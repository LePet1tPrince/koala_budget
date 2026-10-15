from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.books.models import BaseBookModel


def counted_entries(path=""):
    """
    `Q` selecting journal entries that count toward anything: balances, reports,
    budget actuals, net worth and the ledger -- every entry that is not void.

    A void bank row always has a void entry (`apps.journal.services.voiding`), so
    voiding a row in the feed takes its entry off the books through this one test.
    `path` is the lookup from the queried model to the entry: "" on `JournalEntry`,
    "journal_entry__" on `JournalLine`, "journal_lines__journal_entry__" on `Account`.
    """
    return ~Q(**{f"{path}status": JournalEntry.STATUS_VOID})


def transaction_entries(path=""):
    """
    `Q` selecting entries that are transactions: everything but the budget entries
    (`apps.budget.ledger`), which move money between budget buckets and never between
    real accounts. Anything that lists, counts or dates "transactions" -- the
    Transactions page, the journal API, "does this book have any history yet",
    exports -- filters on this. Balances don't need to: a budget entry's lines are
    all on budget buckets, which no report or balance reads. `path` as for
    `counted_entries`.
    """
    return ~Q(**{f"{path}source": JournalEntry.SOURCE_BUDGET})


class JournalEntry(BaseBookModel):
    """
    Journal Entry model for double-entry bookkeeping.
    Each entry must have balanced debits and credits across its journal lines.
    """

    STATUS_DRAFT = "draft"
    STATUS_POSTED = "posted"
    STATUS_VOID = "void"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_POSTED, "Posted"),
        (STATUS_VOID, "Void"),
    ]

    SOURCE_MANUAL = "manual"
    SOURCE_IMPORT = "import"
    SOURCE_BANK_MATCH = "bank_match"
    SOURCE_RECURRING = "recurring"
    # An adjustment posted when a statement is finished with a difference
    # (apps.reconciliation). Its own source so undo can find it without guessing.
    SOURCE_RECONCILIATION = "reconciliation"
    # A budget move between budget buckets (apps.budget.buckets). The only kind of
    # entry a bucket may appear in, and it may hold nothing else
    # (apps.accounts.guards.assert_budget_entry_rules).
    SOURCE_BUDGET = "budget"

    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual Entry"),
        (SOURCE_IMPORT, "Import"),
        (SOURCE_BANK_MATCH, "Bank Match"),
        (SOURCE_RECURRING, "Recurring Entry"),
        (SOURCE_RECONCILIATION, "Reconciliation Adjustment"),
        (SOURCE_BUDGET, "Budget"),
    ]

    entry_date = models.DateField(help_text="Date of the journal entry")
    payee = models.ForeignKey(
        "accounts.Payee",
        on_delete=models.PROTECT,
        related_name="journal_entries",
        null=True,
        blank=True,
        help_text="Optional payee for this entry",
    )
    description = models.TextField(help_text="Description of the journal entry")
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_MANUAL,
        help_text="Source of this journal entry",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        help_text="Status of the journal entry",
    )

    # A transaction is voided, never archived: `status` is the one "doesn't count"
    # state, and the flags inherited from BaseModel are removed so there is no
    # second one to disagree with it.
    is_archived = None
    archived_at = None

    class Meta:
        ordering = ["-entry_date", "-created_at"]
        verbose_name = "Journal Entry"
        verbose_name_plural = "Journal Entries"
        constraints = [
            # A month's budget is one entry (apps.budget.ledger.write_month), dated the first.
            models.UniqueConstraint(
                fields=["book", "entry_date"],
                condition=Q(source="budget"),
                name="one_budget_entry_per_book_month",
            ),
        ]

    def __str__(self):
        return f"JE-{self.id} - {self.entry_date} - {self.description[:50]}"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_status = instance.__dict__.get("status")
        return instance

    def save(self, *args, **kwargs):
        """
        Save, and carry a change of void state to every bank row on this entry.

        A row linked to an entry is void exactly when the entry is. Written with
        `QuerySet.update()`, which skips `BankTransaction.save()` -- the rows are
        being brought in line with this entry, which is what that save would do.
        """
        # A new entry has no rows yet. An instance not read from the database
        # (no `_loaded_status`) may have changed status unseen, so it syncs too.
        adding = self._state.adding
        known = hasattr(self, "_loaded_status")
        changed = not known or (self._loaded_status == self.STATUS_VOID) != (self.status == self.STATUS_VOID)
        super().save(*args, **kwargs)
        self._loaded_status = self.status
        if not adding and changed:
            voided = self.status == self.STATUS_VOID
            bank_transaction = apps.get_model("bank_feed", "BankTransaction")
            bank_transaction.objects.filter(journal_entry=self).exclude(is_void=voided).update(
                is_void=voided, voided_at=timezone.now() if voided else None
            )

    def get_absolute_url(self):
        return reverse("journal:journalentry_detail", args=[*self.book.url_args, self.pk])

    def clean(self):
        """Validate that debits equal credits."""
        super().clean()
        if self.pk:  # Only validate if the entry has been saved (has lines)
            total_debits = self.lines.aggregate(total=Sum("dr_amount"))["total"] or Decimal("0")
            total_credits = self.lines.aggregate(total=Sum("cr_amount"))["total"] or Decimal("0")

            if total_debits != total_credits:
                raise ValidationError(f"Journal entry must balance. Debits: {total_debits}, Credits: {total_credits}")

    @property
    def total_debits(self):
        """Calculate total debits for this entry."""
        return self.lines.aggregate(total=Sum("dr_amount"))["total"] or Decimal("0")

    @property
    def total_credits(self):
        """Calculate total credits for this entry."""
        return self.lines.aggregate(total=Sum("cr_amount"))["total"] or Decimal("0")

    @property
    def is_balanced(self):
        """Check if the entry is balanced."""
        return self.total_debits == self.total_credits


