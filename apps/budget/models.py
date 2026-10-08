from decimal import Decimal

from django.db import models, transaction
from django.db.models import DecimalField, F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import ACCOUNT_TYPE_EQUITY, Account, AccountGroup
from apps.books.models import BaseBookModel

ZERO = Decimal("0")


class BudgetQuerySet(models.QuerySet):
    pass


class Budget(BaseBookModel):
    """
    Budget model for monthly budget planning.
    Automatically generates entries for income/expense accounts each month.
    """

    month = models.DateField(help_text="First day of the month")

    category = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="budgets",
        help_text="Income or expense category (account)",
    )

    budget_amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Planned budget amount")

    objects = BudgetQuerySet.as_manager()

    class Meta:
        unique_together = ["book", "month", "category"]
        ordering = ["-month", "category__name"]

    def __str__(self):
        return f"{self.month.strftime('%Y-%m')} - {self.category.name} - ${self.budget_amount}"


GOALS_GROUP_NAME = "Goals"

STATE_SAVING = "saving"
STATE_FUNDED = "funded"
STATE_SPENDING = "spending"
STATE_CLOSED = "closed"

STATE_LABELS = {
    STATE_SAVING: _("Saving"),
    STATE_FUNDED: _("Funded"),
    STATE_SPENDING: _("Spending"),
    STATE_CLOSED: _("Closed"),
}


def goals_group(book):
    """The non-system equity group goal accounts live in, created if missing.

    Never another equity group: on template and generated charts the lowest-id
    equity group is the system "Equity Adjustments" one.
    """
    group = AccountGroup.objects.filter(
        book=book, account_type=ACCOUNT_TYPE_EQUITY, name=GOALS_GROUP_NAME, is_system=False
    ).first()
    if group is not None:
        return group
    # AccountGroup names are unique per book regardless of type, so a "Goals"
    # group of another type (or a system one) pushes ours to another name.
    name = GOALS_GROUP_NAME
    if AccountGroup.objects.filter(book=book, name=name).exists():
        name = "Savings Goals"
        existing = AccountGroup.objects.filter(
            book=book, account_type=ACCOUNT_TYPE_EQUITY, name=name, is_system=False
        ).first()
        if existing is not None:
            return existing
    return AccountGroup.objects.create(
        book=book, account_type=ACCOUNT_TYPE_EQUITY, name=name, description="Savings goals"
    )


def month_after(month):
    """First day of the month after the one containing `month`."""
    month = month.replace(day=1)
    return month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)


def goal_spent_subquery(start=None, end=None):
    """
    What a goal has spent, as a scalar subquery on `Goal`.

    Σ (dr − cr) of counted lines on the goal's own account (refunds reduce it),
    plus what its linked accounts sent out under the "count it as spent" outflow
    setting (`apps.budget.linked`). Entries dated from `start` (inclusive) to `end`
    (exclusive). Void entries and entries behind an archived bank transaction don't
    count, the same as everywhere else.
    """
    from apps.budget.linked import linked_spent_subquery
    from apps.journal.models import JournalLine, counted_entries

    lines = JournalLine.objects.filter(counted_entries("journal_entry__"), account=OuterRef("account"))
    if start is not None:
        lines = lines.filter(journal_entry__entry_date__gte=start)
    if end is not None:
        lines = lines.filter(journal_entry__entry_date__lt=end)
    total = lines.values("account").annotate(total=Sum(F("dr_amount") - F("cr_amount"))).values("total")
    own = Coalesce(Subquery(total, output_field=DecimalField(max_digits=15, decimal_places=2)), ZERO)
    return own + linked_spent_subquery(start, end)


def goal_assigned_subquery(start=None, end=None):
    """Σ manual allocations (`GoalAllocation`) for months from `start` to `end` (exclusive)."""
    filters = {}
    if start is not None:
        filters["month__gte"] = start.replace(day=1)
    if end is not None:
        filters["month__lt"] = end
    total = (
        GoalAllocation.objects.filter(goal=OuterRef("pk"), **filters)
        .values("goal")
        .annotate(total=Sum("amount"))
        .values("total")
    )
    return Coalesce(Subquery(total, output_field=DecimalField(max_digits=15, decimal_places=2)), ZERO)


