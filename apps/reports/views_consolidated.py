"""
The three consolidated reports (docs/reports-consolidation.md). They sit beside the
seven original reports, which are untouched, so the two sets can be compared.
"""

import contextlib
from datetime import date, datetime
from urllib.parse import urlencode

from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from apps.books.decorators import login_and_book_required

from .consolidated import (
    budget_goals_report,
    net_worth_report,
    shift_month,
    spending_report,
)
from .views import _parse_month_range


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
        "reports/consolidated/spending.html",
        {
            "active_tab": "reports",
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
        "reports/consolidated/net_worth.html",
        {
            "active_tab": "reports",
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
        "reports/consolidated/budget_goals.html",
        {
            "active_tab": "reports",
            "page_title": _("Budget & Goals"),
            **report,
            "month": month,
            "prev_month": shift_month(month, -1),
            "next_month": shift_month(month, 1),
        },
    )
