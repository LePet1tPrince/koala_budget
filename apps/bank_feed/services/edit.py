"""
Field edits on one feed transaction: category, account, payee, description, date.

The writes behind the feed's Bulk Edit, and the ones a transaction rule makes
(`apps.rules`), in one place. `refusal` says why an edit cannot apply to a row
before anything is written; `apply_fields` writes it. Neither opens its own
check of period locks: callers ask `period_lock.row_refusal` alongside `refusal`,
because the batch endpoint names every refused row at once.

`decategorize` is the one way back to "uncategorized" for a feed row.
"""

from django.db import transaction
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Payee
from apps.journal.models import JournalEntry
from apps.journal.services import period_lock
from apps.journal.services.lines import repoint_line
from apps.reconciliation.services.guards import ReconciledLineError, assert_date_change_allowed, assert_entry_removable

from ..models import VOID_ROW_MESSAGE, BankTransaction, VoidRowError
from .categorize import MIRROR_EDIT_ERROR, create_entry, repoint_category
from .splits import apply_splits, is_split
from .transfer_mirror import is_split_mirror, sync_transfer, would_orphan_primary

VOID_EDIT_ERROR = "This transaction is void. Restore it before editing it."
SPLIT_MIRROR_ERROR = "This is one part of a split transaction in another account. Open the split there to change it."


def refusal(tx, *, category=None, target_account=None, new_date=None):
    """Why these field edits cannot apply to `tx`, or None."""
    if tx.is_void:
        return VOID_EDIT_ERROR
    # A split's transfer-leg mirror is part of a split in another account; no
    # field (date, payee, account, category) can be edited on it alone.
    if is_split_mirror(tx):
        return SPLIT_MIRROR_ERROR
    home = target_account or tx.account
    if category is not None:
        # Re-pointing a mirror leg to a non-feed category would orphan the real
        # primary; a split has no single category line to re-point.
        if would_orphan_primary(tx, category):
            return MIRROR_EDIT_ERROR
        if is_split(tx.journal_entry):
            return _("This transaction is split across categories. Open it to edit its categories.")
        if category.id == home.id:
            return _("A transaction cannot be categorized to the account it is in.")
    elif target_account is not None and tx.journal_entry_id:
        # Moving a row into the account its category already is would put both
        # sides of the entry on one account: a transfer to itself.
        others = [line for line in tx.journal_entry.lines.all() if line.account_id != tx.account_id]
        if len(others) == 1 and others[0].account_id == target_account.id:
            return _("A transaction cannot be moved to the account it is categorized to.")
    if new_date is not None:
        try:
            assert_date_change_allowed(tx.journal_entry, new_date)
        except ReconciledLineError as e:
            return str(e)
    return None


def payee_for(book, payee_name):
    """The book's Payee called `payee_name`, made if missing. A blank name is no payee."""
    if not payee_name:
        return None
    payee, _created = Payee.objects.get_or_create(book=book, name=payee_name)
    return payee


@transaction.atomic
def apply_fields(
    tx,
    *,
    category=None,
    target_account=None,
    payee_name=None,
    payee=None,
    description=None,
    new_date=None,
):
    """
    Write the given fields to `tx` (and its journal entry, when it has one).

    A field left as None is untouched. `payee_name=""` clears the payee; pass the
    resolved `payee` to avoid a lookup per row in a batch.
    """
    # --- Category ---
    if category is not None:
        if tx.journal_entry_id:
            repoint_category(tx, category)
        else:
            create_entry(tx, category)
            tx.refresh_from_db()

    # --- Move account ---
    if target_account is not None:
        # Reconciled transactions cannot be moved to another account
        is_reconciled = (
            tx.journal_entry and tx.journal_entry.lines.filter(account=tx.account, is_reconciled=True).exists()
        )
        if not is_reconciled:
            old_account = tx.account
            tx.account = target_account
            if tx.journal_entry:
                lines = tx.journal_entry.lines.all()
                home = next((line for line in lines if line.account == old_account), None)
                if home is not None:
                    repoint_line(home, target_account)

    # --- Payee ---
    if payee_name is not None:
        if payee is None and payee_name:
            payee = payee_for(tx.book, payee_name)
        tx.merchant_name = payee_name
        if tx.journal_entry:
            tx.journal_entry.payee = payee
            tx.journal_entry.save()

    # --- Description ---
    if description is not None:
        tx.description = description
        if tx.journal_entry:
            tx.journal_entry.description = description
            tx.journal_entry.save()

    # --- Date ---
    if new_date is not None:
        tx.posted_date = new_date
        if tx.journal_entry:
            tx.journal_entry.entry_date = new_date
            tx.journal_entry.save()

    tx.save()

    # Keep a transfer's counterpart leg aligned with any date/payee/desc edit.
    sync_transfer(tx)


@transaction.atomic
def create_split_entry(tx, legs, *, payee=None):
    """
    Give an uncategorized feed row a journal entry with several category legs.

    `legs` are (category account, signed amount) pairs summing to the row's
    amount, validated by the caller. Raises `period_lock.PeriodLockedError` and
    `VoidRowError` like `categorize.create_entry`.
    """
    if tx.is_void:
        raise VoidRowError(VOID_ROW_MESSAGE)
    period_lock.assert_date_open(tx.book, tx.posted_date)
    tx.journal_entry = JournalEntry.objects.create(
        book=tx.book,
        entry_date=tx.posted_date,
        description=tx.description,
        payee=payee,
        source=tx.journal_source,
        status=JournalEntry.STATUS_POSTED,
    )
    tx.save()
    apply_splits(tx, legs, total=tx.amount)
    sync_transfer(tx)
    return tx.journal_entry


@transaction.atomic
def decategorize(bank_tx):
    """
    Remove a transaction's categorization: unlink and delete its journal entry
    (and any auto-created transfer mirror leg sharing it). The BankTransaction
    stays in the feed as an uncategorized row.
    """
    entry = bank_tx.journal_entry
    if entry is None:
        return
    assert_entry_removable(entry, own_account_id=bank_tx.account_id, verb=gettext("removing its category"))
    period_lock.assert_entry_mutable(entry, book=bank_tx.book)

    # A transfer's counterpart mirror leg only exists to surface the shared
    # entry in the other feed; drop it so it doesn't linger as an orphan.
    for leg in BankTransaction.objects.filter(journal_entry=entry).exclude(id=bank_tx.id):
        if leg.is_transfer_mirror:
            leg.delete()

    bank_tx.journal_entry = None
    bank_tx.save(update_fields=["journal_entry", "updated_at"])
    entry.delete()
