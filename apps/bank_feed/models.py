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

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        related_name="bank_transactions",
        help_text="The account this transaction belongs to",
    )

    # Link to journal entry (null = uncategorized)
    journal_entry = models.ForeignKey(
        "journal.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bank_feed_transactions",
        help_text="Journal entry created from this transaction (null = uncategorized)",
    )
    # Amount and currency
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Transaction amount (positive = outflow, negative = inflow in Plaid convention)",
    )

    # Dates
    posted_date = models.DateField(help_text="Transaction date")

    # Description and merchant
    description = models.CharField(max_length=255, help_text="Transaction description")
    ## should this be related to payee?
    merchant_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Merchant name",
    )

    # Source of this transaction
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_PLAID,
        help_text="Source of this imported transaction (plaid, csv, manual)",
    )
    raw = models.JSONField(null=True, blank=True, help_text="Raw transaction data from source")

    # When a transaction is categorized as a transfer to another feed account, a
    # linked "mirror" leg is created in that account so the transfer shows up in
    # both feeds. Both legs point at the same JournalEntry (no double-counting).
    is_transfer_mirror = models.BooleanField(
        default=False,
        help_text="True if this row is the auto-created counterpart leg of a transfer",
    )

    class Meta:
        ordering = ["-posted_date", "-created_at"]
        verbose_name = "Bank Transaction"
        verbose_name_plural = "Bank Transactions"
        indexes = [
            models.Index(fields=["journal_entry"]),
            models.Index(fields=["posted_date"]),
            models.Index(fields=["source"]),
        ]

    def __str__(self):
        return f"{self.posted_date} - {self.description} - ${self.amount}"

    @property
    def is_categorized(self):
        """Check if this transaction has been categorized (linked to a journal entry)."""
        return self.journal_entry is not None

    @property
    def journal_source(self):
        """Map this transaction's source to a valid JournalEntry source value."""
        from apps.journal.models import JournalEntry

        return {
            self.SOURCE_PLAID: JournalEntry.SOURCE_BANK_MATCH,
            self.SOURCE_CSV: JournalEntry.SOURCE_IMPORT,
            self.SOURCE_MANUAL: JournalEntry.SOURCE_MANUAL,
            self.SOURCE_SYSTEM: JournalEntry.SOURCE_BANK_MATCH,
        }.get(self.source, JournalEntry.SOURCE_IMPORT)


class TransferMatchDismissal(BaseTeamModel):
    """
    Records that the user reviewed two bank transactions flagged as a possible
    duplicated transfer and confirmed they are NOT the same movement of money.

    The transfer detector excludes any pair recorded here, so a dismissed
    suggestion does not keep reappearing on every sync. The two transactions are
    stored in a normalized (low id, high id) order so the pair is unique
    regardless of which side the user clicked.
    """

    transaction_low = models.ForeignKey(
        "bank_feed.BankTransaction",
        on_delete=models.CASCADE,
        related_name="transfer_dismissals_as_low",
        help_text="The paired transaction with the lower id",
    )
    transaction_high = models.ForeignKey(
        "bank_feed.BankTransaction",
        on_delete=models.CASCADE,
        related_name="transfer_dismissals_as_high",
        help_text="The paired transaction with the higher id",
    )

    class Meta:
        verbose_name = "Transfer Match Dismissal"
        verbose_name_plural = "Transfer Match Dismissals"
        unique_together = ["team", "transaction_low", "transaction_high"]

    def __str__(self):
        return f"Not-a-transfer: {self.transaction_low_id} / {self.transaction_high_id}"

    @staticmethod
    def normalize_pair(tx_id_a, tx_id_b):
        """Return (low_id, high_id) for a pair of transaction ids."""
        return (tx_id_a, tx_id_b) if tx_id_a <= tx_id_b else (tx_id_b, tx_id_a)

    @classmethod
    def record(cls, team, tx_id_a, tx_id_b):
        """Idempotently record a dismissed pair (order-independent)."""
        low, high = cls.normalize_pair(tx_id_a, tx_id_b)
        obj, _ = cls.objects.get_or_create(
            team=team,
            transaction_low_id=low,
            transaction_high_id=high,
        )
        return obj
