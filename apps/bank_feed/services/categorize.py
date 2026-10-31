"""
Give a feed transaction a single category.

The one write path for "this bank transaction is <category>": create its journal
entry the first time, re-point its category line after that, and keep a transfer's
mirror leg in step either way. Used by the feed's categorize and batch-edit
endpoints, CSV import and transfer matching. The lines themselves are written by
`apps.journal.services.lines.write_lines`, like every other transaction's.
"""

from django.db import transaction

from apps.journal.models import JournalEntry
from apps.journal.services import period_lock
from apps.journal.services.lines import signed_amount, write_lines

from ..models import VOID_ROW_MESSAGE, VoidRowError
from .splits import SplitError, is_split
from .transfer_mirror import sync_transfer, would_orphan_primary

MIRROR_EDIT_ERROR = "This is the mirror side of a transfer. Edit the original transaction to change its category."


@transaction.atomic
def categorize_single(bank_tx, category_account):
    """Categorize `bank_tx` to `category_account`, creating or re-pointing its entry."""
    if bank_tx.journal_entry_id:
        repoint_category(bank_tx, category_account)
        return bank_tx.journal_entry
    return create_entry(bank_tx, category_account)


@transaction.atomic
def create_entry(bank_tx, category_account):
    """
    Create the journal entry for an uncategorized feed transaction and link it.

    Raises ValueError when the transaction has no account.
    """
    if not bank_tx.account_id:
        raise ValueError("Cannot categorize transaction: No bank account linked.")
    if bank_tx.is_void:
        raise VoidRowError(VOID_ROW_MESSAGE)

    book = bank_tx.book
    period_lock.assert_date_open(book, bank_tx.posted_date)
    journal_entry = JournalEntry.objects.create(
        book=book,
        entry_date=bank_tx.posted_date,
        description=bank_tx.description,
        source=bank_tx.journal_source,
        status=JournalEntry.STATUS_POSTED,
    )

    # One leg carrying the whole amount. The writer puts the bank line on the
    # opposite side (Plaid convention: positive = outflow), so money in debits the
    # bank account and credits the category; money out is the reverse.
    write_lines(
        journal_entry,
        bank_tx.account_id,
        [(category_account, bank_tx.amount)],
        total=bank_tx.amount,
        book=book,
        lines=[],
    )

    bank_tx.journal_entry = journal_entry
    bank_tx.save()

    # If this is a transfer to another feed account, surface the counterpart leg
    # in that account's feed (linked to this same entry).
    sync_transfer(bank_tx)
    return journal_entry


@transaction.atomic
def repoint_category(bank_tx, category_account):
    """Move the category line of an already-categorized feed transaction."""
    if bank_tx.is_void:
        raise VoidRowError(VOID_ROW_MESSAGE)
    # Re-pointing the mirror leg to a non-feed category would orphan the real
    # primary transaction; reject it (the user must edit the original instead).
    if would_orphan_primary(bank_tx, category_account):
        raise ValueError(MIRROR_EDIT_ERROR)

    # A split has several category lines, and this re-points one. Doing that to a
    # split would leave the other legs alone -- balanced, and quietly not what the
    # user apportioned. Collapsing a split is a real action, but it has to be asked
    # for in the editor, not implied by a bulk categorize.
    if is_split(bank_tx.journal_entry):
        raise SplitError("This is a split transaction. Open it to edit its categories, or remove the split first.")
    period_lock.assert_entry_mutable(bank_tx.journal_entry)

    # On a transfer the category line is the other feed's bank line, so it is
    # re-pointed in place (`repoint=True`) rather than replaced: it keeps that
    # feed's flags, and the writer refuses to move it if it is reconciled.
    entry = bank_tx.journal_entry
    lines = list(entry.lines.all())
    category_line = next((line for line in lines if line.account_id != bank_tx.account_id), None)
    if category_line is not None:
        amount = signed_amount(category_line)
        write_lines(
            entry,
            bank_tx.account_id,
            [(category_account, amount)],
            total=amount,
            book=bank_tx.book,
            repoint=True,
            lines=lines,
        )

    # The category drives whether this is a transfer: add/move/remove the
    # counterpart leg (and move the primary if the mirror was re-pointed).
    sync_transfer(bank_tx)
