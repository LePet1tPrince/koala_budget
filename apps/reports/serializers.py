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
from apps.budget.unassigned import STATE_NEGATIVE, STATE_POSITIVE, STATE_ZERO

from .consolidated import COLUMN_PERIODS

COLUMN_CHOICES = ["total", *COLUMN_PERIODS]
NET_WORTH_SECTION_KEYS = ["assets", "liabilities"]
WATERFALL_KEYS = ["net_worth", "envelopes", "goals", "unassigned"]


def _money(**kwargs):
    return serializers.DecimalField(max_digits=15, decimal_places=2, **kwargs)


def _money_list(**kwargs):
    return serializers.ListField(child=_money(), **kwargs)


# --- Reports home ---------------------------------------------------------------


class ReportsHomeMonthlyReviewSerializer(serializers.Serializer):
    month = MonthField(help_text="Last month, the one the Monthly Review opens on.")
    reviewed = serializers.BooleanField(help_text="Its review was completed.")


class ReportsHomeSerializer(serializers.Serializer):
    monthly_review = ReportsHomeMonthlyReviewSerializer()


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


class WealthRankSerializer(serializers.Serializer):
    wealth = _money(help_text="Net worth per adult: what was ranked.")
    percentile = serializers.FloatField(help_text="Share of the world's adults with less, 0–100.")
    top_pct_display = serializers.CharField(help_text="100 − percentile, to three significant figures.")
    rank = serializers.IntegerField(help_text="1 = richest.")
    population = serializers.IntegerField(help_text="Adults in the distribution.")
    places_per_dollar = serializers.FloatField(allow_null=True)
    dollars_per_place = serializers.FloatField(allow_null=True)
    data_year = serializers.IntegerField()
    price_year = serializers.IntegerField()
    source = serializers.CharField()


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
    wealth_rank = WealthRankSerializer()
    household_adults = serializers.IntegerField()


# --- Budget & Goals --------------------------------------------------------------


class BudgetGoalsUnassignedSerializer(serializers.Serializer):
    amount = _money(help_text="Net worth − envelopes − goals.")
    state = serializers.ChoiceField(choices=[STATE_POSITIVE, STATE_ZERO, STATE_NEGATIVE])
    label = serializers.CharField(help_text="“Unassigned”, or “Over-assigned” when negative.")
    net_worth = _money()
    envelopes = _money(help_text="Unspent expense budget (an overspent envelope counts as 0).")
    goals = _money(help_text="Left in goals (an overspent goal counts as 0).")
    expects_income = serializers.BooleanField(help_text="The book budgets income before it arrives.")
    income_due = _money(help_text="Expected income: budgeted income not yet received.")
    overspent = _money(help_text="Expense envelopes still showing as negative.")
    goals_overspent = _money()


class WaterfallStepSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=WATERFALL_KEYS)
    label = serializers.CharField()
    value = _money()
    start = _money()
    end = _money()
    total = serializers.BooleanField(help_text="A total bar (from zero) rather than a step.")


class BudgetGoalsGoalSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    has_target = serializers.BooleanField()
    target_amount = _money()
    target_date = serializers.DateField(allow_null=True)
    allocated = _money(help_text="Set aside so far.")
    spent = _money(help_text="Spent from the goal so far.")
    progress_percentage = serializers.FloatField()


class BudgetGoalsGoalRowSerializer(serializers.Serializer):
    goal = BudgetGoalsGoalSerializer()
    needed = _money(allow_null=True, help_text="This month's plan; null with no plan or once funded (see `note`).")
    note = serializers.ChoiceField(choices=["", "funded", "no_target_date"], allow_blank=True)
    assigned = _money(help_text="Assigned to the goal this month.")
    spent = _money(help_text="Spent from the goal this month.")
    left = _money()
    pct = serializers.FloatField(allow_null=True, help_text="Assigned / needed × 100.")
    pct_capped = serializers.FloatField()


class BudgetGoalsGoalTotalsSerializer(serializers.Serializer):
    needed = _money()
    assigned = _money()
    spent = _money()
    allocated = _money(help_text="Σ allocated over every open goal: the Goals page's Total Saved.")
    left = _money()


class BudgetGoalsEnvelopesSerializer(serializers.Serializer):
    total = _money(help_text="What sits in the envelopes (a term of Unassigned).")
    leftover = _money(help_text="Left over from last month.")
    assigned = _money()
    spent = _money()
    available = _money()
    overspent = _money()


class BudgetGoalsReportSerializer(serializers.Serializer):
    """Budget & Goals for one month: where every dollar of net worth is going."""

    month = MonthField()
    unassigned = BudgetGoalsUnassignedSerializer()
    expected_income_label = serializers.CharField()
    waterfall = WaterfallStepSerializer(many=True, help_text="Net worth stepping down to Unassigned.")
    goal_rows = BudgetGoalsGoalRowSerializer(many=True)
    goal_totals = BudgetGoalsGoalTotalsSerializer()
    envelopes = BudgetGoalsEnvelopesSerializer()
