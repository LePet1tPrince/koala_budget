from decimal import Decimal

from django.db import models
from django.db.models import F, Q, Sum
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Account, AccountGroup, ACCOUNT_TYPE_EQUITY
from apps.teams.models import BaseTeamModel


class BudgetQuerySet(models.QuerySet):
    pass


class Budget(BaseTeamModel):
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

    budget_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text="Planned budget amount"
    )

    objects = BudgetQuerySet.as_manager()

    class Meta:
        unique_together = ["team", "month", "category"]
        ordering = ["-month", "category__account_number"]

    def __str__(self):
        return f"{self.month.strftime('%Y-%m')} - {self.category.name} - ${self.budget_amount}"


class GoalQuerySet(models.QuerySet):
    def active(self):
        """Return only non-archived, non-complete goals."""
        return self.filter(is_archived=False, is_complete=False)

    def with_progress(self, month=None):
        """
        Annotate goals with their progress information for a given month.
        If month is None, uses current month.
        """
        from django.utils import timezone

        if month is None:
            month = timezone.now().date().replace(day=1)

        return self.annotate(
            # Total saved up to previous month
            saved_previous=Sum(
                "allocations__amount",
                filter=Q(allocations__month__lt=month),
                default=Decimal("0")
            ),
            # Saved this month
            saved_this_month=Sum(
                "allocations__amount",
                filter=Q(allocations__month=month),
                default=Decimal("0")
            ),
            # Total saved (all time)
            total_saved=Sum(
                "allocations__amount",
                default=Decimal("0")
            ),
            # Calculate remaining amount needed
            remaining=F("target_amount") - Sum(
                "allocations__amount",
                default=Decimal("0")
            )
        )


class Goal(BaseTeamModel):
    """
    Goal model for savings goals.
    Each goal is backed by an equity account in the chart of accounts.
    """

    name = models.CharField(max_length=200, verbose_name=_("Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))

    target_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        verbose_name=_("Target amount"),
        help_text=_("Target savings amount")
    )

    target_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Target date"),
        help_text=_("Target date to reach the goal")
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

    is_complete = models.BooleanField(
        default=False,
        verbose_name=_("Completed"),
        help_text=_("Whether this goal has been completed")
    )

    is_archived = models.BooleanField(
        default=False,
        verbose_name=_("Archived"),
        help_text=_("Whether this goal is archived")
    )

    order = models.IntegerField(
        default=0,
        verbose_name=_("Order"),
        help_text=_("Display order for goals")
    )

    objects = GoalQuerySet.as_manager()

    class Meta:
        ordering = ["order", "target_date", "name"]
        unique_together = ["team", "name"]
        # Use unique related_name to avoid conflict with deprecated apps.goals.Goal
        default_related_name = "budget_goals"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("budget:goal_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})

    def save(self, *args, **kwargs):
        """Override save to automatically create backing account for new goals."""
        is_new = self.pk is None

        if is_new and not self.account_id:
            # Get or create the Goals account group
            goal_group, _ = AccountGroup.objects.get_or_create(
                team=self.team,
                account_type=ACCOUNT_TYPE_EQUITY,
                defaults={
                    "name": "Goals",
                    "description": "Savings goals"
                }
            )

            # Find the next available account number in the 3000s range (equity)
            last_goal_account = Account.objects.filter(
                team=self.team,
                account_number__startswith="3"
            ).order_by("-account_number").first()

            if last_goal_account:
                try:
                    next_number = int(last_goal_account.account_number) + 1
                except ValueError:
                    next_number = 3000
            else:
                next_number = 3000

            # Create the backing account
            self.account = Account.objects.create(
                team=self.team,
                name=f"Goal: {self.name}",
                account_number=str(next_number),
                account_group=goal_group
            )

        super().save(*args, **kwargs)

    @property
    def progress_percentage(self):
        """Calculate progress as a percentage."""
        if hasattr(self, "total_saved"):
            saved = self.total_saved or Decimal("0")
        else:
            saved = self.allocations.aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0")

        if self.target_amount > 0:
            return min(float(saved / self.target_amount * 100), 100)
        return 0


class GoalAllocation(BaseTeamModel):
    """
    Monthly allocation towards a goal.
    This represents how much is being saved toward the goal each month.
    """

    goal = models.ForeignKey(
        Goal,
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name=_("Goal")
    )

    month = models.DateField(
        verbose_name=_("Month"),
        help_text=_("Month of this allocation (first day of month)")
    )

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name=_("Amount"),
        help_text=_("Amount allocated this month")
    )

    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    class Meta:
        unique_together = ["team", "goal", "month"]
        ordering = ["-month"]
        default_related_name = "budget_goal_allocations"

    def __str__(self):
        return f"{self.goal.name} - {self.month.strftime('%Y-%m')} - ${self.amount}"

    def save(self, *args, **kwargs):
        # Ensure month is always first day of month
        self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)
