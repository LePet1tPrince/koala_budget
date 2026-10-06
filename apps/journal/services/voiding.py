"""
Voiding and restoring: the one place a transaction's "counts" state changes.

A void transaction counts toward nothing -- no balance, report, budget actual or
net worth. There is one such state, and it is held in two places that must agree:

- `JournalEntry.status == "void"` for the ledger, and
- `BankTransaction.is_void` for every bank row linked to that entry (the primary,
  a transfer's mirror, each mirror of a split's transfer legs).

A row linked to an entry is void exactly when the entry is. A row with no entry
(an uncategorized bank transaction) carries its own flag, because a duplicate
import has to be voidable before anyone categorizes it. An entry with no row has
only its status.

Everything goes through `void()` and `restore()`. The models enforce the same
rule as a backstop (`JournalEntry.save()` pushes its state to its rows,
`BankTransaction.save()` copies it from its entry) so a caller that skips this
module still cannot leave the two disagreeing; `assert_consistent()` checks it.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.bank_feed.models import BankTransaction
from apps.reconciliation.services.guards import ReconciledLineError, assert_entry_removable

from ..models import JournalEntry


class VoidRefused(ValueError):
    """
    Nothing was voided or restored, because some of what was asked can't be.

    `refused` names each refused bank row or entry with its reason, so a caller
    can say which rows to deselect rather than only that something failed.
    """

    def __init__(self, refused):
        self.refused = refused
        super().__init__(refused[0]["error"])


@dataclass
class _Targets:
    entries: dict = field(default_factory=dict)  # id -> JournalEntry
    loose_rows: dict = field(default_factory=dict)  # id -> BankTransaction with no entry
    # Which requested row (or entry) brought each entry in, for naming refusals.
    asked_by: dict = field(default_factory=dict)  # entry id -> ("row"|"entry", id, own account id)


def _collect(entries, rows):
    """
    Resolve what was asked into entries and loose rows, read fresh from the
    database: a caller's objects may be stale (voided since they were loaded).
    """
    targets = _Targets()
    for entry in entries:
        targets.asked_by.setdefault(entry.pk, ("entry", entry.pk, None))
    row_ids = [row.pk for row in rows]
    for row in BankTransaction.objects.filter(pk__in=row_ids).only("pk", "journal_entry_id", "account_id", "is_void"):
        if row.journal_entry_id:
            targets.asked_by[row.journal_entry_id] = ("row", row.pk, row.account_id)
        else:
            targets.loose_rows[row.pk] = row
    targets.entries = {
        entry.pk: entry
        for entry in JournalEntry.objects.filter(pk__in=list(targets.asked_by)).prefetch_related("lines")
    }
    return targets


def _refusal(targets, entry_id, message):
    kind, ident, _account = targets.asked_by[entry_id]
    return {"kind": kind, "id": ident, "error": str(message)}


@transaction.atomic
def void(*, entries=(), rows=()):
    """
    Void `entries` and `rows`, all of them or none.

    A row stands for its entry, and an entry takes every row linked to it. Refused
    when any line on an entry is reconciled: voiding drops every line out of every
    balance, a reconciled one included. Returns `(entry_ids, row_ids)` changed.
    """
    targets = _collect(entries, rows)

    refused = []
    for entry_id, entry in targets.entries.items():
        _kind, _ident, own_account_id = targets.asked_by[entry_id]
        try:
            assert_entry_removable(entry, own_account_id=own_account_id, verb=_("voiding it"))
        except ReconciledLineError as exc:
            refused.append(_refusal(targets, entry_id, exc))
    if refused:
        raise VoidRefused(refused)

    changed_entries = []
    for entry in targets.entries.values():
        if entry.status != JournalEntry.STATUS_VOID:
            entry.status = JournalEntry.STATUS_VOID
            entry.save()  # carries the state to every linked row
            changed_entries.append(entry.pk)

    now = timezone.now()
    changed_rows = [row.pk for row in targets.loose_rows.values() if not row.is_void]
    BankTransaction.objects.filter(pk__in=changed_rows).update(is_void=True, voided_at=now, updated_at=now)

    linked = list(BankTransaction.objects.filter(journal_entry_id__in=changed_entries).values_list("pk", flat=True))
    return changed_entries, sorted({*changed_rows, *linked})


@transaction.atomic
def restore(*, entries=(), rows=()):
    """
    Bring voided `entries` and `rows` back, all of them or none.

    A restored entry is `posted`: every write path in the app posts, and a draft
    is excluded from balances just as a void is. A statement's adjustment is
    refused -- it was voided by undoing its statement, and only finishing the
    statement again can bring it back honestly.
    """
    targets = _collect(entries, rows)

    refused = [
        _refusal(
            targets,
            entry_id,
            _("This is a reconciliation adjustment from an undone statement. Finish the statement again instead."),
        )
        for entry_id, entry in targets.entries.items()
        if entry.status == JournalEntry.STATUS_VOID and entry.source == JournalEntry.SOURCE_RECONCILIATION
    ]
    if refused:
        raise VoidRefused(refused)

    changed_entries = []
    for entry in targets.entries.values():
        if entry.status == JournalEntry.STATUS_VOID:
            entry.status = JournalEntry.STATUS_POSTED
            entry.save()
            changed_entries.append(entry.pk)

    now = timezone.now()
    changed_rows = [row.pk for row in targets.loose_rows.values() if row.is_void]
    BankTransaction.objects.filter(pk__in=changed_rows).update(is_void=False, voided_at=None, updated_at=now)

    linked = list(BankTransaction.objects.filter(journal_entry_id__in=changed_entries).values_list("pk", flat=True))
    return changed_entries, sorted({*changed_rows, *linked})


def inconsistent_rows(book=None):
    """Bank rows whose void flag disagrees with their entry's status."""
    rows = BankTransaction.objects.filter(journal_entry__isnull=False)
    if book is not None:
        rows = rows.filter(book=book)
    return rows.filter(is_void=True).exclude(journal_entry__status=JournalEntry.STATUS_VOID) | rows.filter(
        is_void=False, journal_entry__status=JournalEntry.STATUS_VOID
    )


def assert_consistent(book=None):
    """Raise AssertionError naming the first few rows that break the invariant."""
    bad = list(inconsistent_rows(book).values_list("pk", flat=True)[:10])
    if bad:
        raise AssertionError(f"Bank rows out of step with their entry's void state: {bad}")
