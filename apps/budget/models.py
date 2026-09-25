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
    Σ (dr − cr) of counted lines on the goal's account, as a scalar subquery.

    Entries dated from `start` (inclusive) to `end` (exclusive). Refunds (credits)
    reduce it. Void entries and entries behind an archived bank transaction don't
    count, the same as everywhere else.
    """
    from apps.journal.models import JournalLine, counted_entries

    lines = JournalLine.objects.filter(counted_entries("journal_entry__"), account=OuterRef("account"))
    if start is not None:
        lines = lines.filter(journal_entry__entry_date__gte=start)
    if end is not None:
        lines = lines.filter(journal_entry__entry_date__lt=end)
    total = lines.values("account").annotate(total=Sum(F("dr_amount") - F("cr_amount"))).values("total")
    return Coalesce(Subquery(total, output_field=DecimalField(max_digits=15, decimal_places=2)), ZERO)


def _allocated_subquery(**filters):
    total = (
        GoalAllocation.objects.filter(goal=OuterRef("pk"), **filters)
        .values("goal")
        .annotate(total=Sum("amount"))
        .values("total")
    )
    return Coalesce(Subquery(total, output_field=DecimalField(max_digits=15, decimal_places=2)), ZERO)


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

        - allocated: Σ allocations, all months (withdrawals are negative allocations)
        - spent: Σ (dr − cr) of counted lines on the goal's account through month end
        - left: allocated − spent — the goal's claim on your money

        `total_saved` is an alias of `allocated`, kept while templates move over.
        """
        from django.utils import timezone

        if month is None:
            month = timezone.now().date()
        month = month.replace(day=1)
        end = month_after(month)

        return self.annotate(
            saved_previous=_allocated_subquery(month__lt=month),
            saved_this_month=_allocated_subquery(month=month),
            allocated=_allocated_subquery(),
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

    target_amount = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name=_("Target amount"), help_text=_("Target savings amount")
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
