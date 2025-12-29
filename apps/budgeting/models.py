from django.db import models
from django.db.models import Sum
from django.urls import reverse

from apps.teams.models import BaseTeamModel


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
    budget = models.DecimalField(max_digits=15, decimal_places=2, help_text="Planned budget amount")

    class Meta:
        unique_together = ["team", "month", "category"]
        ordering = ["-month", "category__account_number"]

    def __str__(self):
        return f"{self.month.strftime('%Y-%m')} - {self.category.name} - ${self.budget}"

    @property
    def actual(self):
        """
        Calculate actual amount from transactions.
        Sum of all transactions in the given month where:
        - transaction.account_id = category_id OR
        - transaction.category_id = category_id
        """
        from django.db.models import Q

        month_start = self.month
        # Get the first day of next month
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1)

        transactions = Transaction.objects.filter(
            team=self.team,
            date_posted__gte=month_start,
            date_posted__lt=month_end,
        ).filter(Q(account=self.category) | Q(category=self.category))

        return transactions.aggregate(total=Sum("amount"))["total"] or 0

    @property
    def available(self):
        """Calculate available amount: budget - actual."""
        return self.budget - self.actual


class Goal(BaseTeamModel):
    """
    Goal model for tracking savings goals.
    """

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Goal target amount")
    saved_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Amount saved so far")
    remaining_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, help_text="Amount remaining (calculated)"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} - ${self.saved_amount}/${self.target_amount}"
