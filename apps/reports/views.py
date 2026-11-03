"""
Reports: Monthly Review (its own app) plus the three reports below -- Income &
Spending, Net Worth, Budget & Goals (docs/reports-consolidation.md) -- and the
CSV exports they link.
"""

import contextlib
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _

from apps.books.decorators import login_and_book_required
from apps.utils.months import add_months

from .consolidated import (
    bucket_for,
    budget_goals_report,
    column_periods,
    net_worth_report,
    spending_report,
)
from .exports import (
    export_account_activity_csv,
    export_balance_sheet_csv,
    export_income_statement_csv,
    export_transactions_csv,
)
from .timeframes import date_range_from_request, default_range, month_range_from_request


@login_and_book_required
def reports_home(request, team_slug, book_slug):
    """
    Reports home page with navigation to different reports.
    """
    from apps.monthly_review.models import MonthlyReviewState

    last_reviewable_month = add_months(date.today(), -1)
    reviewed = MonthlyReviewState.objects.filter(
        book=request.book, month=last_reviewable_month, completed_at__isnull=False
    ).exists()

    return render(
        request,
        "reports/reports_home.html",
        {
            "active_tab": "reports",
            "page_title": _("Reports"),
            "monthly_review_last_month": last_reviewable_month,
            "monthly_review_reviewed": reviewed,
        },
    )


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


PERIOD_MONTHS = {"month": 1, "quarter": 3, "year": 12}


def _attach_period_drill(report, start_date, end_date):
    """
    Give every account row of the statement `period_cells`: (amount, drill_qs) per
    column, the query string opening the account on that column's dates (clamped to
    the report's range, so a partial first or last month stays partial).
    """
    data = report["data"]
    step = PERIOD_MONTHS[report["period"]]
    drill = [
        _drill_qs(max(first, start_date), min(add_months(first, step) - timedelta(days=1), end_date))
        for first in data["periods"]
    ]
    items = [item for group in data["income_groups"] + data["expense_groups"] for item in group["accounts"]]
    items += data["goal_spending"]["items"]
    for item in items:
        item["period_cells"] = list(zip(item["per_period"], drill, strict=True))


COLUMN_LABELS = {"year": _("By year"), "quarter": _("By quarter"), "month": _("By month")}


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
            "drill_qs": _drill_qs(start_date, end_date),
            "export_qs": urlencode({"as_of_date": end_date.isoformat()}),
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_and_book_required
def budget_goals(request, team_slug, book_slug):
    """Budget & Goals: where every dollar is going this month -- goals, envelopes (one total), Unassigned."""
    month = date.today().replace(day=1)
    with contextlib.suppress(ValueError):
        year, month_num = map(int, request.GET.get("month", "").split("-")[:2])
        month = date(year, month_num, 1)

    report = budget_goals_report(request.book, month)
    return render(
        request,
        "reports/budget_goals.html",
        {
            "active_tab": "reports",
            "active_report": "budget_goals",
            "page_title": _("Budget & Goals"),
            **report,
            "month": month,
            "prev_month": add_months(month, -1),
            "next_month": add_months(month, 1),
        },
    )


# --- Export Views ---


def _parse_date_range(request):
    """
    Parse start_date and end_date from GET params. A missing side takes the book's
    default report range (else this month to today); an unparseable one, the whole range.
    """
    today = date.today()
    default_start, default_end = default_range(request.book, (today.replace(day=1), today))
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