class JournalLineQuerySet(models.QuerySet):
    def bulk_create_for_import(self, lines, batch_size=1000):
        """
        Insert many lines at once, keeping `save()`'s ledger guard.

        `JournalLine.save()` checks the budget-entry rule and `post_save` then writes
        an audit row: at import volumes (a YNAB export is ~13,000 lines) that is tens
        of thousands of extra queries, the difference between an import that takes
        seconds and one that takes minutes. `bulk_create` skips `save()` and its
        signals, so the guard runs here instead, in one query for the accounts.

        Deliberate consequence: no row-level `AuditLog` entries are written. An
        import is one operation, and 13,000 field diffs describing it would be noise;
        the `AuditEvent` the importer records is the meaningful trail.
        """
        _assert_lines_respect_budget_rules(lines)
        return self.bulk_create(lines, batch_size=batch_size)


def _assert_lines_respect_budget_rules(lines):
    """`assert_budget_entry_rules` over many unsaved lines, in one query for their accounts."""
    from apps.accounts.guards import assert_budget_entry_rules
    from apps.accounts.models import Account

    accounts = Account.objects.select_related("account_group").in_bulk({line.account_id for line in lines})
    for line in lines:
        assert_budget_entry_rules(line.journal_entry.source == JournalEntry.SOURCE_BUDGET, [accounts[line.account_id]])


class JournalLine(BaseBookModel):
    """
    Journal Line model representing individual debit/credit lines in a journal entry.
    Each line must have either a debit or credit amount (not both).
    """

    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
        help_text="The journal entry this line belongs to",
    )

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        related_name="journal_lines",
        help_text="The account being debited or credited",
    )

    dr_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Debit amount (sum of debits must equal sum of credits)",
    )

    cr_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Credit amount (sum of credits must equal sum of debits)",
    )

    is_cleared = models.BooleanField(default=False, help_text="Whether this line has cleared the bank")
    is_reconciled = models.BooleanField(default=False, help_text="Whether this line has been reconciled")
    # Lines are never archived; the entry's status is what takes them out of balances.
    is_archived = None
    archived_at = None

    # The statement that ticked (draft) or locked (completed) this line. Kept when
    # a line is unreconciled or its statement undone, so the drift check can name
    # the lines that moved; `is_reconciled` stays the only input to balances.
    reconciliation = models.ForeignKey(
        "reconciliation.Reconciliation",
        on_delete=models.SET_NULL,
        related_name="lines",
        null=True,
        blank=True,
        help_text="Statement this line was ticked or reconciled on",
    )

    objects = JournalLineQuerySet.as_manager()

    class Meta:
        ## No date_posted field in journal_line. That's in journal_entry. Can we incorporate that?
        # indexes = [
        #     models.Index(fields=["team", "date_posted"]),
        #     models.Index(fields=["account", "date_posted"]),
        # ]
        ordering = ["id"]
        verbose_name = "Journal Line"
        verbose_name_plural = "Journal Lines"

    def __str__(self):
        amount = self.dr_amount if self.dr_amount > 0 else self.cr_amount
        dr_cr = "DR" if self.dr_amount > 0 else "CR"
        return f"{self.account} - {dr_cr} {amount}"

    def clean(self):
        """Validate that a line has either debit or credit, not both or neither."""
        super().clean()

        # Check that we don't have both debit and credit
        if self.dr_amount > 0 and self.cr_amount > 0:
            raise ValidationError("A journal line cannot have both debit and credit amounts.")

        # Check that we have at least one amount
        if self.dr_amount == 0 and self.cr_amount == 0:
            raise ValidationError("A journal line must have either a debit or credit amount.")

        # Ensure amounts are not negative
        if self.dr_amount < 0 or self.cr_amount < 0:
            raise ValidationError("Debit and credit amounts cannot be negative.")

    def save(self, *args, **kwargs):
        """
        The backstop for the budget ledger rule: a budget bucket only in a budget
        entry, a budget entry only of buckets, whatever path saves the line. Bulk
        paths skip `save()` and check it themselves
        (`JournalLineQuerySet.bulk_create_for_import`).
        """
        from apps.accounts.guards import assert_budget_entry_rules

        assert_budget_entry_rules(self.journal_entry.source == JournalEntry.SOURCE_BUDGET, [self.account])
        super().save(*args, **kwargs)

    @property
    def amount(self):
        """Return the non-zero amount (either debit or credit)."""
        return self.dr_amount if self.dr_amount > 0 else self.cr_amount
