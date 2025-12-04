from django.db import models
from django.urls import reverse

from apps.teams.models import BaseTeamModel


class Account(BaseTeamModel):
    """
    Account model for tracking financial accounts.
    Can be assets, liabilities, income, expenses, or equity.
    """

    ACCOUNT_TYPE_CHOICES = [
        ("asset", "Asset"),
        ("liability", "Liability"),
        ("income", "Income"),
        ("expense", "Expense"),
        ("equity", "Equity"),
    ]

    name = models.CharField(max_length=200)
    account_number = models.IntegerField(help_text="Account number (1000s for assets, 2000s for liabilities, etc.)")
    account_type = models.CharField(max_length=30, choices=ACCOUNT_TYPE_CHOICES)
    in_bank_feed = models.BooleanField(default=False, help_text="Display in transactions tab")
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        ordering = ["account_number"]
        unique_together = ["team", "account_number"]

    def __str__(self):
        return f"{self.account_number} - {self.name}"

    def get_absolute_url(self):
        return reverse("budgeting:account-detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})


class Payee(BaseTeamModel):
    """
    Payee model for tracking who transactions are with.
    """

    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Transaction(BaseTeamModel):
    """
    Transaction model for tracking income and expenses.
    """

    date = models.DateField()
    payee = models.ForeignKey(Payee, on_delete=models.PROTECT, related_name="transactions")
    amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Can be positive or negative")
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="transactions", help_text="The account being debited/credited"
    )
    category = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="categorized_transactions",
        help_text="The category/account for classification",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.date} - {self.payee.name} - ${self.amount}"


class Budget(BaseTeamModel):
    """
    Budget model for monthly budget planning.
    """

    month = models.DateField(help_text="First day of the month")
    category = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        limit_choices_to={"account_type__in": ["income", "expense"]},
        help_text="Income or expense category",
    )
    budgeted_amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Planned budget amount")
    actual_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, help_text="Actual amount spent (calculated)"
    )
    available_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, help_text="Remaining budget (calculated)"
    )
    category_name = models.CharField(max_length=200, blank=True, help_text="Cached category name")

    class Meta:
        unique_together = ["team", "month", "category"]
        ordering = ["-month", "category__account_number"]

    def __str__(self):
        return f"{self.month.strftime('%Y-%m')} - {self.category.name} - ${self.budgeted_amount}"


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
