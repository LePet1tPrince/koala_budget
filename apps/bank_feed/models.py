"""
Bank feed models.
Stores imported transactions from various sources (Plaid, CSV, manual).
These become JournalEntry records when the user categorizes them.
"""

from django.db import models

from apps.teams.models import BaseTeamModel


class BankTransaction(BaseTeamModel):
    """
    Staging model for transactions imported from external sources.
    These become JournalEntry records when the user categorizes them.

    Supports multiple ingestion sources:
    - plaid: Transactions synced from Plaid
    - csv: Transactions imported via CSV upload
    - manual: Manually entered bank feed transactions
    """


    # Source choices for imported transactions
    SOURCE_PLAID = "plaid"
    SOURCE_CSV = "csv"
    SOURCE_MANUAL = "manual"
    SOURCE_SYSTEM = "system"

    SOURCE_CHOICES = [
        (SOURCE_PLAID, "Plaid"),
        (SOURCE_CSV, "CSV"),
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_SYSTEM, "System"),
    ]

    # Source of this transaction
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_PLAID,
        help_text="Source of this imported transaction (plaid, csv, manual)",
    )

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        related_name="bank_transactions",
        help_text="The account this transaction belongs to",
    )

    # Plaid-specific fields (only populated when source='plaid')
    plaid_transaction_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Plaid's unique identifier for this transaction (only for source=plaid)",
    )
    plaid_account = models.ForeignKey(
        "plaid.PlaidAccount",
        on_delete=models.CASCADE,
        related_name="imported_transactions",
        null=True,
        blank=True,
        help_text="The Plaid account this transaction belongs to (only for source=plaid)",
    )

    # Amount and currency
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Transaction amount (positive = outflow, negative = inflow in Plaid convention)",
    )
    iso_currency_code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="ISO currency code",
    )
    unofficial_currency_code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="Unofficial currency code for non-standard currencies",
    )

    # Dates
    date = models.DateField(help_text="Transaction date")
    authorized_date = models.DateField(null=True, blank=True, help_text="Authorization date")

    # Pending status
    pending = models.BooleanField(default=False, help_text="Whether this transaction is pending")
    pending_transaction_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="ID of the pending transaction this replaces",
    )

    # Description and merchant
    description = models.CharField(max_length=255, help_text="Transaction description")
    merchant_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Merchant name",
    )

    # Plaid categorization (only for source='plaid')
    plaid_category = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Plaid's personal finance category",
    )
    plaid_category_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Plaid's personal finance category ID",
    )
    plaid_category_confidence = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Confidence level of Plaid's categorization",
    )

    # Additional metadata
    payment_channel = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Payment channel",
    )
    transaction_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Transaction type",
    )

    location = models.JSONField(null=True, blank=True, help_text="Transaction location data")
    merchant_metadata = models.JSONField(null=True, blank=True, help_text="Merchant metadata")

    raw = models.JSONField(null=True, blank=True, help_text="Raw transaction data from source")

    # Link to journal entry (null = uncategorized)
    journal_entry = models.ForeignKey(
        "journal.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bank_feed_transactions",
        help_text="Journal entry created from this transaction (null = uncategorized)",
    )

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "Imported Transaction"
        verbose_name_plural = "Imported Transactions"
        indexes = [
            models.Index(fields=["plaid_account", "journal_entry"]),
            models.Index(fields=["date"]),
            models.Index(fields=["pending"]),
            models.Index(fields=["source"]),
        ]

    def __str__(self):
        return f"{self.date} - {self.description} - ${self.amount}"

    @property
    def is_categorized(self):
        """Check if this transaction has been categorized (linked to a journal entry)."""
        return self.journal_entry is not None
