"""
Request and response shapes of the guided monthly review's API
(`/a/{team}/{book}/reports/monthly-review/api/...`).

The review (`services/review.build_review`) is one large read with every
comparison baseline precomputed, so a client reslices it per baseline without a
new request. Objects appear as `{id, name}`, money as decimal strings, months as
`YYYY-MM`; nothing in it is a link -- a client builds the Inbox / Transactions
URLs itself (the insights that point somewhere say where with `action`).
"""

from datetime import date

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.api.base import MONTH_SCHEMA, MonthField
from apps.utils.months import format_month

from .services.baselines import BASELINE_META
from .services.health import NO_TRANSACTIONS, STALE_ACCOUNT, UNCATEGORIZED, UNRECONCILED

BASELINE_IDS = [meta["id"] for meta in BASELINE_META.values()]


def _money(**kwargs):
    return serializers.DecimalField(max_digits=15, decimal_places=2, **kwargs)


def _optional_money(**kwargs):
    return _money(allow_null=True, default=None, **kwargs)


@extend_schema_field(MONTH_SCHEMA)
class MonthKeyField(serializers.Field):
    """A month the review keys by its ISO first day (`2026-08-01`), written as `YYYY-MM`."""

    def to_representation(self, value):
        return format_month(date.fromisoformat(value) if isinstance(value, str) else value)


class RefSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    name = serializers.CharField()


class DictRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


# --- Step 1: data health ----------------------------------------------------------


class HealthFlagSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[NO_TRANSACTIONS, STALE_ACCOUNT, UNCATEGORIZED, UNRECONCILED])
    account = RefSerializer()
    last_transaction_date = serializers.DateField(allow_null=True, default=None, help_text="stale_account only.")
    days = serializers.IntegerField(allow_null=True, default=None, help_text="stale_account: days before month end.")
    count = serializers.IntegerField(allow_null=True, default=None, help_text="uncategorized / unreconciled.")
    gap = _optional_money(help_text="unreconciled: balance − reconciled balance.")


class HealthAccountSerializer(serializers.Serializer):
    account = RefSerializer()
    account_type = serializers.ChoiceField(choices=["asset", "liability"])
    institution = serializers.CharField(allow_null=True)
    transaction_count = serializers.IntegerField()
    uncategorized_count = serializers.IntegerField()
    unreconciled_count = serializers.IntegerField()
    last_transaction_date = serializers.DateField(allow_null=True)
    balance = _money()
    reconciled_balance = _money()
    balance_gap = _money()
    balance_change = _money()
    flags = HealthFlagSerializer(many=True)


class HealthSerializer(serializers.Serializer):
    accounts = HealthAccountSerializer(many=True, help_text="Every account on a bank feed.")
    flags = HealthFlagSerializer(many=True, help_text="Every account's flags, flattened.")
    all_clear = serializers.BooleanField()


# --- Figures and baselines --------------------------------------------------------


class CurrentFiguresSerializer(serializers.Serializer):
    income = _money()
    spend = _money()
    net = _money()
    saved = _money(help_text="Assigned to goals this month.")
    savings_rate = serializers.FloatField(help_text="Saved / income × 100; 0 with no income.")
    transaction_count = serializers.IntegerField()


class BaselineAveragesSerializer(serializers.Serializer):
    income = _money()
    spend = _money()
    net = _money()
    saved = _money()
    savings_rate = serializers.FloatField()


class StreamRowSerializer(serializers.Serializer):
    payee = serializers.CharField(help_text="The payee, else the income account's name.")
    amount = _money(help_text="This month.")
    avg = _money()
    vs_avg = _money()
    new = serializers.BooleanField(help_text="Income this month with none in the baseline.")


class SavingRowSerializer(serializers.Serializer):
    goal = DictRefSerializer()
    amount = _money(help_text="Saved this month.")
    prev = _money(help_text="Saved last month.")
    avg = _money()
    vs_avg = _money()