def goal_allocated_subquery(start=None, end=None, plans_end=None):
    """
    What a goal has been given, as a scalar subquery on `Goal`: manual allocations,
    everything its linked accounts brought in (starting balances and linked
    flows, `apps.budget.linked`) and what its plans gave it in months no linked
    account covers (`apps.budget.plans`), dated from `start` (inclusive) to `end`
    (exclusive). Months are first-of-month dates, so a month range is
    `(month, month_after(month))`.

    Plans never count past a month that hasn't been reached: they count up to
    `plans_end`, which defaults to `end` (or the end of the current month when
    `end` is open).
    """
    from django.db.models import ExpressionWrapper
    from django.utils import timezone

    from apps.budget.linked import linked_allocated_subquery
    from apps.budget.plans import direct_planned_subquery

    if plans_end is None:
        plans_end = end if end is not None else month_after(timezone.localdate())
    given = goal_assigned_subquery(start, end) + linked_allocated_subquery(start, end)
    planned = direct_planned_subquery(plans_end)
    if start is not None:
        planned = planned - direct_planned_subquery(start)
    return ExpressionWrapper(given + planned, output_field=DecimalField(max_digits=15, decimal_places=2))


class GoalQuerySet(models.QuerySet):
    def active(self):
        """Open goals: not archived and not closed."""
        return self.filter(is_archived=False, closed_at__isnull=True)

    def closed(self):
        return self.filter(closed_at__isnull=False)

    def with_progress(self, month=None):
        """
        Annotate each goal with its three numbers as of the end of `month`
        (default: the current month). See docs/goals-envelopes-plan.md §3.

        - allocated: Σ allocations, all months (withdrawals are negative allocations),
          plus what linked accounts brought in (docs/goal-linked-accounts-plan.md)
        - spent: Σ (dr − cr) of counted lines on the goal's account through month end,
          plus linked spending
        - left: allocated − spent — the goal's claim on your money

        `total_saved` is an alias of `allocated`, kept while templates move over.
        """
        from django.utils import timezone

        if month is None:
            month = timezone.now().date()
        month = month.replace(day=1)
        end = month_after(month)

        return self.annotate(
            saved_previous=goal_allocated_subquery(end=month),
            saved_this_month=goal_allocated_subquery(month, end),
            allocated=goal_allocated_subquery(plans_end=end),
            spent=goal_spent_subquery(end=end),
            spent_this_month=goal_spent_subquery(start=month, end=end),
        ).annotate(
            total_saved=F("allocated"),
            left=F("allocated") - F("spent"),
            remaining=F("target_amount") - F("allocated"),
        )


