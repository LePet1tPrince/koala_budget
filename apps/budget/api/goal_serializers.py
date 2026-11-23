"""
Request and response shapes of the goal API (`/a/{team}/{book}/budget/api/goals/...`).

Money is a decimal string, months are `YYYY-MM`, days `YYYY-MM-DD`, accounts and
goals are named by id. A goal's card is what `apps.budget.goal_figures.goal_card`
builds (the same the goals page renders); its detail adds what the goal page shows.
"""

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.api.base import MonthField
from apps.budget import goal_links
from apps.budget.forms import MAX_BUDGET_AMOUNT
from apps.budget.goal_validation import (
    clean_goal_name,
    clean_outflow,
    clean_target_amount,
    goal_plan_errors,
)
from apps.budget.models import STATE_LABELS, Goal
from apps.budget.services import PLAN_LABELS

from .serializers import BudgetAmountField, UnassignedSerializer, money

GOAL_STATES = list(STATE_LABELS)
GOAL_OUTFLOWS = [value for value, _label in Goal.OUTFLOW_CHOICES]
GOAL_PLAN_STATUSES = list(PLAN_LABELS)
GOAL_ACTIVITY_KINDS = [
    goal_links.ACTIVITY_ASSIGNED,
    goal_links.ACTIVITY_WITHDRAWN,
    goal_links.ACTIVITY_STARTING,
    goal_links.ACTIVITY_IN,
    goal_links.ACTIVITY_OUT,
    goal_links.ACTIVITY_SPENT,
]


# --- Reads ------------------------------------------------------------------------


class GoalPlanSerializer(serializers.Serializer):
    """The goal's plan for the month (`apps.budget.services.goal_plan`)."""

    rate = money(help_text="The plan's monthly amount: the monthly contribution, or the pace to the target date.")
    needed = money(help_text="What the plan asks for this month (never more than is still to fund).")
    finish = MonthField(allow_null=True, help_text="The month the plan reaches the target; null when open-ended.")
    late = serializers.BooleanField(help_text="The finish month falls after the target date.")
    rate_for_date = money(allow_null=True, help_text="With a target date: the monthly amount that reaches it by then.")
    status = serializers.ChoiceField(
        choices=GOAL_PLAN_STATUSES, allow_null=True, help_text="Against the plan's straight line; null once funded."
    )
    status_label = serializers.CharField(allow_null=True)


class GoalAccountRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class GoalCardSerializer(serializers.Serializer):
    """One goal for a month: its settings, its numbers, its bar and its plan."""

    id = serializers.IntegerField(source="goal.pk")
    name = serializers.CharField(source="goal.name")
    description = serializers.CharField(source="goal.description")
    target_amount = money(source="goal.target_amount", help_text="0 for an open-ended goal.")
    target_date = serializers.DateField(source="goal.target_date", allow_null=True)
    monthly_contribution = money(source="goal.monthly_contribution", allow_null=True)
    outflow = serializers.ChoiceField(
        choices=GOAL_OUTFLOWS,
        source="goal.outflow",
        help_text="What money leaving a linked account for another of your accounts does to the goal.",
    )
    account_id = serializers.IntegerField(
        source="goal.account_id",
        allow_null=True,
        help_text="The goal's own (equity) account: spending is categorized to it.",
    )
    has_target = serializers.BooleanField(
        help_text="False for an open-ended goal, planned by its monthly contribution."
    )
    is_complete = serializers.BooleanField(source="goal.is_complete", help_text="Marked funded: it stops asking.")
    is_archived = serializers.BooleanField(source="goal.is_archived")
    closed_at = serializers.DateTimeField(source="goal.closed_at", allow_null=True)
    state = serializers.ChoiceField(choices=GOAL_STATES)
    state_label = serializers.CharField()
    month = MonthField(help_text="The month the figures are for.")
    allocated = money(source="saved", help_text="Every allocation and what linked accounts brought in, to date.")
    spent = money()
    left = money(help_text="Allocated − spent; negative is carried (overspent).")
    this_month = money(help_text="Allocated this month (withdrawals negative).")
    spent_this_month = money()
    remaining = money(help_text="Still to fund (targeted), or still to put in this month (open-ended).")
    cover_amount = money(help_text="What covering a negative goal takes.")
    pct = serializers.FloatField(help_text="The bar, 0–100: of the target, or of this month's contribution.")
    spent_pct = serializers.FloatField(help_text="The spent part of the bar, 0–pct.")
    funded = serializers.BooleanField()
    behind_pace = serializers.BooleanField()
    needed_per_month = money(allow_null=True, help_text="The plan's rate while there is something to fund.")
    plan = GoalPlanSerializer(allow_null=True)
    linked_accounts = GoalAccountRefSerializer(many=True, help_text="The accounts feeding the goal now.")


