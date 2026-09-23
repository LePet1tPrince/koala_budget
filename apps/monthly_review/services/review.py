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

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME
from apps.bank_feed.models import BankTransaction
from apps.budget.models import GoalAllocation
from apps.journal.models import JournalEntry, JournalLine
from apps.reports.services import ReportService

from .baselines import MonthlyMatrix, build_baselines
from .budget import _month_bounds, _prev_month, budget_breakdown
from .health import account_health


def _add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def _baseline_months_setting():
    return tuple(getattr(settings, "MONTHLY_REVIEW_BASELINE_MONTHS", (1, 3, 6, 12)))


def _drill_limit():
    return getattr(settings, "MONTHLY_REVIEW_DRILL_LIMIT", 200)


def _team_first_activity_month(team):
    first_date = (
        JournalEntry.objects.filter(team=team)
        .exclude(status=JournalEntry.STATUS_VOID)
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    return first_date.replace(day=1) if first_date else None


def _stream_series(team, window_start, month_end):
    """Income activity grouped by payee (falling back to the account name)."""
    lines = (
        JournalLine.objects.filter(
            team=team,
            account__account_group__account_type=ACCOUNT_TYPE_INCOME,
            journal_entry__entry_date__range=(window_start, month_end),
        )
        .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
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


def _goal_series(team, window_start, month_end):
    rows = (
        GoalAllocation.objects.filter(team=team, goal__is_archived=False, month__range=(window_start, month_end))
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


def _build_matrix(team, window_start, month, month_end, report_service) -> MonthlyMatrix:
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

    goals = _goal_series(team, window_start, month_end)
    saved = _saved_by_month(goals, months)
    savings_rate = {m: (float(saved[m] / income[m] * 100) if income[m] else 0.0) for m in months}

    streams = _stream_series(team, window_start, month_end)

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
        first_month=_team_first_activity_month(team),
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


def _biggest_transactions(team, month, month_end, limit=25) -> list:
    # There is no per-entry detail page in the app (transactions are worked
    # through the Transactions list, not a standalone URL per entry), so every
    # row links there rather than to a page that doesn't exist.
    transactions_url = reverse("journal:transactions_home", args=[team.slug])

    lines = (
        JournalLine.objects.filter(
            team=team,
            account__account_group__account_type=ACCOUNT_TYPE_EXPENSE,
            journal_entry__entry_date__range=(month, month_end),
            dr_amount__gt=0,
        )
        .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
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


def _category_transactions(team, month, month_end, limit=200) -> dict:
    lines = (
        JournalLine.objects.filter(
            team=team,
            account__account_group__account_type__in=(ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_EXPENSE),
            journal_entry__entry_date__range=(month, month_end),
        )
        .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
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


def _balance_by_account(report_service, window_start, month_end) -> list:
    end_data = report_service.get_balance_sheet_data(month_end)
    start_data = report_service.get_balance_sheet_data(window_start - timedelta(days=1))
    start_by_id = {}
    for section in ("assets", "liabilities", "equity"):
        for item in start_data[section]:
            start_by_id[item["account"].pk] = item["amount"]

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
                    "change": item["amount"] - start_by_id.get(account.pk, Decimal("0")),
                }
            )
    return rows


def _net_worth_section(team, window_start, month, month_end, report_service) -> dict:
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

    composition = report_service.get_balance_composition_data(window_start, month_end)
    stack = [
        {"bucket": group["name"], "values": group["values"]}
        for group in (*composition["asset_groups"], *composition["liability_groups"])
    ]

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
        "by_account": _balance_by_account(report_service, window_start, month_end),
    }


def build_review(team, month: date) -> dict:
    month = month.replace(day=1)
    month_start, month_end = _month_bounds(month)
    baseline_months = _baseline_months_setting()
    window_start = _add_months(month, -max(baseline_months))

    report_service = ReportService(team)
    matrix = _build_matrix(team, window_start, month, month_end, report_service)
    baselines, baseline_order, default_baseline = build_baselines(matrix, month, baseline_months)

    transaction_count = BankTransaction.objects.filter(
        team=team, is_archived=False, posted_date__range=(month_start, month_end)
    ).count()

    health = account_health(team, month)
    inbox_url = reverse("bank_feed:bank_feed_home", args=[team.slug])
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
        "budget": budget_breakdown(team, month),
        "biggest": _biggest_transactions(team, month_start, month_end, limit=25),
        "cat_txns": _category_transactions(team, month_start, month_end, limit=_drill_limit()),
        "net_worth": _net_worth_section(team, window_start, month, month_end, report_service),
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
