from django.db import models
from django.db.models import F, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.db.models.expressions import ExpressionWrapper
from datetime import timedelta

from apps.teams.models import BaseTeamModel
from apps.accounts.models import Account


class BudgetQuerySet(models.Queryset):
    def with_actual_amount(self):
        """Annotate queryset with actual amount."""
        return self.annotate(
            actual_amount=Coalesce(
                Sum(
                    F("journal_lines__cr_amount") -
                    F("journal_lines__dr_amount")
                ),
                Value(0),
            )
        )

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

    @property
    def available(self):
        """Calculate available amount: budget - actual."""
        actual = getattr(self, "actual_amount", 0)
        if actual is None:
            raise AttributeError(
                "Budget.actual_amount is not available. "
                "Call Budget.objects.with_actual_amount() first."
                )
        return self.budget_amount - self.actual
