"""
The rule that keeps a closed period closed.

A set of books can be closed through a date (`Book.locked_through`): an HST return
was filed, a year was closed. From then on no *transaction* dated on or before that
day may be created, edited, re-dated, deleted, voided or restored, and none may be
moved into the closed period. An admin reopens it by clearing or moving the date
in the book's settings.

Every write path asks these functions first -- the Transactions page
(`simple_edit`), voiding, the journal API, the bank feed (categorize, edit, batch
edit, delete, splits), reconciliation adjustments and opening balances -- so the
rule and its wording live here once, as `apps.reconciliation.services.guards`
does for reconciled lines. The models carry a backstop (`JournalEntry.save()` /
`delete()`, `JournalLine.save()` / `delete()` call the `check_*` functions below)
so a path that forgets to ask still cannot write into a closed period; the
explicit calls are what give the user a good message before anything is written.

Decisions, each deliberate:

- **Budget entries are not locked** (`JournalEntry.SOURCE_BUDGET`, written only by
  `apps.budget.ledger`). They move money between budget buckets and no balance,
  report or return reads them, so a past month's budget stays editable after the
  period it budgeted is closed.
- **Uncategorized bank rows are not entries.** Plaid and CSV may still deliver a
  row dated in a closed period, it may be edited, voided, deleted or duplicated
  (a copy is uncategorized), but it cannot be *categorized* there, because that
  creates an entry.
- **Flags are not edits.** Ticking, finishing a statement without an adjustment,
  or unreconciling a line in a closed period changes no amount, account or date,
  so it is allowed. A statement whose adjustment would be posted in the closed
  period is refused, and so is undoing one whose adjustment is there.
- **The bank revising a closed transaction** (`bank_revision.revise`) is treated
  like a reconciled one: the row keeps its date and amount, and the difference
  arrives as its own uncategorized row, dated on the first open day
  (`first_open_date`) so it can be categorized.
- **Bulk importers that build a whole book are exempt** (`exempt()`): the YNAB
  import and the export loader (`apps.portability`) write a book from scratch,
  and the portability import *replaces* one -- an admin-only action with a typed
  confirmation and a safety export.

`PeriodLockedError` subclasses ValueError because the feed's endpoints already
turn a ValueError into a 400; its message is the sentence the user sees.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from django.utils.formats import date_format
from django.utils.translation import gettext as _

_EXEMPT = ContextVar("period_lock_exempt", default=False)


class PeriodLockedError(ValueError):
    """A write that would change a transaction in a closed period."""


@contextmanager
def exempt():
    """Switch the lock off for a bulk import that builds a whole book. Usable as a decorator."""
    token = _EXEMPT.set(True)
    try:
        yield
    finally:
        _EXEMPT.reset(token)


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def lock_date(book):
    """The last closed day, or None when nothing is closed (or the lock is exempted)."""
    if book is None or _EXEMPT.get():
        return None
    return book.locked_through


def is_locked(book, day) -> bool:
    """Whether `day` falls in `book`'s closed period."""
    lock = lock_date(book)
    return lock is not None and day is not None and day <= lock


def _is_budget(entry) -> bool:
    from apps.journal.models import JournalEntry

    return entry.source == JournalEntry.SOURCE_BUDGET


def _book(entry, book):
    return book if book is not None else entry.book


def entry_is_locked(entry, *, book=None) -> bool:
    """Whether `entry` sits in the closed period (a budget entry never does)."""
    if entry is None or _is_budget(entry):
        return False
    book = _book(entry, book)
    loaded = getattr(entry, "_loaded_lock_state", None) or {}
    # The date it was read with counts too: an entry re-dated in memory is still
    # the closed period's until it is saved somewhere else -- which is refused.
    return is_locked(book, entry.entry_date) or is_locked(book, loaded.get("entry_date"))


def first_open_date(book, day):
    """`day`, or the first day after the closed period when `day` is inside it."""
    lock = lock_date(book)
    if lock is None or day > lock:
        return day
    return lock + timedelta(days=1)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _date(book):
    return date_format(book.locked_through, "DATE_FORMAT")


def entry_locked_message(book) -> str:
    return _(
        "This transaction is in a closed period: this set of books is closed through %(date)s. "
        "An admin can reopen it in the book's settings."
    ) % {"date": _date(book)}


def date_locked_message(book) -> str:
    return _(
        "This set of books is closed through %(date)s, so a transaction can't be dated on or before then. "
        "An admin can change that in the book's settings."
    ) % {"date": _date(book)}


