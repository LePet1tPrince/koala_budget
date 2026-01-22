from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.urls import reverse

from apps.teams.models import BaseTeamModel

from .querysets import AccountQuerySet, AccountTeamScopedManager

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

    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = ["team", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("accounts:accountgroup_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})


class Account(BaseTeamModel):
    """
    Account model for tracking financial accounts.
    Can be assets, liabilities, income, expenses, or equity.
    Account type is determined by the associated account_group.
    """

    name = models.CharField(max_length=200)
    account_number = models.CharField(
        max_length=20,
        help_text="Account number (1000s for assets, 2000s for liabilities, etc.)")
    account_group = models.ForeignKey(
        AccountGroup,
        on_delete=models.PROTECT,
        related_name="accounts",
        help_text="Account group classification",
    )
    has_feed = models.BooleanField(default=False, help_text="Whether this account has a bank feed")

    # Override managers to use AccountQuerySet for optimized balance queries
    objects = AccountQuerySet.as_manager()
    for_team = AccountTeamScopedManager()

    class Meta:
        ordering = ["account_number"]
        unique_together = ["team", "account_number"]

    def __str__(self):
        return f"{self.account_number} - {self.name}"

    def get_absolute_url(self):
        return reverse("accounts:account_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})

    @property
    def balance(self):
        """Return annotated balance if available, otherwise calculate."""
        if hasattr(self, '_balance'):
            return self._balance or Decimal('0')
        # Fallback for non-annotated queries
        dr_total = self.journal_lines.aggregate(total=Sum("dr_amount"))["total"] or Decimal('0')
        cr_total = self.journal_lines.aggregate(total=Sum("cr_amount"))["total"] or Decimal('0')
        return dr_total - cr_total


class Payee(BaseTeamModel):
    """
    Payee model for tracking who transactions are with.
    """

    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]
        unique_together = ["team", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("accounts:payee_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})