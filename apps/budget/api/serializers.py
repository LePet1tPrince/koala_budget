"""
Request and response shapes of the budget API (`/a/{team}/{book}/budget/api/...`).

Money is a decimal string ("1234.50"), months are `YYYY-MM`, categories are named
by id. Responses are the structure `apps.budget.figures.month_figures` and
`apps.budget.grid.grid_data` build -- never DOM keys or rendered text.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.utils.translation import gettext_lazy as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.api.base import MonthField
from apps.budget.figures import AUTOFILL_ACTIONS
from apps.budget.forms import MAX_BUDGET_AMOUNT, parse_budget_amount
from apps.budget.grid import GRID_ACTUAL_MODES, GRID_MAX_CHANGES, GRID_MAX_MONTHS
from apps.budget.unassigned import STATE_NEGATIVE, STATE_POSITIVE, STATE_ZERO

SECTION_KEYS = ["income", "expense"]
COVER_FROM_UNASSIGNED = "unassigned"
COVER_FROM_GOAL = "goal"
COVER_SOURCES = [COVER_FROM_UNASSIGNED, COVER_FROM_GOAL]


def money(**kwargs):
    return serializers.DecimalField(max_digits=15, decimal_places=2, **kwargs)


@extend_schema_field(OpenApiTypes.STR)
class BudgetAmountField(serializers.CharField):
    """
    A typed budget amount. Accepts what people paste from a spreadsheet ("$1,234.56",
    "(45.50)" for a negative) and simple arithmetic ("120+35"), via the same
    `parse_budget_amount` the no-JS form uses; blank means zero (clears the row).
    """

    default_error_messages = {"invalid": _("Enter a number, for example 250 or 1,250.50.")}

    def __init__(self, **kwargs):
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("trim_whitespace", True)
        super().__init__(**kwargs)

    def run_validation(self, data=serializers.empty):
        # CharField answers a blank value itself, before `to_internal_value`.
        if self.allow_blank and isinstance(data, str) and not data.strip():
            return parse_budget_amount("")
        return super().run_validation(data)

    def to_internal_value(self, data):
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            data = str(data)
        amount = parse_budget_amount(super().to_internal_value(data))
        if amount is None:
            self.fail("invalid")
        return amount


# --- Month figures ----------------------------------------------------------------


class FigureTotalsSerializer(serializers.Serializer):
    budgeted = money()
    actual = money(help_text="Activity this month: spent (expense) or received (income).")
    available = money(
        help_text="Budget − actual + last month's available (expense); for income, actual − budget + rollover, "
        "negative while budgeted income has not arrived."
    )


class MeterSerializer(serializers.Serializer):
    pct = serializers.FloatField(allow_null=True, help_text="Spent (received) of what there was; null with nothing.")
    width = serializers.IntegerField(help_text="Bar fill, 0–100.")
    over = serializers.BooleanField(help_text="Overspent (expense rows only).")
    label = serializers.CharField(help_text="“40%”, or “—” with nothing to measure against.")


class BudgetRowSerializer(serializers.Serializer):
    category_id = serializers.IntegerField(source="category.pk")
    name = serializers.CharField(source="category.name")
    account_group_id = serializers.IntegerField(source="category.account_group_id")
    account_group_name = serializers.CharField(source="category.account_group.name")
    hidden = serializers.BooleanField(source="category.hidden_from_budget")
    budgeted = money()
    actual = money()
    available = money()
    meter = MeterSerializer()


class BudgetGroupSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="The account group's name, or “Hidden” for the hidden group.")
    hidden = serializers.BooleanField(help_text="The collapsed group of hidden categories, last in its section.")
    subtotals = FigureTotalsSerializer()
    overspent = serializers.IntegerField(help_text="Rows with a negative available.")
    rows = BudgetRowSerializer(many=True)


class SectionSummarySerializer(serializers.Serializer):
    leftover_last_month = money()
    assigned_this_month = money()
    activity_this_month = money()
    available = money()


class AutofillActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=AUTOFILL_ACTIONS)
    label = serializers.CharField()


class BudgetSectionSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=SECTION_KEYS, help_text="The section's category type; one tab each.")
    label = serializers.CharField()
    income = serializers.BooleanField()
    totals = FigureTotalsSerializer()
    overspent = serializers.IntegerField(help_text="Overspent categories (expense section; 0 for income).")
    hidden_count = serializers.IntegerField(help_text="Categories in the section's hidden group.")
    summary = SectionSummarySerializer(help_text="The sidebar summary for this tab.")
    autofill = AutofillActionSerializer(many=True, help_text="The tab's Auto-Assign actions.")
    groups = BudgetGroupSerializer(many=True)


class ExpectedIncomeSerializer(serializers.Serializer):
    label = serializers.CharField()
    amount = money()


class UnassignedSerializer(serializers.Serializer):
    """Every term of the Unassigned sum for one month (`apps.budget.unassigned.Unassigned`)."""

    month = MonthField()
    amount = money(help_text="Net worth − envelopes − goals.")
    state = serializers.ChoiceField(choices=[STATE_POSITIVE, STATE_ZERO, STATE_NEGATIVE])
    label = serializers.CharField(help_text="“Unassigned”, or “Over-assigned” when negative.")
    net_worth = money()
    envelopes = money(help_text="Unspent expense budget, rollover included (overspent envelopes count as 0).")
    goals = money(help_text="Left in goals (overspent goals count as 0).")
    overspent = money(help_text="Overspending still showing on expense envelopes.")
    goals_overspent = money()
    expected_income = ExpectedIncomeSerializer(
        allow_null=True, help_text="Budgeted income not yet received; null unless the book budgets income ahead."
    )

    def to_representation(self, instance):
        from apps.budget.unassigned import EXPECTED_INCOME_LABEL

        return super().to_representation(
            {
                "month": instance.month,
                "amount": instance.amount,
                "state": instance.state,
                "label": str(instance.label),
                "net_worth": instance.net_worth,
                "envelopes": instance.envelopes,
                "goals": instance.goals,
                "overspent": instance.overspent,
                "goals_overspent": instance.goals_overspent,
                "expected_income": {"label": str(EXPECTED_INCOME_LABEL), "amount": instance.income_due}
                if instance.expects_income
                else None,
            }
        )


class CoverGoalSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    left = money(help_text="What the goal has left this month (may be negative).")


class BudgetMonthSerializer(serializers.Serializer):
    month = MonthField()
    has_categories = serializers.BooleanField(help_text="False until the book has a budgeted category.")
    sections = BudgetSectionSerializer(many=True, help_text="One per tab, in tab order.")
    totals = FigureTotalsSerializer(source="grand_totals", help_text="Across every section.")
    unassigned = UnassignedSerializer()
    cover_goals = CoverGoalSerializer(many=True, help_text="Open goals an overspent category can be covered from.")


# --- Writes -----------------------------------------------------------------------


class BudgetAmountRequestSerializer(serializers.Serializer):
    category_id = serializers.IntegerField()
    month = MonthField()
    amount = BudgetAmountField()


class BudgetAmountResponseSerializer(serializers.Serializer):
    category_id = serializers.IntegerField()
    month = MonthField()
    amount = money(help_text="The amount saved, normalized.")
    figures = BudgetMonthSerializer(help_text="The month recomputed after the save.")


class CoverRequestSerializer(serializers.Serializer):
    category_id = serializers.IntegerField(help_text="An expense category.")
    month = MonthField()
    amount = BudgetAmountField(allow_blank=False)
    source = serializers.ChoiceField(
        choices=COVER_SOURCES,
        required=False,
        help_text="Where the money comes from; defaults to a goal when `goal_id` is given, else Unassigned.",
    )
    goal_id = serializers.IntegerField(required=False, allow_null=True, help_text="With `source` “goal”.")

    def validate_amount(self, amount):
        if amount <= 0 or amount > MAX_BUDGET_AMOUNT:
            raise serializers.ValidationError(_("Enter an amount greater than zero."))
        return amount

    def validate(self, attrs):
        attrs.setdefault("source", COVER_FROM_GOAL if attrs.get("goal_id") else COVER_FROM_UNASSIGNED)
        if attrs["source"] == COVER_FROM_GOAL and not attrs.get("goal_id"):
            raise serializers.ValidationError({"goal_id": [_("Pick a goal.")]})
        return attrs


class CoverResponseSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=COVER_SOURCES)
    category_id = serializers.IntegerField()
    month = MonthField()
    amount = money(help_text="The category's budget for the month after covering.")
    goal_id = serializers.IntegerField(allow_null=True)
    goal_left = money(allow_null=True, help_text="What the goal has left after covering; null from Unassigned.")
    figures = BudgetMonthSerializer()


class VisibilityRequestSerializer(serializers.Serializer):
    hidden = serializers.BooleanField(help_text="True hides the category from the budget page; false brings it back.")
    month = MonthField(help_text="The month to answer with.")


class VisibilityResponseSerializer(serializers.Serializer):
    category_id = serializers.IntegerField()
    hidden = serializers.BooleanField()
    figures = BudgetMonthSerializer(help_text="The month with the category in its new group.")


class AutofillRequestSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=AUTOFILL_ACTIONS)
    month = MonthField()
    section = serializers.ChoiceField(
        choices=SECTION_KEYS, required=False, help_text="The tab whose categories it reaches; omitted, every tab."
    )
    category_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_null=True,
        help_text="Only these categories (an empty list reaches none); omitted or null, every category of the tab. "
        "Hidden categories are never reached.",
    )


class AutofillResponseSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=AUTOFILL_ACTIONS)
    changed = serializers.IntegerField(help_text="Categories whose budget was set.")
    figures = BudgetMonthSerializer()


# --- Grid -------------------------------------------------------------------------


class GridQuerySerializer(serializers.Serializer):
    start = MonthField(required=False, help_text="The first month; defaults to January of the current year.")
    months = serializers.IntegerField(required=False, default=12, min_value=1, max_value=GRID_MAX_MONTHS)


class GridMonthSerializer(serializers.Serializer):
    month = MonthField(source="*")
    label = serializers.SerializerMethodField()

    def get_label(self, month) -> str:
        return month.strftime("%b %Y")


class GridActualModeSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=GRID_ACTUAL_MODES)
    label = serializers.CharField()
    detail = serializers.CharField(help_text="The window it averages, e.g. “Monthly average, Jan–Aug 2026”.")


@extend_schema_field({"type": "object", "additionalProperties": {"type": "string", "format": "decimal"}})
class MonthAmountsField(serializers.Field):
    """`{"YYYY-MM": "123.45"}`: the months with a budget. A month without one is blank."""

    def to_representation(self, value):
        return {month.strftime("%Y-%m"): f"{amount:.2f}" for month, amount in sorted(value.items())}


@extend_schema_field(
    {"type": "object", "additionalProperties": {"type": "string", "format": "decimal", "nullable": True}}
)
class ModeActualsField(serializers.Field):
    """`{mode: "123.45" | null}` for each of `actual_modes`; null when the mode has no complete month yet."""

    def to_representation(self, value):
        return {mode: (f"{amount:.2f}" if amount is not None else None) for mode, amount in value.items()}


class GridRowSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="The category's id.")
    name = serializers.CharField()
    amounts = MonthAmountsField()
    actuals = ModeActualsField()


class GridGroupSerializer(serializers.Serializer):
    name = serializers.CharField()
    type = serializers.ChoiceField(choices=SECTION_KEYS)
    rows = GridRowSerializer(many=True)


class GridSerializer(serializers.Serializer):
    start = MonthField()
    num_months = serializers.IntegerField()
    prev_start = MonthField()
    next_start = MonthField()
    months = GridMonthSerializer(many=True)
    actual_modes = GridActualModeSerializer(many=True)
    groups = GridGroupSerializer(many=True, help_text="Income groups first; hidden categories are left out.")


class CentsDecimalField(serializers.DecimalField):
    """A decimal amount rounded half-up to cents, rather than refused for its extra places."""

    def validate_precision(self, value):
        return super().validate_precision(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class GridChangeSerializer(serializers.Serializer):
    category_id = serializers.IntegerField()
    month = MonthField()
    amount = CentsDecimalField(
        max_digits=15, decimal_places=2, min_value=-MAX_BUDGET_AMOUNT, max_value=MAX_BUDGET_AMOUNT
    )


class GridSaveRequestSerializer(serializers.Serializer):
    changes = GridChangeSerializer(many=True, max_length=GRID_MAX_CHANGES, allow_empty=True)


class GridSaveResponseSerializer(serializers.Serializer):
    saved = serializers.IntegerField(help_text="Distinct cells written (a cell named twice counts once).")
