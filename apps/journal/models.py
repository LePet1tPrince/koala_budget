from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils.dateparse import parse_date

from apps.budget.models import Budget
from apps.teams.models import BaseTeamModel


def counted_entries(path=""):
    """
    `Q` selecting journal entries that count toward anything: balances, reports,
    budget actuals, net worth and the ledger.

    An entry does not count when it is voided, or when a bank transaction linked to
    it is archived -- archiving a row takes it off the books, not just out of the
    feed. `path` is the lookup from the queried model to the entry: "" on
    `JournalEntry`, "journal_entry__" on `JournalLine`, "journal_lines__journal_entry__"
    on `Account` (for use in an aggregate's `filter=`, where a join would fan out --
    hence an `__in` subquery rather than a reverse-relation lookup).
    """
    bank_transaction = apps.get_model("bank_feed", "BankTransaction")
    archived_entry_ids = bank_transaction.objects.filter(is_archived=True, journal_entry__isnull=False).values(
        "journal_entry_id"
    )
    return ~Q(**{f"{path}status": JournalEntry.STATUS_VOID}) & ~Q(**{f"{path}id__in": archived_entry_ids})


class JournalEntry(BaseTeamModel):
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

    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual Entry"),
        (SOURCE_IMPORT, "Import"),
        (SOURCE_BANK_MATCH, "Bank Match"),
        (SOURCE_RECURRING, "Recurring Entry"),
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

    class Meta:
        ordering = ["-entry_date", "-created_at"]
        verbose_name = "Journal Entry"
        verbose_name_plural = "Journal Entries"

    def __str__(self):
        return f"JE-{self.id} - {self.entry_date} - {self.description[:50]}"

    def get_absolute_url(self):
        return reverse("journal:journalentry_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})

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
    def bulk_create_for_import(self, lines, budget_map, batch_size=1000):
        """
        Insert many lines at once, standing in for `save()`'s budget lookup.

        `JournalLine.save()` resolves `budget` with a query per line, and `post_save`
        then writes an audit row: at import volumes (a YNAB export is ~13,000 lines)
        that is tens of thousands of extra queries, the difference between an import
        that takes seconds and one that takes minutes. `bulk_create` skips `save()`
        and its signals, so the budget link has to be made here instead --
        `budget_map` is `{(account_id, first_of_month): budget_id}`, built once from
        the budgets the same import created.

        Deliberate consequence: no row-level `AuditLog` entries are written. An
        import is one operation, and 13,000 field diffs describing it would be noise;
        the `AuditEvent` the importer records is the meaningful trail.
        """
        for line in lines:
            if line.budget_id is None:
                month = line.journal_entry.entry_date.replace(day=1)
                line.budget_id = budget_map.get((line.account_id, month))
        return self.bulk_create(lines, batch_size=batch_size)


class JournalLine(BaseTeamModel):
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
    is_archived = models.BooleanField(default=False, help_text="Whether this line has been archived")

    # Budget foreign key - commented out until Budget model is ready
    budget = models.ForeignKey(
        "budget.Budget",
        on_delete=models.SET_NULL,
        related_name="journal_lines",
        null=True,
        blank=True,
        editable=False,
        help_text="Link to budget based on account_id and journal entry date month",
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

    ## Budget Auto linking

    def _calculate_budget(self):
        """
        Calculate the budget based on the account and entry date.
        """
        if not self.journal_entry or not self.journal_entry.entry_date:
            return None

        entry_date = self.journal_entry.entry_date
        if isinstance(entry_date, str):
            entry_date = parse_date(entry_date)

        month_start = entry_date.replace(day=1)

        return Budget.objects.filter(
            team=self.team,
            category=self.account,
            month=month_start,
        ).first()

    def save(self, *args, **kwargs):
        """
        Automatically link to budget based on account and entry date.

        One query per line. Bulk paths skip `save()` entirely and must resolve the
        same link themselves -- see `JournalLineQuerySet.bulk_create_for_import`,
        which exists so the two cannot drift apart unnoticed.
        """
        self.budget = self._calculate_budget()
        super().save(*args, **kwargs)

    @property
    def amount(self):
        """Return the non-zero amount (either debit or credit)."""
        return self.dr_amount if self.dr_amount > 0 else self.cr_amount
