"""
The reports as data (`/a/{team}/{book}/reports/api/...`): the reports home, Income &
Spending, Net Worth, and Budget & Goals. Each is built by the same function as its
page (`consolidated.py`) and takes the page's query parameters; a parameter that is
present but malformed is a 400 rather than the default the page falls back to.

The CSV exports (`export/...`) stay file downloads.
"""

from datetime import date, timedelta

from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from apps.api.base import BookAPIView, month_parameter
from apps.utils.months import add_months

from .consolidated import (
    COLUMN_LABELS,
    column_periods,
    net_worth_report,
    period_bounds,
    spending_report,
)
from .serializers import (
    NetWorthQuerySerializer,
    NetWorthReportSerializer,
    SpendingQuerySerializer,
    SpendingReportSerializer,
)

TAGS = ["reports"]


SPENDING_PARAMETERS = [
    OpenApiParameter("start_date", OpenApiTypes.DATE, description="First day of the range (with end_date)."),
    OpenApiParameter("end_date", OpenApiTypes.DATE, description="Last day of the range (with start_date)."),
    OpenApiParameter(
        "columns",
        OpenApiTypes.STR,
        enum=["total", "year", "quarter", "month"],
        description="The statement's columns (default total).",
    ),
]


class SpendingReportView(BookAPIView):
    """
    Income & Spending: money in and out over a range -- summary stats, the
    statement by group and account with per-period figures, and goal spending.
    The range defaults to the book's report timeframe, else this year to date.
    """

    @extend_schema(
        operation_id="reports_spending_retrieve",
        tags=TAGS,
        parameters=SPENDING_PARAMETERS,
        responses=SpendingReportSerializer,
    )
    def get(self, request, team_slug, book_slug):
        query = SpendingQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        today = date.today()
        start_date = query.validated_data.get("start_date")
        end_date = query.validated_data.get("end_date")
        if start_date is None:
            start_date, end_date = date(today.year, 1, 1), today
        offered = column_periods(start_date, end_date)
        requested = query.validated_data.get("columns")
        chosen = requested if requested in offered else None
        report = spending_report(self.book, start_date, end_date, period=chosen)
        return Response(spending_payload(report, start_date, end_date, chosen, offered))


def spending_payload(report, start_date, end_date, chosen, offered):
    """
    The `GET …/reports/api/spending/` body for a `spending_report` already built with
    column period `chosen` (None: Total) out of `offered`. The Income & Spending page
    embeds the same body for its charts rather than having them fetch it again.
    """
    data = report["data"]
    goal_spending = data["goal_spending"]
    bounds = period_bounds(data["periods"], report["period"], start_date, end_date)
    return SpendingReportSerializer(
        {
            "start_date": start_date,
            "end_date": end_date,
            "period": report["period"],
            "columns": {
                "selected": chosen or "total",
                "options": [{"key": "total", "label": _("Total")}]
                + [{"key": key, "label": COLUMN_LABELS[key]} for key in offered],
            },
            "periods": [
                {"start_date": first, "end_date": last, "label": label}
                for (first, last), label in zip(bounds, data["period_labels"], strict=True)
            ],
            "has_activity": report["has_activity"],
            "stats": report["stats"],
            "income": {
                "total": data["total_income"],
                "per_period": data["total_income_per_period"],
                "groups": data["income_groups"],
            },
            "expenses": {
                "total": data["total_expenses"],
                "per_period": data["total_expenses_per_period"],
                "groups": data["expense_groups"],
            },
            "net": data["net_profit"],
            "net_per_period": data["net_profit_per_period"],
            "goal_spending": goal_spending,
            "net_after_goal_spending": data["net_after_goal_spending"],
            "net_after_goal_spending_per_period": data["net_after_goal_spending_per_period"],
        }
    ).data


NET_WORTH_PARAMETERS = [
    month_parameter("start_month", description="First month of the range, as YYYY-MM (with end_month)."),
    month_parameter("end_month", description="Last month of the range, as YYYY-MM (with start_month)."),
]


class NetWorthReportView(BookAPIView):
    """
    Net Worth: what you own and owe at the end of a range of whole months and what
    changed since its start, by section, group and account; the month-end trend and
    composition. The range defaults to the book's report timeframe, else the last 12
    months; it never runs past today.
    """

    @extend_schema(
        operation_id="reports_net_worth_retrieve",
        tags=TAGS,
        parameters=NET_WORTH_PARAMETERS,
        responses=NetWorthReportSerializer,
    )
    def get(self, request, team_slug, book_slug):
        query = NetWorthQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        today = date.today()
        start_month = query.validated_data.get("start_month")
        if start_month is None:
            start_date, end_date = date(today.year - 1, today.month, 1), today
        else:
            start_date = start_month
            end_date = add_months(query.validated_data["end_month"], 1) - timedelta(days=1)
        end_date = min(end_date, today)
        if start_date > end_date:
            start_date = end_date.replace(day=1)

        return Response(net_worth_payload(net_worth_report(self.book, start_date, end_date), start_date, end_date))


def net_worth_payload(report, start_date, end_date):
    """The `GET …/reports/api/net-worth/` body for a `net_worth_report`; the Net Worth page embeds the same."""
    return NetWorthReportSerializer({**report, "start_date": start_date, "end_date": end_date}).data