class GoalsSummarySerializer(serializers.Serializer):
    total_target = money()
    total_saved = money()
    total_spent = money()
    total_left = money()
    goal_count = serializers.IntegerField()
    on_track_count = serializers.IntegerField(help_text="Goals on pace or funded.")


class GoalListSerializer(serializers.Serializer):
    month = MonthField()
    closed = serializers.BooleanField(help_text="The closed (and archived) goals rather than the open ones.")
    goals = GoalCardSerializer(many=True, source="cards")
    summary = GoalsSummarySerializer()
    closed_count = serializers.IntegerField(help_text="Closed and archived goals, whichever list this is.")
    unassigned = UnassignedSerializer()


class GoalLinkSerializer(serializers.Serializer):
    """A linked account: from `start_date` to `end_date` (open while null) its money counts towards the goal."""

    id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    account_name = serializers.CharField(source="account.name")
    start_date = serializers.DateField()
    end_date = serializers.DateField(allow_null=True)
    include_starting_balance = serializers.BooleanField()
    is_open = serializers.BooleanField()


class GoalSpendingLineSerializer(serializers.Serializer):
    date = serializers.DateField()
    payee = serializers.CharField()
    memo = serializers.CharField()
    counter = serializers.CharField(help_text="The other side's account names.")
    amount = money(help_text="Spent (a refund is negative).")
    entry_id = serializers.IntegerField()


class GoalDriftSerializer(serializers.Serializer):
    held = money(help_text="What the linked accounts hold.")
    left = money()
    gap = money()
    reasons = serializers.ListField(child=serializers.CharField())


class GoalDetailSerializer(GoalCardSerializer):
    """The goal page: the card plus its accounts, spending and what may be done to it."""

    progress_pct = serializers.FloatField(help_text="The goal page's bar (ignores Mark Funded).")
    open_links = GoalLinkSerializer(many=True)
    past_links = GoalLinkSerializer(many=True)
    can_edit_contributions = serializers.BooleanField(help_text="False once closed or archived.")
    delete_blocked = serializers.CharField(allow_null=True, help_text="Why the goal can't be deleted; null if it can.")
    spending = GoalSpendingLineSerializer(many=True, help_text="The latest 50 lines on the goal's account.")
    drift = GoalDriftSerializer(
        allow_null=True, help_text="How far `left` is from what the linked accounts hold, and why; null if they agree."
    )


class GoalActivityEventSerializer(serializers.Serializer):
    date = serializers.DateField(help_text="The first of the month for a manual contribution (`month_only`).")
    kind = serializers.ChoiceField(choices=GOAL_ACTIVITY_KINDS)
    account_id = serializers.IntegerField(allow_null=True, help_text="The linked account, for linked events.")
    account_name = serializers.CharField(allow_null=True)
    payee = serializers.CharField()
    memo = serializers.CharField()
    amount = money(help_text="Its effect on what's left in the goal (spending negative).")
    month_only = serializers.BooleanField()
    line_id = serializers.IntegerField(
        allow_null=True, help_text="A manual contribution's line: change or undo it at `contributions/{line_id}/`."
    )


class GoalActivitySerializer(serializers.Serializer):
    goal_id = serializers.IntegerField()
    can_edit_contributions = serializers.BooleanField()
    events = GoalActivityEventSerializer(many=True, help_text="Newest first, at most 100.")


# --- Create / update --------------------------------------------------------------


class GoalLinkRowSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(help_text="An asset account of the book.")
    start_date = serializers.DateField(required=False, allow_null=True, help_text="Count from; omitted, today.")
    include_starting_balance = serializers.BooleanField(
        required=False, default=True, help_text="Count the balance already there on the start date."
    )


def links_field(**kwargs):
    return GoalLinkRowSerializer(many=True, required=False, **kwargs)


def link_rows(book, items):
    """`LinkRow`s from validated rows, or a 400 on `links`."""
    try:
        return goal_links.link_rows(book, items)
    except goal_links.LinkError as e:
        raise serializers.ValidationError({"links": [str(e)]}) from None


