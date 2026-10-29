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

from .consolidated import (
    budget_goals_report,
    net_worth_report,
    shift_month,
    spending_report,
)
from .exports import (
    export_account_activity_csv,
    export_balance_sheet_csv,
    export_income_statement_csv,
    export_transactions_csv,
)


@login_and_book_required
def reports_home(request, team_slug, book_slug):
    """
    Reports home page with navigation to different reports.
    """
    from apps.monthly_review.models import MonthlyReviewState
    from apps.monthly_review.services.budget import _prev_month

    last_reviewable_month = _prev_month(date.today().replace(day=1))
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
    range of whole months, defaulting to the last 12 months.
    """
    start_month_param = request.GET.get("start_month")
    end_month_param = request.GET.get("end_month")
    if start_month_param and end_month_param:
        try:
            start_year, start_month_num = map(int, start_month_param.split("-"))
            end_year, end_month_num = map(int, end_month_param.split("-"))
            start_date = date(start_year, start_month_num, 1)
            end_date = (date(end_year, end_month_num, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            return start_date, end_date
        except ValueError:
            pass
    today = date.today()
    return date(today.year - 1, today.month, 1), today


def _drill_qs(start_date, end_date):
    """Query string that opens an account page on the report's own range."""
    return urlencode({"start_date": start_date.isoformat(), "end_date": end_date.isoformat()})


@login_and_book_required
def spending(request, team_slug, book_slug):
    """Income & Spending: money in and out over a range, with the statement and the flow."""
    today = date.today()
    start_date, end_date = date(today.year, 1, 1), today
    with contextlib.suppress(KeyError, ValueError):
        start_date, end_date = (
            datetime.strptime(request.GET["start_date"], "%Y-%m-%d").date(),
            datetime.strptime(request.GET["end_date"], "%Y-%m-%d").date(),
        )
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    by_period = request.GET.get("columns") == "period"
    columns_params = request.GET.copy()
    columns_params.pop("columns", None)
    total_qs = columns_params.urlencode()
    columns_params["columns"] = "period"
    period_qs = columns_params.urlencode()

    report = spending_report(request.book, start_date, end_date)
    return render(
        request,
        "reports/spending.html",
        {
            "active_tab": "reports",
            "active_report": "spending",
            "page_title": _("Income & Spending"),
            **report,
            "by_period": by_period,
            "total_qs": total_qs,
            "period_qs": period_qs,
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
            "prev_month": shift_month(month, -1),
            "next_month": shift_month(month, 1),
        },
    )


# --- Export Views ---


def _parse_date_range(request):
    """Parse start_date and end_date from GET params, with defaults to current month."""
    today = date.today()
    start_date_param = request.GET.get("start_date")
    end_date_param = request.GET.get("end_date")
    try:
        start_date = (
            datetime.strptime(start_date_param, "%Y-%m-%d").date() if start_date_param else today.replace(day=1)
        )  # noqa: E501
        end_date = datetime.strptime(end_date_param, "%Y-%m-%d").date() if end_date_param else today
    except ValueError:
        start_date = today.replace(day=1)
        end_date = today
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
