"""
Assembles everything the guided monthly review needs for one month, with every
comparison baseline precomputed (docs/monthly-review-plan.md §2-3).

A pure read -- no writes. Figures are never stored: this always recomputes
from the ledger, so correcting an old transaction corrects every review that
touches it.

Returns rich Python objects (Decimal amounts, Account/Goal instances), same as
`apps.budget.views._budget_figures`. Serializing to JSON-safe types for the
page's `json_script` payload is the view's job, not this one's.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_LIABILITY
from apps.bank_feed.models import BankTransaction
from apps.budget.models import GoalAllocation
from apps.journal.models import JournalEntry, JournalLine, counted_entries
from apps.reports.services import ReportService

from .baselines import ALL_TIME, MonthlyMatrix, build_baselines
from .budget import _month_bounds, _prev_month, budget_breakdown
from .health import account_health


def _add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def _baseline_months_setting():
    return tuple(getattr(settings, "MONTHLY_REVIEW_BASELINE_MONTHS", (1, 3, 6, 12, ALL_TIME)))


def _window_start(month: date, baseline_months, first_month: date | None) -> date:
    """
    The first month the review loads: far enough back for the longest numeric
    baseline, and back to the book's first activity when "all time" is offered.
    """
    numeric = [m for m in baseline_months if m != ALL_TIME]
    start = _add_months(month, -max(numeric, default=0))
    if ALL_TIME in baseline_months and first_month and first_month < start:
        start = first_month
    return start


def _drill_limit():
    return getattr(settings, "MONTHLY_REVIEW_DRILL_LIMIT", 200)


def _book_first_activity_month(book):
    first_date = (
        JournalEntry.objects.filter(book=book)
        .filter(counted_entries())
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    return first_date.replace(day=1) if first_date else None


def _stream_series(book, window_start, month_end):
    """Income activity grouped by payee (falling back to the account name)."""
    lines = (
        JournalLine.objects.filter(
            book=book,
            account__account_group__account_type=ACCOUNT_TYPE_INCOME,
            journal_entry__entry_date__range=(window_start, month_end),
        )
        .filter(counted_entries("journal_entry__"))
        .select_related("journal_entry__payee", "account")
        .annotate(month=TruncMonth("journal_entry__entry_date"))
    )
    streams = {}
    for line in lines:
        payee = line.journal_entry.payee
        if payee:
            key, label = f"payee:{payee.pk}", payee.name
        else:
            key, label = f"account:{line.account_id}", line.account.name
        month_key = line.month.date() if hasattr(line.month, "date") else line.month
        entry = streams.setdefault(key, {"label": label, "by_month": {}})
        signed = line.cr_amount - line.dr_amount
        entry["by_month"][month_key] = entry["by_month"].get(month_key, Decimal("0")) + signed
    return streams


def _goal_series(book, window_start, month_end):
    rows = (
        GoalAllocation.objects.filter(book=book, goal__is_archived=False, month__range=(window_start, month_end))
        .values("goal_id", "goal__name", "month")
        .annotate(total=Sum("amount"))
    )
    goals = {}
    for row in rows:
        entry = goals.setdefault(
            row["goal_id"], {"goal": {"id": row["goal_id"], "name": row["goal__name"]}, "by_month": {}}
        )
        entry["by_month"][row["month"]] = row["total"]
    return goals


def _saved_by_month(goals: dict, months: list) -> dict:
    return {
        month: sum((entry["by_month"].get(month, Decimal("0")) for entry in goals.values()), Decimal("0"))
        for month in months
    }


def _build_matrix(book, window_start, month, month_end, report_service, first_month) -> MonthlyMatrix:
    data = report_service.get_income_statement_data(window_start, month_end, period="month")
    months = data["periods"]

    income = dict(zip(months, data["total_income_per_period"], strict=True))
    spend = dict(zip(months, data["total_expenses_per_period"], strict=True))
    net = dict(zip(months, data["net_profit_per_period"], strict=True))

    categories = {}
    for item in (*data["income"], *data["expenses"]):
        account = item["account"]
        account_type = account.account_group.account_type
        categories[account.pk] = {
            "account": account,
            "type": account_type,
            "group": account.account_group.name,
            "by_month": dict(zip(months, item["per_period"], strict=True)),
        }

    goals = _goal_series(book, window_start, month_end)
    saved = _saved_by_month(goals, months)
    savings_rate = {m: (float(saved[m] / income[m] * 100) if income[m] else 0.0) for m in months}

    streams = _stream_series(book, window_start, month_end)

    return MonthlyMatrix(
        months=months,
        income=income,
        spend=spend,
        net=net,
        saved=saved,
        savings_rate=savings_rate,
        categories=categories,
        streams=streams,
        goals=goals,
        first_month=first_month,
    )


def _current_figures(matrix: MonthlyMatrix, month: date, transaction_count: int) -> dict:
    return {
        "income": matrix.income.get(month, Decimal("0")),
        "spend": matrix.spend.get(month, Decimal("0")),
        "net": matrix.net.get(month, Decimal("0")),
        "saved": matrix.saved.get(month, Decimal("0")),
        "savings_rate": matrix.savings_rate.get(month, 0.0),
        "transaction_count": transaction_count,
    }


def _contra_account_name(line) -> str:
    other = next((other_line for other_line in line.journal_entry.lines.all() if other_line.pk != line.pk), None)
    return other.account.name if other else ""


def _biggest_transactions(book, month, month_end, limit=25) -> list:
    # There is no per-entry detail page in the app (transactions are worked
    # through the Transactions list, not a standalone URL per entry), so every
    # row links there rather than to a page that doesn't exist.
    transactions_url = reverse("journal:transactions_home", args=book.url_args)

    lines = (
        JournalLine.objects.filter(
            book=book,
            account__account_group__account_type=ACCOUNT_TYPE_EXPENSE,
            journal_entry__entry_date__range=(month, month_end),
            dr_amount__gt=0,
        )
        .filter(counted_entries("journal_entry__"))
        .select_related("journal_entry__payee", "account")
        .prefetch_related("journal_entry__lines__account")
        .order_by("-dr_amount")[:limit]
    )
    rows = []
    for line in lines:
        rows.append(
            {
                "date": line.journal_entry.entry_date,
                "payee": line.journal_entry.payee.name if line.journal_entry.payee else "",
                "category": line.account.name,
                "account": _contra_account_name(line),
                "amount": line.dr_amount,
                "entry_url": transactions_url,
            }
        )
    return rows


def _category_transactions(book, month, month_end, limit=200) -> dict:
    lines = (
        JournalLine.objects.filter(
            book=book,
            account__account_group__account_type__in=(ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_EXPENSE),
            journal_entry__entry_date__range=(month, month_end),
        )
        .filter(counted_entries("journal_entry__"))
        .select_related("journal_entry__payee", "account", "account__account_group")
        .prefetch_related("journal_entry__lines__account")
        .order_by("account_id", "journal_entry__entry_date", "pk")
    )
    cat_txns = {}
    for line in lines:
        rows = cat_txns.setdefault(line.account_id, [])
        if len(rows) >= limit:
            continue
        if line.account.account_group.account_type == ACCOUNT_TYPE_EXPENSE:
            signed = line.dr_amount - line.cr_amount
        else:
            signed = line.cr_amount - line.dr_amount
        rows.append(
            {
                "date": line.journal_entry.entry_date,
                "payee": line.journal_entry.payee.name if line.journal_entry.payee else "",
                "memo": line.journal_entry.description,
                "account": _contra_account_name(line),
                "amount": signed,
            }
        )
    return cat_txns


def _balance_by_account(report_service, month_end, baselines) -> list:
    """
    Each non-system balance-sheet account's balance at month end, plus its change
    per baseline: measured from the end of the baseline window's first month, the
    same point the net worth chart starts from when that baseline is selected.
    """

    def amounts(as_of):
        data = report_service.get_balance_sheet_data(as_of)
        return {
            item["account"].pk: item["amount"]
            for section in ("assets", "liabilities", "equity")
            for item in data[section]
        }

    start_by_baseline = {}
    for baseline_id, baseline in baselines.items():
        first_month = date.fromisoformat(baseline["keys"][0])
        start_by_baseline[baseline_id] = _month_bounds(first_month)[1]
    start_amounts = {as_of: amounts(as_of) for as_of in set(start_by_baseline.values())}

    end_data = report_service.get_balance_sheet_data(month_end)
    rows = []
    for section, type_label in (("assets", "asset"), ("liabilities", "liability"), ("equity", "equity")):
        for item in end_data[section]:
            account = item["account"]
            if account.is_system:
                continue
            rows.append(
                {
                    "name": account.name,
                    "type": type_label,
                    "balance": item["amount"],
                    "changes": {
                        baseline_id: item["amount"] - start_amounts[as_of].get(account.pk, Decimal("0"))
                        for baseline_id, as_of in start_by_baseline.items()
                    },
                }
            )
    return rows


CASH_BAND = "cash"


def _net_worth_bands(book, window_start, month_end, month_keys) -> list:
    """
    Month-end net worth split into bands for the composition chart, each value
    signed as its contribution to net worth (dr - cr: assets positive,
    liabilities negative) and aligned with `month_keys`:

    - one CASH_BAND for every account on a bank feed, asset *and* liability --
      bank accounts net of credit cards, so everyday card debt reads as money
      spent rather than as a negative band of its own;
    - one band per account group for the remaining assets and liabilities
      (investments, a mortgage, ...), typed "asset" or "liability".

    Bands that are zero throughout are dropped. Whether the cash band dips below
    zero is decided on the page, over the months the selected baseline shows.
    """
    deltas = (
        JournalLine.objects.filter(
            book=book,
            journal_entry__entry_date__lte=month_end,
            account__account_group__account_type__in=(ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY),
        )
        .filter(counted_entries("journal_entry__"))
        .annotate(month=TruncMonth("journal_entry__entry_date"))
        .values(
            "month",
            "account__has_feed",
            "account__account_group_id",
            "account__account_group__name",
            "account__account_group__account_type",
        )
        .annotate(delta=Sum("dr_amount") - Sum("cr_amount"))
    )

    months = [date.fromisoformat(key) for key in month_keys]
    bands = {}  # key -> {"bucket", "type", "deltas": {month: Decimal}}
    for row in deltas:
        if row["account__has_feed"]:
            key, bucket, band_type = CASH_BAND, _("Bank accounts & credit cards"), CASH_BAND
        else:
            key = row["account__account_group_id"]
            bucket, band_type = row["account__account_group__name"], row["account__account_group__account_type"]
        band = bands.setdefault(key, {"bucket": bucket, "type": band_type, "deltas": {}})
        month = row["month"].date() if hasattr(row["month"], "date") else row["month"]
        band["deltas"][month] = band["deltas"].get(month, Decimal("0")) + row["delta"]

    out = []
    for band in bands.values():
        running = sum((amount for m, amount in band["deltas"].items() if months and m < months[0]), Decimal("0"))
        values = []
        for m in months:
            running += band["deltas"].get(m, Decimal("0"))
            values.append(float(running))
        if any(values):
            out.append({"bucket": band["bucket"], "type": band["type"], "values": values})

    # Cash at the bottom, then other assets (largest first), then liabilities (largest debt nearest zero).
    order = {CASH_BAND: 0, ACCOUNT_TYPE_ASSET: 1, ACCOUNT_TYPE_LIABILITY: 2}
    out.sort(key=lambda b: (order[b["type"]], -abs(b["values"][-1]) if b["values"] else 0))
    return out


def _net_worth_section(book, window_start, month, month_end, report_service, baselines) -> dict:
    """
    Month-end net worth from `window_start` through the reviewed month. The page
    shows the slice matching the selected baseline (its months plus this one).
    """
    trend = report_service.get_net_worth_trend_data_by_date_range(window_start, month_end)
    series = [
        {
            "key": point["date"].replace(day=1).isoformat(),
            "label": date_format(point["date"].replace(day=1), "M Y"),
            "net": point["net_worth"],
            "assets": point["assets"],
            "liabilities": point["liabilities"],
        }
        for point in trend
    ]

    stack = _net_worth_bands(book, window_start, month_end, [point["key"] for point in series])

    now_data = report_service.get_balance_sheet_data(month_end)
    prev_month_end = _month_bounds(_prev_month(month))[1]
    prev_data = report_service.get_balance_sheet_data(prev_month_end)

    return {
        "series": series,
        "stack": stack,
        "now": {
            "net": now_data["net_worth"],
            "assets": now_data["total_assets"],
            "liabilities": now_data["total_liabilities"],
        },
        "prev": {
            "net": prev_data["net_worth"],
            "assets": prev_data["total_assets"],
            "liabilities": prev_data["total_liabilities"],
        },
        "by_account": _balance_by_account(report_service, month_end, baselines),
    }


def _goal_spending(book, month: date) -> list:
    """
    What was spent from goals this month: planned spending paid from money set
    aside, never overspending. Each: name, amount, months_funded (months with a
    positive allocation up to this one).
    """
    from apps.budget.models import Goal, GoalAllocation

    rows = []
    for goal in Goal.objects.filter(book=book).with_progress(month).exclude(spent_this_month=0):
        months_funded = GoalAllocation.objects.filter(goal=goal, month__lte=month, amount__gt=0).count()
        rows.append({"name": goal.name, "amount": goal.spent_this_month, "months_funded": months_funded})
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows


def build_review(book, month: date) -> dict:
    month = month.replace(day=1)
    month_start, month_end = _month_bounds(month)
    baseline_months = _baseline_months_setting()
    first_month = _book_first_activity_month(book)
    window_start = _window_start(month, baseline_months, first_month)

    report_service = ReportService(book)
    matrix = _build_matrix(book, window_start, month, month_end, report_service, first_month)
    baselines, baseline_order, default_baseline = build_baselines(matrix, month, baseline_months)

    transaction_count = BankTransaction.objects.filter(
        book=book, is_archived=False, posted_date__range=(month_start, month_end)
    ).count()

    health = account_health(book, month)
    inbox_url = reverse("bank_feed:bank_feed_home", args=book.url_args)
    for flag in health["flags"]:
        # `health["accounts"][i]["flags"]` holds the same dict objects (not
        # copies), so this also covers the per-account view of the flags.
        flag.setdefault("url", inbox_url)

    review = {
        "month": month.isoformat(),
        "month_label": date_format(month, "F Y"),
        "prev_label": date_format(_prev_month(month), "F Y"),
        "is_current_month": month == date.today().replace(day=1),
        "health": health,
        "current": _current_figures(matrix, month, transaction_count),
        "baselines": baselines,
        "baseline_order": baseline_order,
        "default_baseline": default_baseline,
        "budget": budget_breakdown(book, month),
        "biggest": _biggest_transactions(book, month_start, month_end, limit=25),
        "cat_txns": _category_transactions(book, month_start, month_end, limit=_drill_limit()),
        "net_worth": _net_worth_section(book, window_start, month, month_end, report_service, baselines),
        "goal_spending": _goal_spending(book, month),
        "notes": [
            _(
                '"Saved" is the amount assigned to your savings goals this month -- it '
                "will not tie to any bank balance, since goals are a budget-side concept."
            ),
            _("Voided journal entries are excluded from every figure on this page."),
        ],
    }

    # Imported here (rather than at module scope) to avoid a circular import:
    # insights.py reads the assembled review dict, so it depends on this module.
    from .insights import generate

    review["insights"] = generate(review)
    return review
