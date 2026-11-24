"""
Reports: Monthly Review (its own app) plus the three reports below -- Income &
Spending, Net Worth, Budget & Goals (docs/reports-consolidation.md) -- and the
CSV exports they link.
"""

from datetime import date, datetime
from urllib.parse import urlencode

from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.books.decorators import login_and_book_required

from .api import net_worth_payload, spending_payload
from .consolidated import (
    COLUMN_LABELS,
    bucket_for,
    column_periods,
    net_worth_report,
    period_bounds,
    spending_report,
)
from .exports import (
    export_account_activity_csv,
    export_balance_sheet_csv,
    export_income_statement_csv,
    export_transactions_csv,
)
from .timeframes import date_range_from_request, month_range_from_request


@login_and_book_required
def reports_home(request, team_slug, book_slug):
    """Reports has no landing page of its own: it opens on Income & Spending (the sidebar lists the rest)."""
    return redirect("reports:spending", team_slug, book_slug)


def _parse_month_range(request):
    """
    Parse start_month/end_month GET params (YYYY-MM) into a (start_date, end_date)
    range of whole months, defaulting to the book's report timeframe, else the
    last 12 months.
    """
    today = date.today()
    return month_range_from_request(request, (date(today.year - 1, today.month, 1), today))


def _drill_qs(start_date, end_date):
    """Query string that opens an account page on the report's own range."""
    return urlencode({"start_date": start_date.isoformat(), "end_date": end_date.isoformat()})


def _attach_period_drill(report, start_date, end_date):
    """
    Give every account row of the statement `period_cells`: (amount, drill_qs) per
    column, the query string opening the account on that column's dates.
    """
    data = report["data"]
    drill = [
        _drill_qs(first, last) for first, last in period_bounds(data["periods"], report["period"], start_date, end_date)
    ]
    items = [item for group in data["income_groups"] + data["expense_groups"] for item in group["accounts"]]
    items += data["goal_spending"]["items"]
    for item in items:
        item["period_cells"] = list(zip(item["per_period"], drill, strict=True))


def _column_choice(request, start_date, end_date):
    """
    The statement's column period from `?columns=` (year/quarter/month), or None for
    Total. A period the range doesn't span more than one of falls back to Total -- the
    date picker keeps `columns` when the range changes. The legacy `columns=period`
    means the range's default bucket.
    """
    offered = column_periods(start_date, end_date)
    requested = request.GET.get("columns")
    if requested == "period":
        requested = bucket_for(start_date, end_date)
    return (requested if requested in offered else None), offered


@login_and_book_required
def spending(request, team_slug, book_slug):
    """Income & Spending: money in and out over a range, with the statement and the flow."""
    today = date.today()
    start_date, end_date = date_range_from_request(request, (date(today.year, 1, 1), today))
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    chosen, offered = _column_choice(request, start_date, end_date)
    by_period = chosen is not None
    params = request.GET.copy()
    params.pop("columns", None)
    column_options = [{"key": "total", "label": _("Total"), "qs": params.urlencode(), "active": not by_period}]
    for key in offered:
        params["columns"] = key
        column_options.append(
            {"key": key, "label": COLUMN_LABELS[key], "qs": params.urlencode(), "active": key == chosen}
        )

    report = spending_report(request.book, start_date, end_date, period=chosen)
    # The charts draw from what `GET …/reports/api/spending/` would return for this
    # range; the page embeds it rather than have them fetch the report a second time.
    report_json = spending_payload(report, start_date, end_date, chosen, offered)
    if by_period:
        _attach_period_drill(report, start_date, end_date)
    return render(
        request,
        "reports/spending.html",
        {
            "active_tab": "reports",
            "active_report": "spending",
            "page_title": _("Income & Spending"),
            **report,
            "report_json": report_json,
            "by_period": by_period,
            "column_options": column_options,
            "export_qs": _drill_qs(start_date, end_date),
            "drill_qs": _drill_qs(start_date, end_date),
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_and_book_required
def net_worth(request, team_slug, book_slug):
    """Net Worth: what you own and owe at the end of a range, and what changed since its start."""
    start_date, end_date = _parse_month_range(request)
    end_date = min(end_date, date.today())
    if start_date > end_date:
        start_date = end_date.replace(day=1)

    report = net_worth_report(request.book, start_date, end_date)
    return render(
        request,
        "reports/net_worth.html",
        {
            "active_tab": "reports",
            "active_report": "net_worth",
            "page_title": _("Net Worth"),
            **report,
            # The charts draw from the `GET …/reports/api/net-worth/` body for this range, embedded.
            "report_json": net_worth_payload(report, start_date, end_date),
            "drill_qs": _drill_qs(start_date, end_date),
            "export_qs": urlencode({"as_of_date": end_date.isoformat()}),
            "start_date": start_date,
            "end_date": end_date,
        },
    )


# --- Export Views ---


def _parse_date_range(request):
    """
    Parse start_date and end_date from GET params. A missing side defaults to this
    month to today; an unparseable one, the whole range.
    """
    today = date.today()
    default_start, default_end = today.replace(day=1), today
    start_date_param = request.GET.get("start_date")
    end_date_param = request.GET.get("end_date")
    try:
        start_date = datetime.strptime(start_date_param, "%Y-%m-%d").date() if start_date_param else default_start
        end_date = datetime.strptime(end_date_param, "%Y-%m-%d").date() if end_date_param else default_end
    except ValueError:
        start_date, end_date = default_start, default_end
    return start_date, end_date


@login_and_book_required
def export_income_statement(request, team_slug, book_slug):
    """Export income statement as CSV."""
    start_date, end_date = _parse_date_range(request)
    return export_income_statement_csv(request.book, start_date, end_date)


@login_and_book_required
def export_balance_sheet(request, team_slug, book_slug):
    """Export balance sheet as CSV."""
    as_of_date_param = request.GET.get("as_of_date")
    try:
        as_of_date = datetime.strptime(as_of_date_param, "%Y-%m-%d").date() if as_of_date_param else date.today()
    except ValueError:
        as_of_date = date.today()
    return export_balance_sheet_csv(request.book, as_of_date)


@login_and_book_required
def export_account_activity_view(request, team_slug, book_slug, account_id):
    """Export one account's activity (the account page's table) as CSV."""
    from apps.accounts.models import Account

    account = get_object_or_404(Account, book=request.book, pk=account_id)
    start_date, end_date = _parse_date_range(request)
    return export_account_activity_csv(request.book, account, start_date, end_date)


@login_and_book_required
def export_transactions(request, team_slug, book_slug):
    """Export all transactions as CSV."""
    start_date, end_date = _parse_date_range(request)
    return export_transactions_csv(request.book, start_date, end_date)
