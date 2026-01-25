from django.db import models

from apps.accounts.models import Account
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

class Goal(BaseTeamModel):