class BaselineSerializer(serializers.Serializer):
    id = serializers.ChoiceField(choices=BASELINE_IDS)
    label = serializers.CharField()
    short = serializers.CharField()
    against = serializers.CharField(help_text="How a sentence names it: “the 3-month average”.")
    span = serializers.CharField(help_text="Its months, as a label: “May – Jul 2026”.")
    months = serializers.IntegerField(help_text="How many months it averages.")
    clamped = serializers.BooleanField(help_text="Shorter than its name: the book's history starts later.")
    keys = serializers.ListField(child=MonthKeyField(), help_text="Its months, oldest first.")
    avgs = BaselineAveragesSerializer()
    streams = StreamRowSerializer(many=True, help_text="Income by payee, largest this month first.")
    cat_avg = serializers.DictField(child=_money(), help_text="Category (account) id → its average.")
    saving_rows = SavingRowSerializer(many=True)


# --- Budget ------------------------------------------------------------------------


class BudgetCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    income = serializers.BooleanField(help_text="An income category: `spent` is what was received.")
    assigned = _money()
    spent = _money()
    prev = _money(help_text="Spent last month.")
    available = _money()
    count = serializers.IntegerField(help_text="Transactions this month.")
    unbudgeted = serializers.BooleanField()


class BudgetGroupSerializer(serializers.Serializer):
    name = serializers.CharField()
    income = serializers.BooleanField()
    assigned = _money()
    spent = _money()
    prev = _money()
    available = _money()
    count = serializers.IntegerField()
    categories = BudgetCategorySerializer(many=True)


class BudgetTotalsSerializer(serializers.Serializer):
    assigned = _money()
    spent = _money()
    available = _money()


class OverspentRowSerializer(serializers.Serializer):
    category = RefSerializer()
    group = RefSerializer()
    assigned = _money()
    spent = _money()
    available = _money()
    over = _money(help_text="Spent − assigned.")


class BudgetBreakdownSerializer(serializers.Serializer):
    groups = BudgetGroupSerializer(many=True, help_text="Budget-page order, income first.")
    totals = BudgetTotalsSerializer()
    overspent = OverspentRowSerializer(many=True, help_text="Ended the month with a negative available.")
    over_assigned = OverspentRowSerializer(many=True, help_text="Beat the assignment, a cushion absorbed it.")


# --- Transactions, net worth, goals ----------------------------------------------


class BiggestTransactionSerializer(serializers.Serializer):
    entry_id = serializers.IntegerField(help_text="The journal entry (open it in the Transactions list).")
    date = serializers.DateField()
    payee = serializers.CharField(allow_blank=True)
    category_id = serializers.IntegerField()
    category = serializers.CharField()
    account = serializers.CharField(allow_blank=True, help_text="The other side's account name.")
    amount = _money()


class CategoryTransactionSerializer(serializers.Serializer):
    date = serializers.DateField()
    payee = serializers.CharField(allow_blank=True)
    memo = serializers.CharField(allow_blank=True)
    account = serializers.CharField(allow_blank=True)
    amount = _money(help_text="Signed so positive is spending (expense) or income received (income).")


class NetWorthPointSerializer(serializers.Serializer):
    key = MonthKeyField()
    label = serializers.CharField()
    net = _money()
    assets = _money()
    liabilities = _money()


class NetWorthBandSerializer(serializers.Serializer):
    bucket = serializers.CharField(help_text="“Bank accounts & credit cards”, or an account group.")
    type = serializers.ChoiceField(choices=["cash", "asset", "liability"])
    values = serializers.ListField(child=_money(), help_text="Contribution to net worth, aligned with `series`.")


class NetWorthTotalsSerializer(serializers.Serializer):
    net = _money()
    assets = _money()
    liabilities = _money()


class BalanceRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    type = serializers.ChoiceField(choices=["asset", "liability", "equity"])
    balance = _money(help_text="At month end.")
    changes = serializers.DictField(child=_money(), help_text="Baseline id → change over that baseline.")


