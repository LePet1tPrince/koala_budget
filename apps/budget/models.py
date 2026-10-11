from decimal import Decimal

from django.db import models, transaction
from django.db.models import DecimalField, F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import ACCOUNT_TYPE_EQUITY, ACCOUNT_TYPE_SAVING, Account, AccountGroup
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
SAVINGS_GROUP_NAME = "Saving for goals"

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


def savings_group(book):
    """The system group every goal's "Saving: X" account lives in, created if missing."""
    group = AccountGroup.objects.filter(book=book, account_type=ACCOUNT_TYPE_SAVING).order_by("pk").first()
    if group is not None:
        return group
    name = SAVINGS_GROUP_NAME
    if AccountGroup.objects.filter(book=book, name=name).exists():
        name = f"{SAVINGS_GROUP_NAME} (goals)"
    return AccountGroup.objects.create(
        book=book,
        account_type=ACCOUNT_TYPE_SAVING,
        name=name,
        description="What each goal saved, month by month",
        is_system=True,
    )


def month_after(month):
    """First day of the month after the one containing `month`."""
    month = month.replace(day=1)
    return month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)


def _fund_lines(start=None, end=None):
    """Counted lines on `OuterRef("account")` (a goal's fund), dated `start` to `end` (exclusive)."""
    from apps.journal.models import JournalLine, counted_entries

    lines = JournalLine.objects.filter(counted_entries("journal_entry__"), account=OuterRef("account"))
    if start is not None:
        lines = lines.filter(journal_entry__entry_date__gte=start)
    if end is not None:
        lines = lines.filter(journal_entry__entry_date__lt=end)
    return lines


def _sum_subquery(lines, expression):
    total = lines.values("account").annotate(total=Sum(expression)).values("total")
    return Coalesce(Subquery(total, output_field=DecimalField(max_digits=15, decimal_places=2)), ZERO)


def goal_spent_subquery(start=None, end=None):
    """
    What a goal has spent, as a scalar subquery on `Goal`.

    Σ (dr − cr) of counted lines on the goal's fund that a saving entry didn't
    write (refunds reduce it), dated from `start` (inclusive) to `end`
    (exclusive). Void entries don't count, the same as everywhere else.
    """
    lines = _fund_lines(start, end).filter(journal_entry__goal_saving__isnull=True)
    return _sum_subquery(lines, F("dr_amount") - F("cr_amount"))


def goal_assigned_subquery(start=None, end=None):
    """Σ the plan and the by-hand adjustments (`GoalAllocation`) for months from `start` to `end` (exclusive)."""
    filters = {}
    if start is not None:
        filters["month__gte"] = start.replace(day=1)
    if end is not None:
        filters["month__lt"] = end
    total = (
        GoalAllocation.objects.filter(goal=OuterRef("pk"), **filters)
        .values("goal")
        .annotate(total=Sum(F("amount") + F("adjustment")))
        .values("total")
    )
    return Coalesce(Subquery(total, output_field=DecimalField(max_digits=15, decimal_places=2)), ZERO)


def goal_allocated_subquery(start=None, end=None):
    """
    What a goal has been given, as a scalar subquery on `Goal`: Σ (cr − dr) of
    its fund's lines in saving entries (`GoalSaving`, written by
    `apps.budget.goal_ledger` from the plan and the linked accounts), dated from
    `start` (inclusive) to `end` (exclusive). A saving entry is dated the first
    of its month, so a month range is `(month, month_after(month))`.
    """
    lines = _fund_lines(start, end).filter(journal_entry__goal_saving__isnull=False)
    return _sum_subquery(lines, F("cr_amount") - F("dr_amount"))


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
            allocated=goal_allocated_subquery(),
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

    Saving is a real entry, Dr "Saving: X" / Cr the goal's fund (its backing
    equity account), posted by `apps.budget.goal_ledger` from the month's plan
    (`GoalAllocation`) and what linked accounts brought in. Spending is a debit
    to the fund. The fund's balance is what's left. Every goal has a fund; not
    every equity account is a goal.
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

    # The expense side of every saving entry: "Saving: X", in `savings_group`.
    saving_account = models.OneToOneField(
        Account,
        on_delete=models.SET_NULL,
        related_name="saving_goal",
        null=True,
        blank=True,
        verbose_name=_("Saving account"),
        help_text=_("Expense account the goal's savings are booked to (automatically created)"),
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
        """Create the fund and the saving account a new goal needs, in one transaction."""
        if self.pk is None and not (self.account_id and self.saving_account_id):
            with transaction.atomic():
                # Created inside the same transaction so a failed goal save
                # doesn't leave an orphaned account behind.
                if not self.account_id:
                    self.account = Account.objects.create(
                        book=self.book, name=f"Goal: {self.name}", account_group=goals_group(self.book)
                    )
                if not self.saving_account_id:
                    self.saving_account = create_saving_account(self)
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
    A goal's month: the plan, and money taken out or put back by hand.

    `amount` is the plan -- what you commit to saving this month. Money moved
    into a linked account counts towards it rather than on top of it, so the
    month saves the larger of the two (`apps.budget.goal_ledger`). A negative
    `amount` (written before withdrawals had their own field) reads as one.

    `adjustment` is money moved by hand outside the plan: a withdrawal, money
    released on closing, or a shortfall covered. It always counts in full.
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

    adjustment = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name=_("Adjustment"),
        help_text=_("Money taken out (negative) or put back by hand this month, outside the plan"),
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


def create_saving_account(goal):
    """A new "Saving: X" account for `goal` (not yet linked to it)."""
    return Account.objects.create(
        book=goal.book,
        name=f"Saving: {goal.name}",
        account_group=savings_group(goal.book),
        is_system=True,
    )


class GoalSaving(BaseBookModel):
    """
    The journal entry that books one month of a goal's saving
    (docs/goals-ledger-plan.md). Written only by `apps.budget.goal_ledger`.

    - KIND_SAVING, one per goal and month: Dr "Saving: X" / Cr fund for
      max(plan, moved in) − moved out, sides flipped when that is negative.
    - KIND_STARTING, one per linked account that counts the balance already
      there: Dr the system equity offset / Cr fund. Equity to equity, so it
      never reaches the income statement.

    Deleting the entry deletes this row; the ledger deletes entries, never rows.
    """

    KIND_SAVING = "saving"
    KIND_STARTING = "starting"
    KIND_CHOICES = [(KIND_SAVING, _("Saving")), (KIND_STARTING, _("Starting balance"))]

    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="savings", verbose_name=_("Goal"))
    month = models.DateField(verbose_name=_("Month"))
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_SAVING)
    link = models.ForeignKey(
        "GoalAccountLink", on_delete=models.SET_NULL, null=True, blank=True, related_name="starting_entries"
    )
    entry = models.OneToOneField("journal.JournalEntry", on_delete=models.CASCADE, related_name="goal_saving")

    class Meta:
        ordering = ["month", "pk"]
        default_related_name = "budget_goal_savings"
        constraints = [
            models.UniqueConstraint(
                fields=["goal", "month"], condition=models.Q(kind="saving"), name="goal_saving_one_per_month"
            ),
            models.UniqueConstraint(
                fields=["link"],
                condition=models.Q(kind="starting", link__isnull=False),
                name="goal_saving_one_starting_per_link",
            ),
        ]

    def __str__(self):
        return f"{self.goal.name} - {self.month.strftime('%Y-%m')} - {self.kind}"


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
