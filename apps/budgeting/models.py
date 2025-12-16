from django.db import models
from django.db.models import Sum
from django.urls import reverse

from apps.teams.models import BaseTeamModel


class AccountType(BaseTeamModel):
    """
    AccountType model for categorizing accounts with type and subtype.
    """

    type_name = models.CharField(max_length=100, help_text="Account type (e.g., Asset, Liability, Income, Expense)")
    subtype_name = models.CharField(max_length=100, help_text="Account subtype (e.g., Checking, Savings, Credit Card)")

    class Meta:
        ordering = ["type_name", "subtype_name"]
        unique_together = ["team", "type_name", "subtype_name"]

    def __str__(self):
        return f"{self.type_name} - {self.subtype_name}"


class Account(BaseTeamModel):
    """
    Account model for tracking financial accounts.
    Can be assets, liabilities, income, expenses, or equity.
    """

    name = models.CharField(max_length=200)
    account_number = models.IntegerField(help_text="Account number (1000s for assets, 2000s for liabilities, etc.)")
    account_type = models.ForeignKey(
        AccountType,
        on_delete=models.PROTECT,
        related_name="accounts_by_type",
        help_text="Account type classification",
        null=True,
        blank=True,
    )
    subtype = models.ForeignKey(
        AccountType,
        on_delete=models.PROTECT,
        related_name="accounts_by_subtype",
        help_text="Account subtype classification",
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
        return reverse("budgeting:account-detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})

    @property
    def account_balance(self):
        """Calculate account balance from transactions."""
        # Sum transactions where this account is the account field
        account_total = self.transactions.aggregate(total=Sum("amount"))["total"] or 0
        # Sum transactions where this account is the category field
        category_total = self.categorized_transactions.aggregate(total=Sum("amount"))["total"] or 0
        return account_total + category_total


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


class Transaction(BaseTeamModel):
    """
    Transaction model for tracking income and expenses.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("posted", "Posted"),
        ("reconciled", "Reconciled"),
    ]

    IMPORT_METHOD_CHOICES = [
        ("manual", "Manual Entry"),
        ("csv", "CSV Import"),
        ("api", "API Import"),
        ("bank_feed", "Bank Feed"),
    ]

    date_posted = models.DateField(help_text="Date the transaction was posted")
    amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Transaction amount")
    payee = models.ForeignKey(
        Payee,
        on_delete=models.PROTECT,
        related_name="transactions",
        null=True,
        blank=True,
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="transactions",
        help_text="The account being debited/credited",
    )
    category = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="categorized_transactions",
        help_text="The category/account for classification",
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)
    imported_on = models.DateField(null=True, blank=True, help_text="Date the transaction was imported")
    import_method = models.CharField(
        max_length=20,
        choices=IMPORT_METHOD_CHOICES,
        default="manual",
        help_text="How the transaction was imported",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        help_text="Transaction status",
    )
    is_cleared = models.BooleanField(default=False, help_text="Whether the transaction has cleared")
    is_reconciled = models.BooleanField(default=False, help_text="Whether the transaction has been reconciled")

    class Meta:
        ordering = ["-date_posted", "-created_at"]

    def __str__(self):
        payee_name = self.payee.name if self.payee else "No Payee"
        return f"{self.date_posted} - {payee_name} - ${self.amount}"


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