class NetWorthSectionSerializer(serializers.Serializer):
    series = NetWorthPointSerializer(many=True, help_text="Month ends, back to the longest baseline.")
    stack = NetWorthBandSerializer(many=True)
    now = NetWorthTotalsSerializer()
    prev = NetWorthTotalsSerializer(help_text="At the end of last month.")
    by_account = BalanceRowSerializer(many=True)


class GoalSpendingSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    amount = _money()
    months_funded = serializers.IntegerField()


class InsightSerializer(serializers.Serializer):
    kind = serializers.CharField()
    severity = serializers.ChoiceField(choices=["good", "info", "warn", "bad"])
    step = serializers.IntegerField(help_text="The walkthrough step that shows it (1 = the data check).")
    title = serializers.CharField()
    body = serializers.CharField(allow_blank=True)
    action = serializers.SerializerMethodField(help_text="Where to act on it: `inbox`, or null.")
    metric = _optional_money()
    delta = _optional_money()
    lines = serializers.ListField(child=serializers.CharField(), help_text="One sentence per account it covers.")

    @extend_schema_field(serializers.ChoiceField(choices=["inbox"], allow_null=True))
    def get_action(self, insight):
        # Every insight that links anywhere links to the Inbox (`build_review` sets it).
        return "inbox" if insight.url else None


class ReviewSerializer(serializers.Serializer):
    month = MonthKeyField()
    month_label = serializers.CharField()
    prev_label = serializers.CharField()
    is_current_month = serializers.BooleanField()
    health = HealthSerializer()
    current = CurrentFiguresSerializer()
    baselines = serializers.DictField(child=BaselineSerializer(), help_text="Baseline id → its slice.")
    baseline_order = serializers.ListField(child=serializers.ChoiceField(choices=BASELINE_IDS))
    default_baseline = serializers.ChoiceField(choices=BASELINE_IDS, allow_null=True)
    budget = BudgetBreakdownSerializer()
    biggest = BiggestTransactionSerializer(many=True)
    cat_txns = serializers.DictField(
        child=serializers.ListField(child=CategoryTransactionSerializer()),
        help_text="Category (account) id → this month's transactions.",
    )
    net_worth = NetWorthSectionSerializer()
    goal_spending = GoalSpendingSerializer(many=True)
    notes = serializers.ListField(child=serializers.CharField())
    insights = InsightSerializer(many=True)


# --- Progress ---------------------------------------------------------------------


class ReviewStateSerializer(serializers.Serializer):
    step = serializers.IntegerField(help_text="The walkthrough step the user is on.")
    steps_seen = serializers.ListField(child=serializers.IntegerField())
    baseline = serializers.CharField(help_text="The baseline last chosen.")
    is_finished = serializers.BooleanField(help_text="Completed or dismissed: the client opens the dashboard.")
    completed_at = serializers.DateTimeField(allow_null=True)
    dismissed_at = serializers.DateTimeField(allow_null=True)


class MonthlyReviewSerializer(serializers.Serializer):
    month = MonthField()
    has_activity = serializers.BooleanField(help_text="Any ledger activity by this month; false: nothing to review.")
    review = ReviewSerializer(allow_null=True, help_text="Null without activity.")
    state = ReviewStateSerializer()


class MonthRequestSerializer(serializers.Serializer):
    month = MonthField(help_text="The reviewed month, as YYYY-MM.")


class StepRequestSerializer(MonthRequestSerializer):
    step = serializers.IntegerField(required=False, min_value=0, max_value=32767)
    baseline = serializers.ChoiceField(
        choices=BASELINE_IDS, required=False, allow_null=True, help_text="Null (or absent) leaves it as it is."
    )


class StepResponseSerializer(serializers.Serializer):
    state = ReviewStateSerializer()


class FinishResponseSerializer(serializers.Serializer):
    already_finished = serializers.BooleanField(help_text="It was completed or dismissed before: nothing changed.")
    state = ReviewStateSerializer()


class CompleteResponseSerializer(FinishResponseSerializer):
    current = CurrentFiguresSerializer(
        allow_null=True, help_text="The month's headline figures; null if already finished."
    )
