"""
Plaid integration models.
Stores Plaid items, accounts, and imported transactions.
"""


from django.db import models

from apps.teams.models import BaseTeamModel


class PlaidItem(BaseTeamModel):
    """
    Represents a connected bank login (Plaid Item).
    Each item can have multiple accounts.
    """

    plaid_item_id = models.CharField(max_length=255, unique=True, help_text="Plaid's unique identifier for this item")
    # TODO: Encrypt this field in production using django-encrypted-model-fields or similar
    access_token = models.CharField(max_length=512, help_text="Access token for Plaid API")
    # access_token = EncryptedCharField(max_length=512, help_text="Access token for Plaid API")
    institution_name = models.CharField(max_length=255, help_text="Name of the financial institution")

    cursor = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Cursor for incremental transaction sync",
    )
    is_active = models.BooleanField(default=True, help_text="Whether this item is currently active")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Plaid Item"
        verbose_name_plural = "Plaid Items"

    def __str__(self):
        return f"{self.institution_name} ({self.plaid_item_id})"


class PlaidAccount(BaseTeamModel):
    """
    Maps a Plaid account to a ledger Account.
    Each Plaid account feeds transactions into a specific ledger account.
    """

    plaid_account_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Plaid's unique identifier for this account",
    )
    item = models.ForeignKey(
        PlaidItem,
        on_delete=models.CASCADE,
        related_name="accounts",
        help_text="The Plaid item this account belongs to",
    )

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="plaid_accounts",
        help_text="Ledger account this Plaid account feeds into",
    )

    name = models.CharField(max_length=255, help_text="Account name from Plaid")
    mask = models.CharField(max_length=10, blank=True, help_text="Last 4 digits of account number")
    subtype = models.CharField(max_length=100, help_text="Account subtype (e.g., checking, savings)")
    type = models.CharField(max_length=100, help_text="Account type (e.g., depository, credit)")

    class Meta:
        ordering = ["name"]
        verbose_name = "Plaid Account"
        verbose_name_plural = "Plaid Accounts"

    def __str__(self):
        if self.account:
            return f"{self.name} ({self.mask}) → {self.account.name}"
        return f"{self.name} ({self.mask}) [Unmapped]"

    @property
    def is_mapped(self):
        """Check if this Plaid account is mapped to a ledger account."""
        return self.account is not None

    def can_sync_transactions(self):
        """
        Check if this account is ready to sync transactions.
        Requires both a mapped ledger account and an active Plaid item.
        """
        return self.is_mapped and self.item.is_active


class PlaidTransaction(BaseTeamModel):
    """
    This model add's extra context to the bank app's bank transactions just for plaid transactions.

    """
    bank_transaction = models.OneToOneField(
        "bank_feed.BankTransaction",
        on_delete=models.CASCADE,
        related_name="plaid_transaction",
        help_text="The bank transaction this plaid transaction is linked to",
    )

    plaid_transaction_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Plaid's unique identifier for this transaction",
    )
    plaid_account = models.ForeignKey(
        PlaidAccount,
        on_delete=models.CASCADE,
        related_name="transactions",
        help_text="The Plaid account this transaction belongs to",
    )

    iso_currency_code = models.CharField(max_length=10, null=True, blank=True, help_text="ISO currency code")
    unofficial_currency_code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="Unofficial currency code for non-standard currencies",
    )

    # Dates
    authorized_date = models.DateField(null=True, blank=True, help_text="Authorization date")

    # Pending status
    pending = models.BooleanField(default=False, help_text="Whether this transaction is pending")
    pending_transaction_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="ID of the pending transaction this replaces",
    )

    # Plaid categorization
    personal_finance_category = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Plaid's personal finance category",
    )
    personal_finance_category_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Plaid's personal finance category ID",
    )
    category_confidence = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Confidence level of Plaid's categorization",
    )

    # Additional metadata
    payment_channel = models.CharField(max_length=50, null=True, blank=True, help_text="Payment channel")
    transaction_type = models.CharField(max_length=50, null=True, blank=True, help_text="Transaction type")

    location = models.JSONField(null=True, blank=True, help_text="Transaction location data")
    merchant_metadata = models.JSONField(null=True, blank=True, help_text="Merchant metadata")

    class Meta:
        ordering = ["-bank_transaction__date"]
        verbose_name = "Plaid Transaction"
        verbose_name_plural = "Plaid Transactions"
        indexes = [
            models.Index(fields=["plaid_account", "journal_entry"]),
            models.Index(fields=["pending"]),
        ]

    def __str__(self):
        return f"{self.bank_transaction.date} - {self.bank_transaction.name} - ${self.bank_transaction.amount}"
