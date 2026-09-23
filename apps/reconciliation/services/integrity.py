"""
Whether a finished statement still holds.

A statement is intact while the lines it locked still sum to what they summed
when it was finished. After the guards in `guards.py`, the only ways that can
change are visible ones: a line unreconciled in the feed (with a warning naming
the statement), or a statement undone. Both keep the line's link, so a changed
statement can always name the lines responsible.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from apps.journal.models import JournalEntry, JournalLine, counted_entries

from ..models import Reconciliation
from .candidates import reconciled_balance
from .session import last_completed

ZERO = Decimal("0")


def _locked():
    """A line still locked by its statement: reconciled, on an entry that counts (`counted_entries`)."""
    return Q(is_reconciled=True) & counted_entries("journal_entry__")


def locked_totals(reconciliations) -> dict[int, Decimal]:
    """{reconciliation id: ledger sum of its still-locked lines}, in one query."""
    ids = [r.id for r in reconciliations]
    rows = (
        JournalLine.objects.filter(_locked(), reconciliation_id__in=ids)
        .values("reconciliation_id")
        .annotate(dr=Coalesce(Sum("dr_amount"), ZERO), cr=Coalesce(Sum("cr_amount"), ZERO))
    )
    return {row["reconciliation_id"]: row["dr"] - row["cr"] for row in rows}


def intact_map(reconciliations) -> dict[int, bool]:
    """{id: intact} for completed statements; drafts and undone statements are not judged."""
    completed = [r for r in reconciliations if r.is_completed]
    totals = locked_totals(completed)
    return {r.id: totals.get(r.id, ZERO) == r.cleared_total for r in completed}


def is_intact(reconciliation) -> bool:
    return intact_map([reconciliation]).get(reconciliation.id, False)


def moved_lines(reconciliation):
    """Lines this statement locked that are no longer locked."""
    return (
        reconciliation.lines.filter(~_locked())
        .select_related("journal_entry", "journal_entry__payee")
        .order_by("journal_entry__entry_date", "pk")
    )


@dataclass
class Drift:
    """How far the reconciled balance has moved from the last finished statement (ledger sign)."""

    amount: Decimal = ZERO
    since: Reconciliation | None = None
    lines: list = field(default_factory=list)


def drift(account) -> Drift:
    """
    Compare the current reconciled balance with the latest completed statement.

    The lines named are every line linked to a completed or undone statement of
    this account that is no longer locked -- whatever took it out.
    """
    latest = last_completed(account)
    if latest is None:
        return Drift()
    amount = reconciled_balance(account) - latest.statement_balance
    if amount == 0:
        return Drift(since=latest)
    lines = list(
        JournalLine.objects.filter(
            account=account,
            reconciliation__status__in=(Reconciliation.STATUS_COMPLETED, Reconciliation.STATUS_UNDONE),
        )
        .filter(~_locked())
        # An undone statement's adjustment is voided on purpose; it is not a
        # line that moved, and it will not be back in the list to tick.
        .exclude(
            journal_entry__source=JournalEntry.SOURCE_RECONCILIATION, journal_entry__status=JournalEntry.STATUS_VOID
        )
        .select_related("journal_entry", "journal_entry__payee", "reconciliation")
        .order_by("journal_entry__entry_date", "pk")
    )
    return Drift(amount=amount, since=latest, lines=lines)