def lock_reason(entry, *, book=None):
    """Why `entry` can't be changed, or None. What the edit modal shows."""
    if not entry_is_locked(entry, book=book):
        return None
    return entry_locked_message(_book(entry, book))


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def assert_date_open(book, day):
    """Refuse a new transaction (or a move) onto `day` when it is in the closed period."""
    if is_locked(book, day):
        raise PeriodLockedError(date_locked_message(book))


def assert_entry_mutable(entry, *, book=None):
    """Refuse any change to an entry in the closed period: edit, delete, void, restore."""
    if entry_is_locked(entry, book=book):
        raise PeriodLockedError(entry_locked_message(_book(entry, book)))


def assert_redate_allowed(entry, new_date, *, book=None):
    """Refuse moving an entry out of the closed period, or into it."""
    if entry is None or new_date is None or _is_budget(entry):
        return
    assert_entry_mutable(entry, book=book)
    assert_date_open(_book(entry, book), new_date)


def row_refusal(bank_tx, *, book, new_date=None, categorizes=False):
    """
    Why an edit to feed row `bank_tx` would touch the closed period, or None.

    A categorized row stands for its entry: any edit changes the entry, so a closed
    entry refuses it, and so does a new date inside the closed period. An
    uncategorized row is not an entry: it is refused only when the edit gives it a
    category (`categorizes`), which creates one on its (new) date.
    """
    if lock_date(book) is None:
        return None
    entry = bank_tx.journal_entry if bank_tx.journal_entry_id else None
    if entry is not None:
        if entry_is_locked(entry, book=book):
            return entry_locked_message(book)
        if is_locked(book, new_date):
            return date_locked_message(book)
        return None
    if categorizes and is_locked(book, new_date or bank_tx.posted_date):
        return date_locked_message(book)
    return None


def assert_row_edit_allowed(bank_tx, *, book, new_date=None, categorizes=False):
    """`row_refusal`, raised."""
    error = row_refusal(bank_tx, book=book, new_date=new_date, categorizes=categorizes)
    if error:
        raise PeriodLockedError(error)


def refused_rows(rows, *, book, new_date=None, categorizes=False):
    """`row_refusal` over many rows, in the `refused` shape the feed's batch endpoints answer with."""
    refused = []
    for row in rows:
        error = row_refusal(row, book=book, new_date=new_date, categorizes=categorizes)
        if error:
            refused.append({"kind": "row", "id": row.pk, "error": error})
    return refused


# ---------------------------------------------------------------------------
# Model backstops
# ---------------------------------------------------------------------------

#: The fields whose change is an edit of the transaction (not of its bookkeeping flags).
ENTRY_FIELDS = ("entry_date", "payee_id", "description", "status", "source")
LINE_FIELDS = ("account_id", "dr_amount", "cr_amount", "journal_entry_id")


def snapshot(instance, fields):
    """What `instance` was read (or last saved) with, for the backstops to compare against."""
    return {name: instance.__dict__.get(name) for name in fields}


def _changed(instance, fields) -> bool:
    loaded = getattr(instance, "_loaded_lock_state", None)
    if loaded is None:
        return True
    return any(loaded.get(name) != getattr(instance, name) for name in fields)


def check_entry_save(entry):
    """`JournalEntry.save()`'s backstop: no new entry, and no change to one, in the closed period."""
    if _is_budget(entry) or lock_date(entry.book) is None:
        return
    if entry._state.adding:
        assert_date_open(entry.book, entry.entry_date)
        return
    if not _changed(entry, ENTRY_FIELDS):
        return
    loaded = getattr(entry, "_loaded_lock_state", None) or {}
    if is_locked(entry.book, loaded.get("entry_date")):
        raise PeriodLockedError(entry_locked_message(entry.book))
    assert_date_open(entry.book, entry.entry_date)


def check_entry_delete(entry):
    """`JournalEntry.delete()`'s backstop."""
    assert_entry_mutable(entry)


def check_line_save(line):
    """`JournalLine.save()`'s backstop: a line's account and amount don't change in the closed period."""
    entry = line.journal_entry
    if _is_budget(entry) or lock_date(entry.book) is None:
        return
    if not line._state.adding and not _changed(line, LINE_FIELDS):
        return  # a flag (is_reconciled, is_cleared, its statement) changed, nothing else
    assert_entry_mutable(entry)


def check_line_delete(line):
    """`JournalLine.delete()`'s backstop."""
    assert_entry_mutable(line.journal_entry)
