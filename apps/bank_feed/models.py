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

    # Amount and currency
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Transaction amount (positive = outflow, negative = inflow in Plaid convention)",
    )

    # Dates
    date = models.DateField(help_text="Transaction date")
    authorized_date = models.DateField(null=True, blank=True, help_text="Authorization date")

    # Description and merchant
    description = models.CharField(max_length=255, help_text="Transaction description")
    ## should this be related to payee?
    merchant_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Merchant name",
    )
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
            models.Index(fields=["journal_entry"]),
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