class GoalWriteSerializer(serializers.Serializer):
    """
    A goal's settings and the accounts its money lives in, validated as the goal form
    validates them (`apps.budget.goal_validation`). `links` lists the accounts that
    should feed the goal: one not listed is unlinked; omitted, the links stay as
    they are. The view needs `book` (and, to update, `instance`) in the context.
    """

    FIELDS = ["name", "description", "target_amount", "target_date", "monthly_contribution", "outflow"]

    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    target_amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
        help_text="Null or 0 for an open-ended goal planned by its monthly contribution.",
    )
    target_date = serializers.DateField(required=False, allow_null=True)
    monthly_contribution = serializers.DecimalField(
        max_digits=15, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    outflow = serializers.ChoiceField(
        choices=GOAL_OUTFLOWS, required=False, allow_null=True, help_text="Omitted, the goal keeps its own."
    )
    links = links_field()

    def validate_name(self, value):
        return clean_goal_name(self.context["book"], value, exclude_pk=getattr(self.instance, "pk", None))

    def validate(self, attrs):
        instance = self.instance
        values = {}
        for field in self.FIELDS:
            if field in attrs:
                values[field] = attrs[field]
            elif instance is not None:
                values[field] = getattr(instance, field)
            elif field == "description":
                values[field] = ""
            else:
                values[field] = None
        values["target_amount"] = clean_target_amount(values["target_amount"])
        values["outflow"] = clean_outflow(values["outflow"], instance)
        errors = {}
        for field, message, _code in goal_plan_errors(
            values["target_amount"], values["monthly_contribution"], values["target_date"]
        ):
            errors.setdefault(field or "non_field_errors", []).append(message)
        if errors:
            raise serializers.ValidationError(errors)
        values["rows"] = link_rows(self.context["book"], attrs["links"]) if "links" in attrs else None
        return values


class GoalLinkPreviewRequestSerializer(serializers.Serializer):
    goal_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="The goal being edited; null for a new one."
    )
    outflow = serializers.ChoiceField(choices=GOAL_OUTFLOWS, required=False, default=Goal.OUTFLOW_WITHDRAW)
    links = links_field()
    month = MonthField(required=False, help_text="Omitted, this month.")


class GoalLinkPreviewSerializer(serializers.Serializer):
    """What saving the links and outflow would do (nothing is written)."""

    adds = money(help_text="What saving adds to the goal (negative takes it away).")
    left_before = money()
    left_after = money()
    unassigned_before = money()
    unassigned_after = money()


# --- Money in and out -------------------------------------------------------------


class GoalFundsRequestSerializer(serializers.Serializer):
    month = MonthField()
    amount = BudgetAmountField(
        required=False,
        allow_null=True,
        allow_blank=False,
        help_text="Positive. Omitted or null: assign everything available (capped at what the goal asks for), "
        "or withdraw everything left.",
    )

    def validate_amount(self, amount):
        if amount is not None and (amount <= 0 or amount > MAX_BUDGET_AMOUNT):
            raise serializers.ValidationError(_("Enter an amount greater than zero."))
        return amount


class GoalBeforeSerializer(serializers.Serializer):
    allocated = money()
    pct = serializers.FloatField()


class GoalFundsResponseSerializer(serializers.Serializer):
    amount = money(help_text="What was assigned (or withdrawn), positive.")
    month = MonthField()
    before = GoalBeforeSerializer(help_text="The goal's allocated total and bar before.")
    goal = GoalCardSerializer(help_text="The goal for the month, after.")
    completed = serializers.BooleanField(help_text="This assignment reached the target.")
    unassigned = UnassignedSerializer(help_text="Unassigned for the month, after.")


class GoalAllocateRequestSerializer(serializers.Serializer):
    month = MonthField()
    amount = BudgetAmountField(help_text="The month's allocation (replacing it); blank is 0.")

    def validate_amount(self, amount):
        if amount < 0:
            raise serializers.ValidationError(_("Allocation amount cannot be negative."))
        return amount


class GoalAllocateResponseSerializer(serializers.Serializer):
    month = MonthField()
    amount = money(help_text="The month's allocation now.")
    goal = GoalCardSerializer()
    unassigned = UnassignedSerializer()


class GoalMonthRequestSerializer(serializers.Serializer):
    month = MonthField(required=False, help_text="Omitted, this month.")


class GoalCloseRequestSerializer(GoalMonthRequestSerializer):
    cover = serializers.BooleanField(
        required=False, default=False, help_text="Top a negative goal back up to zero first (else it is refused)."
    )


class GoalCloseResponseSerializer(serializers.Serializer):
    released = money(help_text="What went back to Unassigned.")
    covered = money(help_text="What covered its overspending.")
    goal = GoalCardSerializer()
    unassigned = UnassignedSerializer()


class GoalUnlinkResponseSerializer(serializers.Serializer):
    goal_id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    account_name = serializers.CharField()
    end_date = serializers.DateField(
        allow_null=True, help_text="The last day it counted; null when a link made today was simply removed."
    )
    removed = serializers.BooleanField()


class GoalContributionRequestSerializer(serializers.Serializer):
    amount = BudgetAmountField(
        required=False, help_text="The month's contribution (negative for a withdrawal); 0 or blank undoes it."
    )
    undo = serializers.BooleanField(required=False, default=False, help_text="Remove the contribution.")

    def validate(self, attrs):
        if attrs.get("undo"):
            attrs["amount"] = clean_target_amount(None)
        elif "amount" not in attrs:
            raise serializers.ValidationError({"amount": [_("Enter an amount, like 250 or -40 for a withdrawal.")]})
        return attrs


class GoalContributionResponseSerializer(serializers.Serializer):
    goal_id = serializers.IntegerField()
    month = MonthField()
    old = money(help_text="The contribution before.")
    amount = money(help_text="The contribution now (0: undone).")
    goal = GoalCardSerializer()
