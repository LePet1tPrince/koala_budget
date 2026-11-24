"""
Request and response shapes of the reports API (`/a/{team}/{book}/reports/api/...`).

Rows carry ids, never model instances or links: an account row's drill-down is
the account (`id`) opened on the report's range (`start_date`/`end_date`), and a
statement cell's is the same account on that column's `periods[i]` dates.
"""

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.serializers import DateRangeQuerySerializer
from apps.api.base import MonthField

from .consolidated import COLUMN_PERIODS

COLUMN_CHOICES = ["total", *COLUMN_PERIODS]
NET_WORTH_SECTION_KEYS = ["assets", "liabilities"]


def _money(**kwargs):
    return serializers.DecimalField(max_digits=15, decimal_places=2, **kwargs)


def _money_list(**kwargs):
    return serializers.ListField(child=_money(), **kwargs)


# --- Income & Spending ----------------------------------------------------------


class SpendingQuerySerializer(DateRangeQuerySerializer):
    """`?start_date=&end_date=` (both or neither; neither = the default range, else this year) and `?columns=`."""

    columns = serializers.ChoiceField(
        choices=COLUMN_CHOICES,
        required=False,
        help_text="The statement's columns: `total`, or by year/quarter/month. One the range does not span more "
        "than one of falls back to `total`.",
    )


class SpendingColumnOptionSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=COLUMN_CHOICES)
    label = serializers.CharField()


class SpendingColumnsSerializer(serializers.Serializer):
    selected = serializers.ChoiceField(choices=COLUMN_CHOICES, help_text="What the statement shows.")
    options = SpendingColumnOptionSerializer(many=True, help_text="Total, then each period the range spans.")


class ReportPeriodSerializer(serializers.Serializer):
    start_date = serializers.DateField(help_text="First day of the column, clamped to the report's range.")
    end_date = serializers.DateField(help_text="Last day of the column, clamped to the report's range.")
    label = serializers.CharField()


class SpendingStatsSerializer(serializers.Serializer):
    income = _money()
    expenses = _money()
    goal_spending = _money(help_text="Spent from goals: planned, paid from money set aside.")
    net = _money(help_text="Income − expenses (kept).")
    net_after_goals = _money(help_text="Net − goal spending.")
    savings_rate = serializers.FloatField(allow_null=True, help_text="Net / income × 100; null with no income.")
    avg_net = _money(help_text="Net after goal spending, per month of the range.")
    num_months = serializers.IntegerField()


class SpendingAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="account.id")
    name = serializers.CharField(source="account.name")
    amount = _money()
    per_period = _money_list(help_text="Aligned with `periods`.")


class SpendingGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="group.id")
    name = serializers.CharField(source="group.name")
    total = _money(source="subtotal")
    per_period = _money_list()
    accounts = SpendingAccountSerializer(many=True)


class SpendingSectionSerializer(serializers.Serializer):
    total = _money()
    per_period = _money_list()
    groups = SpendingGroupSerializer(many=True)


class SpendingGoalSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(source="account.id", help_text="The goal's account (what a drill opens).")
    goal_id = serializers.IntegerField(source="account.goal.id")
    name = serializers.CharField(source="account.goal.name")
    amount = _money()
    per_period = _money_list()


class SpendingGoalSectionSerializer(serializers.Serializer):
    total = _money()
    per_period = _money_list()
    goals = SpendingGoalSerializer(many=True, source="items")


class SpendingReportSerializer(serializers.Serializer):
    """
    Income & Spending over a range: summary stats, the statement (income and expense
    groups, then goal spending), per-period figures for its columns and the chart.
    The flow (Sankey) is the statement's accounts and group totals.
    """

    start_date = serializers.DateField()
    end_date = serializers.DateField()
    period = serializers.ChoiceField(
        choices=list(COLUMN_PERIODS), help_text="The length of each `periods` column and chart bar."
    )
    columns = SpendingColumnsSerializer()
    periods = ReportPeriodSerializer(many=True)
    has_activity = serializers.BooleanField(help_text="Any income, spending or goal spending in the range.")
    stats = SpendingStatsSerializer()
    income = SpendingSectionSerializer()
    expenses = SpendingSectionSerializer()
    net = _money(help_text="Income − expenses.")
    net_per_period = _money_list()
    goal_spending = SpendingGoalSectionSerializer()
    net_after_goal_spending = _money()
    net_after_goal_spending_per_period = _money_list()


# --- Net Worth -------------------------------------------------------------------


class NetWorthQuerySerializer(serializers.Serializer):
    """`?start_month=&end_month=` (YYYY-MM, both or neither; neither = the book's default range, else 12 months)."""

    start_month = MonthField(required=False)
    end_month = MonthField(required=False)

    def validate(self, attrs):
        start, end = attrs.get("start_month"), attrs.get("end_month")
        if (start is None) != (end is None):
            raise serializers.ValidationError(_("Give both start_month and end_month, or neither."))
        if start is not None and start > end:
            raise serializers.ValidationError({"end_month": [_("The end month is before the start month.")]})
        return attrs


class NetWorthStatsSerializer(serializers.Serializer):
    net_worth = _money(help_text="At the end of the range.")
    start_net_worth = _money(help_text="The day before the range starts.")
    change = _money()
    pct_change = serializers.FloatField(allow_null=True)
    assets = _money()
    liabilities = _money()
    debt_ratio = serializers.FloatField(allow_null=True, help_text="Liabilities / assets × 100.")
    num_months = serializers.IntegerField()


class NetWorthAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="account.id")
    name = serializers.CharField(source="account.name")
    start = _money()
    end = _money()
    change = _money()


class NetWorthGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="group.id")
    name = serializers.CharField(source="group.name")
    start = _money()
    end = _money()
    change = _money()
    accounts = NetWorthAccountSerializer(many=True, source="rows")


class NetWorthSectionSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=NET_WORTH_SECTION_KEYS)
    start = _money()
    end = _money()
    change = _money()
    groups = NetWorthGroupSerializer(many=True)


class NetWorthPointSerializer(serializers.Serializer):
    date = serializers.DateField(help_text="A month end (the last is the range's end).")
    net_worth = _money()
    assets = _money()
    liabilities = _money()


class CompositionBandSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="An account group, or “Other assets” / “Other debts” for a folded tail.")
    type = serializers.ChoiceField(choices=["asset", "liability"])
    values = _money_list(help_text="Signed as the contribution to net worth (debts negative), aligned with `dates`.")


class CompositionSerializer(serializers.Serializer):
    dates = serializers.ListField(child=serializers.DateField(), source="labels")
    bands = CompositionBandSerializer(many=True, source="groups")


class NetWorthReportSerializer(serializers.Serializer):
    """Net Worth over a range: balances at its start and end by section/group/account, the trend, the composition."""

    start_date = serializers.DateField()
    end_date = serializers.DateField(help_text="Never after today.")
    stats = NetWorthStatsSerializer()
    sections = NetWorthSectionSerializer(many=True)
    trend = NetWorthPointSerializer(many=True)
    composition = CompositionSerializer(
        allow_null=True, source="composition_data", help_text="Month-end balance per group; null with no groups."
    )
