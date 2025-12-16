from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils.translation import gettext

from apps.teams.models import BaseTeamModel, Team


# Account type constants - shared across models
ACCOUNT_TYPE_ASSET = "asset"
ACCOUNT_TYPE_LIABILITY = "liability"
ACCOUNT_TYPE_INCOME = "income"
ACCOUNT_TYPE_EXPENSE = "expense"
ACCOUNT_TYPE_EQUITY = "equity"

ACCOUNT_TYPE_CHOICES = [
    (ACCOUNT_TYPE_ASSET, "Asset"),
    (ACCOUNT_TYPE_LIABILITY, "Liability"),
    (ACCOUNT_TYPE_INCOME, "Income"),
    (ACCOUNT_TYPE_EXPENSE, "Expense"),
    (ACCOUNT_TYPE_EQUITY, "Equity"),
]


class AccountGroup(BaseTeamModel):
    """
    Account Group model for tracking account groups.
    """

    account_group_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = ["team", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("transactions:accountgroup_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})


class Account(BaseTeamModel):
    """
    Account model for tracking financial accounts.
    Can be assets, liabilities, income, expenses, or equity.
    """
    account_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200)
    account_number = models.IntegerField(help_text="Account number (1000s for assets, 2000s for liabilities, etc.)")
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    account_group = models.ForeignKey(
        AccountGroup,
        on_delete=models.PROTECT,
        related_name="accounts",
        help_text="Account group classification",
        null=True,
        blank=True,
    )
    has_feed = models.BooleanField(default=False, help_text="Whether this account has a bank feed")

    class Meta:
        ordering = ["account_number"]
        unique_together = ["team", "account_number"]

    def __str__(self):
        return f"{self.account_number} - {self.name}"

    def get_absolute_url(self):
        return reverse("transactions:account_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})

    # @property
    # def account_balance(self):
    #     """Calculate account balance from transactions."""
    #     # Sum transactions where this account is the account field
    #     account_total = (
    #         self.transactions.aggregate(total=Sum("amount"))["total"] or 0
    #     )
    #     # Sum transactions where this account is the category field
    #     category_total = (
    #         self.categorized_transactions.aggregate(total=Sum("amount"))["total"] or 0
    #     )
    #     return account_total + category_total


class Payee(BaseTeamModel):
    """
    Payee model for tracking who transactions are with.
    """

    payee_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]
        unique_together = ["team", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("transactions:payee_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})