class Goal(BaseBookModel):
    """
    A savings goal: a budget envelope that never resets.

    Saving is an allocation of unassigned money (`GoalAllocation`); spending is a
    real transaction categorized to the goal's backing equity account. Every goal
    has that account; not every equity account is a goal.
    """

    name = models.CharField(max_length=200, verbose_name=_("Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))

    # 0 = no target: an open-ended goal (retirement, an RESP) planned by its
    # monthly contribution alone. See `has_target`.
    target_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        verbose_name=_("Target amount"),
        help_text=_("Target savings amount (0 for an open-ended goal)"),
    )

    target_date = models.DateField(
        null=True, blank=True, verbose_name=_("Target date"), help_text=_("Target date to reach the goal")
    )

    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,
        related_name="goal",
        null=True,
        blank=True,
        verbose_name=_("Account"),
        help_text=_("Associated equity account (automatically created)"),
    )

    # "Funded — stop asking for money". The goal keeps its claim either way.
    is_complete = models.BooleanField(
        default=False, verbose_name=_("Funded"), help_text=_("Stop asking for money for this goal")
    )

    closed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Closed at"), help_text=_("When the goal was closed")
    )

    is_archived = models.BooleanField(
        default=False, verbose_name=_("Archived"), help_text=_("Whether this goal is archived")
    )

    order = models.IntegerField(default=0, verbose_name=_("Order"), help_text=_("Display order for goals"))

    # What money leaving a linked account for one of your other accounts does to
    # the goal (docs/goal-linked-accounts-plan.md §3).
    OUTFLOW_WITHDRAW = "withdraw"
    OUTFLOW_SPEND = "spend"
    OUTFLOW_IGNORE = "ignore"
    OUTFLOW_CHOICES = [
        (OUTFLOW_WITHDRAW, _("Take it out of the goal")),
        (OUTFLOW_SPEND, _("Count it as spent from the goal")),
        (OUTFLOW_IGNORE, _("Leave the goal alone")),
    ]
    outflow = models.CharField(
        max_length=10,
        choices=OUTFLOW_CHOICES,
        default=OUTFLOW_WITHDRAW,
        verbose_name=_("When money moves out"),
        help_text=_("What money leaving a linked account for one of your other accounts does to the goal"),
    )

    # The plan: a target date or a monthly contribution, the other one computed.
    monthly_contribution = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Monthly contribution"),
        help_text=_("How much you plan to put towards the goal each month"),
    )

    # The plan (docs/goal-plans-plan.md). Months from `plan_from` on that have no
    # `GoalPlan` row plan the goal's current default (`monthly_contribution`);
    # earlier months plan only what their rows say. Every change to what the
    # default depends on goes through `apps.budget.plans.freeze` first.
    plan_from = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Plan from"),
        help_text=_("First month the current monthly contribution applies to (first day of month)"),
    )

    # What a linked goal does with planned money that hasn't arrived by month end.
    UNMET_RELEASE = "release"
    UNMET_CARRY = "carry"
    UNMET_PLAN_CHOICES = [
        (UNMET_RELEASE, _("Release it at the end of the month")),
        (UNMET_CARRY, _("Keep holding it until the money arrives")),
    ]
    unmet_plan = models.CharField(
        max_length=10,
        choices=UNMET_PLAN_CHOICES,
        default=UNMET_RELEASE,
        verbose_name=_("When planned money isn't moved"),
        help_text=_("What happens to money planned for this goal that hasn't reached its linked accounts by month end"),
    )

    objects = GoalQuerySet.as_manager()

    class Meta:
        ordering = ["order", "target_date", "name"]
        unique_together = ["book", "name"]
        # Use unique related_name to avoid conflict with deprecated apps.goals.Goal
        default_related_name = "budget_goals"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("budget:goal_detail", args=[*self.book.url_args, self.pk])

    def save(self, *args, **kwargs):
        """Override save to automatically create backing account for new goals."""
        if self.pk is None and self.plan_from is None:
            # A new goal plans its monthly contribution from the month it was made.
            from django.utils import timezone

            self.plan_from = timezone.localdate().replace(day=1)
        if self.pk is None and not self.account_id:
            with transaction.atomic():
                # Created inside the same transaction so a failed goal save
                # doesn't leave an orphaned account behind.
                self.account = Account.objects.create(
                    book=self.book, name=f"Goal: {self.name}", account_group=goals_group(self.book)
                )
                super().save(*args, **kwargs)
            return

        super().save(*args, **kwargs)

    def _progress(self, name):
        """An annotation from `with_progress()`, or computed on demand."""
        if hasattr(self, name):
            return getattr(self, name) or ZERO
        annotated = Goal.objects.filter(pk=self.pk).with_progress().values(name).first()
        return (annotated or {}).get(name) or ZERO

    @property
    def allocated_amount(self):
        return self._progress("allocated")

    @property
    def spent_amount(self):
        return self._progress("spent")

    @property
    def left_amount(self):
        return self._progress("left")

    @property
    def has_target(self):
        """False for an open-ended goal: one planned by a monthly contribution alone."""
        return bool(self.target_amount and self.target_amount > 0)

    @property
    def to_fund(self):
        """What the goal still asks for: nothing once funded."""
        if self.is_complete:
            return ZERO
        return max(self.target_amount - self.allocated_amount, ZERO)

    @property
    def cover_amount(self):
        """What covering a negative goal takes: how far below zero it is."""
        return max(-self.left_amount, ZERO)

    @property
    def is_closed(self):
        return self.closed_at is not None

    @property
    def is_funded(self):
        return self.is_complete or (self.target_amount > 0 and self.allocated_amount >= self.target_amount)

    @property
    def state(self):
        """Saving, Funded, Spending or Closed (docs/goals-envelopes-plan.md §4.3)."""
        if self.is_closed:
            return STATE_CLOSED
        if self.spent_amount > 0:
            return STATE_SPENDING
        if self.is_funded:
            return STATE_FUNDED
        return STATE_SAVING

    @property
    def state_label(self):
        return STATE_LABELS[self.state]

    @property
    def progress_percentage(self):
        """Funded %: allocated / target, capped at 100. Spending doesn't slide it back."""
        if self.target_amount > 0:
            return max(min(float(self.allocated_amount / self.target_amount * 100), 100), 0)
        return 0


