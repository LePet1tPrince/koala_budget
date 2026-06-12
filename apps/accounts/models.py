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
ACCOUNT_TYPE_EQUITY = "goal"

ACCOUNT_TYPE_CHOICES = [
    (ACCOUNT_TYPE_ASSET, "Asset"),
    (ACCOUNT_TYPE_LIABILITY, "Liability"),
    (ACCOUNT_TYPE_INCOME, "Income"),
    (ACCOUNT_TYPE_EXPENSE, "Expense"),
    (ACCOUNT_TYPE_EQUITY, "Goal"),
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
    account_group = models.ForeignKey(
        AccountGroup,
        on_delete=models.PROTECT,
        related_name="accounts",
        help_text="Account group classification",
    )
    institution = models.ForeignKey(
        "Institution",
        on_delete=models.SET_NULL,
        related_name="accounts",
        null=True,
        blank=True,
        help_text="Bank or financial institution this account is held with",
    )
    has_feed = models.BooleanField(default=False, help_text="Whether this account has a bank feed")

    # Override managers to use AccountQuerySet for optimized balance queries
    objects = AccountQuerySet.as_manager()
    for_team = AccountTeamScopedManager()

    class Meta:
        ordering = ["account_group__account_type", "account_group__name", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("accounts:account_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})

    @property
    def balance(self):
        """Return annotated balance if available, otherwise calculate."""
        if hasattr(self, "_balance"):
            return self._balance or Decimal("0")
        # Fallback for non-annotated queries (voided entries don't count)
        lines = self.journal_lines.exclude(journal_entry__status="void")
        totals = lines.aggregate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
        return (totals["dr"] or Decimal("0")) - (totals["cr"] or Decimal("0"))


class Institution(BaseTeamModel):
    """
    Institution model for tracking the bank or financial institution an account is held with.
    Examples: TD Bank, CIBC, Wealthsimple.
    """

    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]
        unique_together = ["team", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("accounts:institution_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})


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
