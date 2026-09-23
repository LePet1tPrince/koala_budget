"""
A reconciliation: one bank or card statement checked against the ledger.

The statement is the record the reconciliation guarantee rests on. Which lines
it covered is carried by `JournalLine.reconciliation`, not by a list here, so a
line always knows the statement that locked it -- and the adjustment entry, if
any, is found through its bank line rather than through a foreign key to
`JournalEntry` (which `apps.portability`'s wipe raw-deletes, and which an FK
from here would block).

Amounts are stored in LEDGER sign (dr - cr). The API and the page speak
statement sign; `services/signs.py` is the one place that converts.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.teams.models import BaseTeamModel


class Reconciliation(BaseTeamModel):
    STATUS_DRAFT = "draft"
    STATUS_COMPLETED = "completed"
    STATUS_UNDONE = "undone"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_UNDONE, "Undone"),
    ]

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        related_name="reconciliations",
        help_text="The asset or liability account this statement is for",
    )
    statement_date = models.DateField(help_text="Closing date printed on the statement")
    statement_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text="Closing balance on the statement, in ledger sign (dr - cr)",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    # Snapshots taken at finish. `cleared_total` is what the statement's own lines
    # summed to (ledger sign, adjustment included); a statement is intact while
    # they still do.
    opening_balance = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    cleared_total = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    adjustment_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, help_text="Adjustment posted at finish, ledger sign"
    )

    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    undone_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-statement_date", "-id"]
        verbose_name = "Reconciliation"
        verbose_name_plural = "Reconciliations"
        constraints = [
            models.UniqueConstraint(
                fields=["account"],
                condition=Q(status="draft"),
                name="one_draft_reconciliation_per_account",
            )
        ]

    def __str__(self):
        return f"{self.account} statement {self.statement_date} ({self.status})"

    @property
    def is_draft(self):
        return self.status == self.STATUS_DRAFT

    @property
    def is_completed(self):
        return self.status == self.STATUS_COMPLETED
