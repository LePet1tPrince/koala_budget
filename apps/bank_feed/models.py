"""
Bank feed models.
Stores imported transactions from various sources (Plaid, CSV, manual).
These become JournalEntry records when the user categorizes them.
"""

from django.db import models
from django.utils import timezone

from apps.books.models import BaseBookModel

VOID_ROW_MESSAGE = "This transaction is void. Restore it before categorizing it."


class VoidRowError(ValueError):
    """A void bank row was about to be linked to an entry that counts."""


class BankTransaction(BaseBookModel):
    """
    Staging model for transactions imported from external sources.
    These become JournalEntry records when the user categorizes them.

    Supports multiple ingestion sources:
    - plaid: Transactions synced from Plaid
    - csv: Transactions imported via CSV upload
    - manual: Manually entered bank feed transactions
    - ynab: A YNAB register row, written by the YNAB import
    """

    # Source choices for imported transactions
    SOURCE_PLAID = "plaid"
    SOURCE_CSV = "csv"
    SOURCE_MANUAL = "manual"
    SOURCE_SYSTEM = "system"
    SOURCE_YNAB = "ynab"

    SOURCE_CHOICES = [
        (SOURCE_PLAID, "Plaid"),
        (SOURCE_CSV, "CSV"),
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_SYSTEM, "System"),
        (SOURCE_YNAB, "YNAB"),
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

    # Void, not "archived": a void row counts toward nothing. While the row is
    # linked to a journal entry this is a stored copy of `entry.status == void`,
    # kept in step by `save()` here and by `JournalEntry.save()`; only an
    # uncategorized row's flag is its own. Change it through
    # `apps.journal.services.voiding`, never directly.
    is_void = models.BooleanField(default=False, help_text="Whether this transaction is void (counts toward nothing)")
    voided_at = models.DateTimeField(null=True, blank=True, help_text="When this transaction was voided")

    # The flags inherited from BaseModel would be a second, competing "doesn't
    # count" state; `is_void` replaces them.
    is_archived = None
    archived_at = None

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
    def is_active(self):
        return not self.is_void

    def archive(self):
        raise NotImplementedError("Bank transactions are voided, not archived: use apps.journal.services.voiding.")

    def restore(self):
        raise NotImplementedError("Restore a bank transaction with apps.journal.services.voiding.restore.")

    def save(self, *args, **kwargs):
        """
        Keep a linked row's void flag equal to its entry's status.

        The entry is the truth for a linked row, read fresh from the database so a
        stale in-memory entry cannot write a stale flag. Linking a *void* row to an
        entry that is not void is refused: it would silently restore the row.
        """
        if self.journal_entry_id:
            from apps.journal.models import JournalEntry

            entry_status = (
                JournalEntry.objects.filter(pk=self.journal_entry_id).values_list("status", flat=True).first()
            )
            entry_void = entry_status == JournalEntry.STATUS_VOID
            if self.is_void and not entry_void and not self._state.adding:
                previous = BankTransaction.objects.filter(pk=self.pk).values_list("journal_entry_id", flat=True).first()
                if previous != self.journal_entry_id:
                    raise VoidRowError(VOID_ROW_MESSAGE)
            if self.is_void != entry_void:
                self.is_void = entry_void
                self.voided_at = timezone.now() if entry_void else None
                update_fields = kwargs.get("update_fields")
                if update_fields is not None:
                    kwargs["update_fields"] = {*update_fields, "is_void", "voided_at"}
        super().save(*args, **kwargs)

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
            self.SOURCE_YNAB: JournalEntry.SOURCE_IMPORT,
        }.get(self.source, JournalEntry.SOURCE_IMPORT)


class TransferMatchDismissal(BaseBookModel):
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
        unique_together = ["book", "transaction_low", "transaction_high"]

    def __str__(self):
        return f"Not-a-transfer: {self.transaction_low_id} / {self.transaction_high_id}"

    @staticmethod
    def normalize_pair(tx_id_a, tx_id_b):
        """Return (low_id, high_id) for a pair of transaction ids."""
        return (tx_id_a, tx_id_b) if tx_id_a <= tx_id_b else (tx_id_b, tx_id_a)

    @classmethod
    def record(cls, book, tx_id_a, tx_id_b):
        """Idempotently record a dismissed pair (order-independent)."""
        low, high = cls.normalize_pair(tx_id_a, tx_id_b)
        obj, _ = cls.objects.get_or_create(
            book=book,
            transaction_low_id=low,
            transaction_high_id=high,
        )
        return obj
