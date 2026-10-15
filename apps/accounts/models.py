from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.urls import reverse

from apps.books.models import BaseBookModel, BookScopedManager

from .querysets import AccountQuerySet

# Account type constants - shared across models
ACCOUNT_TYPE_ASSET = "asset"
ACCOUNT_TYPE_LIABILITY = "liability"
ACCOUNT_TYPE_INCOME = "income"
ACCOUNT_TYPE_EXPENSE = "expense"
ACCOUNT_TYPE_EQUITY = "goal"
# Budget buckets (Unassigned, envelopes, expected income, goal buckets): equity
# that says what money is for. Never a category, never in a real transaction;
# see `apps.budget.buckets` and `apps.accounts.guards.assert_budget_entry_rules`.
ACCOUNT_TYPE_BUDGET = "budget"

# The types a user can pick. Budget buckets are maintained by the app, so the
# budget type is only in the model field's choices, never in a form or API.
ACCOUNT_TYPE_CHOICES = [
    (ACCOUNT_TYPE_ASSET, "Asset"),
    (ACCOUNT_TYPE_LIABILITY, "Liability"),
    (ACCOUNT_TYPE_INCOME, "Income"),
    (ACCOUNT_TYPE_EXPENSE, "Expense"),
    (ACCOUNT_TYPE_EQUITY, "Goal"),
]
ALL_ACCOUNT_TYPE_CHOICES = [*ACCOUNT_TYPE_CHOICES, (ACCOUNT_TYPE_BUDGET, "Budget")]


class AccountGroup(BaseBookModel):
    """
    Account Group model for tracking account groups.
    """

    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=20, choices=ALL_ACCOUNT_TYPE_CHOICES)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False, help_text="System groups cannot be deleted by users")
    sort_order = models.PositiveIntegerField(default=0, help_text="Manual display order within the account type")

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = ["book", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("accounts:accountgroup_detail", args=[*self.book.url_args, self.pk])


class Account(BaseBookModel):
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
    is_system = models.BooleanField(default=False, help_text="System accounts cannot be deleted by users")
    sort_order = models.PositiveIntegerField(default=0, help_text="Manual display order within the account group")
    hidden_from_budget = models.BooleanField(
        default=False,
        help_text="Income/expense category tucked into the budget page's collapsed Hidden group. "
        "A display choice only: its figures still count in every total.",
    )
    is_hidden = models.BooleanField(
        default=False,
        help_text="Left out of every account picker and the Inbox. A display choice only: "
        "its transactions and balance still count everywhere.",
    )
    # Set on a budget bucket: the income, expense or goal account it budgets for.
    # Null on Unassigned. Deleting the category deletes its bucket.
    paired_account = models.OneToOneField(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="budget_bucket",
        help_text="The category this budget bucket budgets for",
    )

    # Override managers to use AccountQuerySet for optimized balance queries
    objects = AccountQuerySet.as_manager()
    for_book = BookScopedManager.from_queryset(AccountQuerySet)()

    class Meta:
        ordering = [
            "account_group__account_type",
            "account_group__sort_order",
            "account_group__name",
            "sort_order",
            "name",
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("accounts:account_detail", args=[*self.book.url_args, self.pk])

    @property
    def is_budget_bucket(self):
        return self.account_group.account_type == ACCOUNT_TYPE_BUDGET

    @property
    def balance(self):
        """Return annotated balance if available, otherwise calculate."""
        if hasattr(self, "_balance"):
            return self._balance or Decimal("0")
        # Fallback for non-annotated queries (voided/archived entries don't count)
        from apps.journal.models import counted_entries

        lines = self.journal_lines.filter(counted_entries("journal_entry__"))
        totals = lines.aggregate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
        return (totals["dr"] or Decimal("0")) - (totals["cr"] or Decimal("0"))


class Institution(BaseBookModel):
    """
    Institution model for tracking the bank or financial institution an account is held with.
    Examples: TD Bank, CIBC, Wealthsimple.
    """

    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]
        unique_together = ["book", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("accounts:institution_detail", args=[*self.book.url_args, self.pk])


class Payee(BaseBookModel):
    """
    Payee model for tracking who transactions are with.
    """

    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]
        unique_together = ["book", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("accounts:payee_detail", args=[*self.book.url_args, self.pk])