class GoalAllocation(BaseBookModel):
    """
    Monthly allocation towards a goal.
    This represents how much is being saved toward the goal each month.
    """

    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="allocations", verbose_name=_("Goal"))

    month = models.DateField(verbose_name=_("Month"), help_text=_("Month of this allocation (first day of month)"))

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name=_("Amount"),
        help_text=_("Amount allocated this month"),
    )

    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    class Meta:
        unique_together = ["book", "goal", "month"]
        ordering = ["-month"]
        default_related_name = "budget_goal_allocations"

    def __str__(self):
        return f"{self.goal.name} - {self.month.strftime('%Y-%m')} - ${self.amount}"

    def save(self, *args, **kwargs):
        # Ensure month is always first day of month
        self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)


class GoalPlan(BaseBookModel):
    """
    What a goal plans to receive in one month (docs/goal-plans-plan.md).

    A month with no row plans the goal's default (`Goal.monthly_contribution`) if
    it falls on or after `Goal.plan_from`, and nothing otherwise. A `typed` row is
    the user changing one month on the budget page; a `default` row is
    `plans.freeze` recording what the default was before a change to it.

    What a plan does depends on the month: for a goal with no linked account
    covering it, the plan *is* the money given to the goal; for a linked month,
    the plan holds money back from Unassigned until it arrives in the account.
    """

    SOURCE_DEFAULT = "default"
    SOURCE_TYPED = "typed"
    SOURCE_CHOICES = [
        (SOURCE_DEFAULT, _("Monthly contribution")),
        (SOURCE_TYPED, _("Changed for this month")),
    ]

    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="plans", verbose_name=_("Goal"))
    month = models.DateField(verbose_name=_("Month"), help_text=_("Month of this plan (first day of month)"))
    amount = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name=_("Amount"), help_text=_("Amount planned for the month")
    )
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_TYPED, verbose_name=_("Source"))

    class Meta:
        unique_together = ["book", "goal", "month"]
        ordering = ["goal", "month"]
        default_related_name = "budget_goal_plans"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gte=0), name="goal_plan_amount_not_negative"),
        ]

    def __str__(self):
        return f"{self.goal.name} - {self.month.strftime('%Y-%m')} - plan ${self.amount}"

    def save(self, *args, **kwargs):
        self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)


class GoalAccountLinkQuerySet(models.QuerySet):
    def open(self):
        return self.filter(end_date__isnull=True)

    def covering(self, day):
        """Links whose range includes `day`."""
        return self.filter(start_date__lte=day).filter(models.Q(end_date__isnull=True) | models.Q(end_date__gte=day))


class GoalAccountLink(BaseBookModel):
    """
    "The money for this goal lives in this account" (docs/goal-linked-accounts-plan.md).

    From `start_date` to `end_date` (both inclusive; open while `end_date` is null)
    money arriving in the account adds to the goal's allocation and money leaving
    it does what the goal's `outflow` says. Nothing is stored per transaction: the
    flows are derived from journal lines (`apps.budget.linked`). Unlinking sets
    `end_date`, so the months already counted keep what the account brought in.
    """

    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="account_links", verbose_name=_("Goal"))
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="goal_links", verbose_name=_("Account"))
    start_date = models.DateField(verbose_name=_("Count from"), help_text=_("First day counted"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("Until"), help_text=_("Last day counted"))
    include_starting_balance = models.BooleanField(
        default=True,
        verbose_name=_("Include the balance already there"),
        help_text=_("Count the account's balance on the day before the start date towards the goal"),
    )

    objects = GoalAccountLinkQuerySet.as_manager()

    class Meta:
        ordering = ["start_date", "pk"]
        default_related_name = "budget_goal_account_links"
        constraints = [
            # An account's whole balance belongs to one goal at a time.
            models.UniqueConstraint(
                fields=["book", "account"],
                condition=models.Q(end_date__isnull=True),
                name="goal_account_link_one_open_per_account",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True) | models.Q(end_date__gte=models.F("start_date")),
                name="goal_account_link_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.goal.name} ← {self.account.name}"

    @property
    def is_open(self):
        return self.end_date is None
