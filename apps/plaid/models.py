"""
Plaid integration models.
Stores Plaid items, accounts, and imported transactions.
"""

from django.conf import settings
from django.db import models

from apps.books.models import BaseBookModel
from apps.utils.fields import EncryptedTextField


def is_foreign_currency(code) -> bool:
    """True for a known currency that isn't the books' own. Unknown (None) is not flagged."""
    return bool(code) and code.upper() != settings.BASE_CURRENCY.upper()


class PlaidItem(BaseBookModel):
    """
    Represents a connected bank login (Plaid Item).
    Each item can have multiple accounts.
    """

    # What the bank connection needs from the user, if anything. Set from Plaid's
    # ITEM webhooks and from errors a sync hits (apps.plaid.item_status).
    STATUS_HEALTHY = "healthy"
    STATUS_LOGIN_REQUIRED = "login_required"  # the bank wants the user to sign in again
    STATUS_PENDING_EXPIRATION = "pending_expiration"  # consent runs out soon
    STATUS_PENDING_DISCONNECT = "pending_disconnect"  # the institution will drop the connection soon
    STATUS_REVOKED = "revoked"  # the user withdrew access at the bank
    STATUS_ERROR = "error"  # any other item error Plaid reported

    STATUS_CHOICES = [
        (STATUS_HEALTHY, "Healthy"),
        (STATUS_LOGIN_REQUIRED, "Sign-in required"),
        (STATUS_PENDING_EXPIRATION, "Access expiring"),
        (STATUS_PENDING_DISCONNECT, "Disconnecting soon"),
        (STATUS_REVOKED, "Access revoked"),
        (STATUS_ERROR, "Error"),
    ]

    #: Statuses a sync cannot get past until the user reconnects.
    BLOCKED_STATUSES = (STATUS_LOGIN_REQUIRED, STATUS_REVOKED)

    plaid_item_id = models.CharField(max_length=255, unique=True, help_text="Plaid's unique identifier for this item")
    # Encrypted at rest with FIELD_ENCRYPTION_KEY: whoever holds it can read the
    # user's bank transactions.
    access_token = EncryptedTextField(help_text="Access token for Plaid API (encrypted at rest)")
    institution_name = models.CharField(max_length=255, help_text="Name of the financial institution")
    institution_id = models.CharField(
        max_length=64, blank=True, default="", help_text="Plaid's institution id (for spotting a duplicate link)"
    )

    cursor = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Cursor for incremental transaction sync",
    )

    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When transactions were last successfully synced from Plaid",
    )

    # The sync lock (see apps.plaid.sync_lock): set while a sync runs, so a
    # webhook, the schedule and the Refresh button never sync one item at once.
    sync_lock_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="A sync holds this item until then (expires, so a crashed worker can't hold it forever)",
    )
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_HEALTHY)
    error_code = models.CharField(max_length=100, blank=True, help_text="Plaid's error_code, when status says so")
    error_message = models.TextField(blank=True, help_text="Plaid's display message for the error, if any")
    consent_expiration_time = models.DateTimeField(
        null=True, blank=True, help_text="When the user's consent at the institution runs out"
    )
    new_accounts_available = models.BooleanField(
        default=False, help_text="Plaid found accounts at this bank the user hasn't shared yet"
    )

    sync_requested = models.BooleanField(
        default=False,
        help_text="A sync was asked for while one was running; the running one goes again when done",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Plaid Item"
        verbose_name_plural = "Plaid Items"

    def __str__(self):
        return f"{self.institution_name} ({self.plaid_item_id})"

    @property
    def needs_attention(self):
        """True when the user should reconnect (or re-share accounts) through Link update mode."""
        return self.status != self.STATUS_HEALTHY or self.new_accounts_available


class PlaidAccount(BaseBookModel):
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

    is_ignored = models.BooleanField(
        default=False,
        help_text="The user chose not to import this account (e.g. a mortgage tracked elsewhere)",
    )

    name = models.CharField(max_length=255, help_text="Account name from Plaid")
    mask = models.CharField(max_length=10, blank=True, help_text="Last 4 digits of account number")
    subtype = models.CharField(max_length=100, help_text="Account subtype (e.g., checking, savings)")
    type = models.CharField(max_length=100, help_text="Account type (e.g., depository, credit)")
    iso_currency_code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="The account's currency (ISO code, or Plaid's unofficial code for e.g. crypto)",
    )

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

    @property
    def is_foreign_currency(self):
        """True when the account is kept in a currency other than the books' (`BASE_CURRENCY`)."""
        return is_foreign_currency(self.iso_currency_code)

    def can_sync_transactions(self):
        """
        Check if this account is ready to sync transactions.
        Requires a mapped ledger account.
        """
        return self.is_mapped


class PlaidTransaction(BaseBookModel):
    """
    This model add's extra context to the bank app's bank transactions just for plaid transactions.

    """

    plaid_transaction_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Plaid's unique identifier for this transaction",
    )
    bank_transaction = models.OneToOneField(
        "bank_feed.BankTransaction",
        on_delete=models.CASCADE,
        related_name="plaid_transaction",
        help_text="The bank transaction this plaid transaction is linked to",
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
        ordering = ["-bank_transaction__posted_date"]
        verbose_name = "Plaid Transaction"
        verbose_name_plural = "Plaid Transactions"
        indexes = [
            models.Index(fields=["plaid_account"]),
            models.Index(fields=["pending"]),
        ]

    @property
    def currency(self):
        return self.iso_currency_code or self.unofficial_currency_code

    def __str__(self):
        return f"{self.bank_transaction.posted_date} - {self.bank_transaction.description} - ${self.bank_transaction.amount}"  # noqa: E501
