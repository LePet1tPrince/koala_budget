from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils.dateparse import parse_date

from apps.budget.models import Budget
from apps.teams.models import BaseTeamModel


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
        indexes = [
            models.Index(fields=["entry_date"]),
            models.Index(fields=["status"]),
        ]

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

    is_reconciled = models.BooleanField(default=False, help_text="Whether this line has been reconciled")
    reconciled_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date this line was reconciled to a bank statement",
    )
    is_archived = models.BooleanField(
        default=False, help_text="Whether this line has been archived"
    )

    budget = models.ForeignKey(
        "budget.Budget",
        on_delete=models.SET_NULL,
        related_name="journal_lines",
        null=True,
        blank=True,
        editable=False,
        help_text="Link to budget based on account_id and journal entry date month",
    )

    class Meta:
        ordering = ["id"]
        verbose_name = "Journal Line"
        verbose_name_plural = "Journal Lines"
        indexes = [
            models.Index(fields=["account"]),
            models.Index(fields=["journal_entry"]),
            models.Index(fields=["is_cleared", "is_reconciled", "is_archived"]),
            models.Index(fields=["budget"]),
        ]

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

        return (
            Budget.objects
            .filter(
                team=self.team,
                category=self.account,
                month=month_start,
            )
            .first()
        )

    def save(self, *args, **kwargs):
        """Automatically link to budget based on account and entry date."""
        self.budget = self._calculate_budget()
        super().save(*args, **kwargs)

    # this could probably be moved to serializers. Not really necessary here.
    @property
    def amount(self):
        """Return the non-zero amount (either debit or credit)."""
        return self.dr_amount if self.dr_amount > 0 else self.cr_amount
