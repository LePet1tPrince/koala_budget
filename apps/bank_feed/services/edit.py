"""
Field edits on one feed transaction: category, account, payee, description, date.

The writes behind the feed's Bulk Edit, and the ones a transaction rule makes
(`apps.rules`), in one place. `refusal` says why an edit cannot apply to a row
before anything is written; `apply_fields` writes it. Neither opens its own
check of period locks: callers ask `period_lock.row_refusal` alongside `refusal`,
because the batch endpoint names every refused row at once.

`update_row` is the feed API's whole-row edit (the transaction modal's Save):
every field and the categorization at once, checked before anything is written.

`decategorize` is the one way back to "uncategorized" for a feed row.
"""

from django.db import transaction
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from apps.accounts.guards import assert_category_allowed
from apps.accounts.models import Payee
from apps.journal.models import JournalEntry
from apps.journal.services import period_lock
from apps.journal.services.lines import repoint_line
from apps.reconciliation.services.guards import (
    ReconciledLineError,
    assert_date_change_allowed,
    assert_entry_removable,
    assert_line_mutable,
)
from apps.utils.errors import Refused

from ..models import VOID_ROW_MESSAGE, BankTransaction, VoidRowError
from .categorize import MIRROR_EDIT_ERROR, create_entry, repoint_category
from .splits import apply_splits, check_legs_total, is_split, parse_legs
from .transfer_mirror import is_split_mirror, sync_transfer, would_orphan_primary

VOID_EDIT_ERROR = "This transaction is void. Restore it before editing it."
SPLIT_MIRROR_ERROR = "This is one part of a split transaction in another account. Open the split there to change it."
RECONCILED_DECATEGORIZE_ERROR = "This transaction is reconciled. Unreconcile it before removing its category."
RECONCILED_AMOUNT_ERROR = "This transaction is reconciled. Unreconcile it before changing its amount."
SPLIT_NOT_SENT_ERROR = "This transaction is split across categories. Send its splits, or remove the split first."


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


def update_row(tx, *, account, category, splits, remove_split, amount, date, payee_name, description):
    """
    Replace `tx`'s account, signed `amount`, date, payee, description and
    categorization.

    `category` None with no `splits` leaves the row uncategorized; `splits` is the
    raw leg list `parse_legs` reads. Every rule is checked before anything is
    written; a broken one raises `Refused` saying what to do instead.
    """
    entry = tx.journal_entry
    # A category the entry already uses stays allowed even if it is a system one,
    # so re-saving an adjustment untouched keeps working.
    lines = entry.lines.all() if entry else ()
    current_ids = {line.account_id for line in lines if line.account_id != tx.account_id}
    reconciled = entry is not None and entry.lines.filter(account=tx.account, is_reconciled=True).exists()
    decategorizes = category is None and splits is None

    # A void row counts toward nothing; editing it would change what the user
    # restores later without them seeing it.
    if tx.is_void:
        raise Refused(VOID_EDIT_ERROR)
    if category is not None:
        assert_category_allowed(category, keep_ids=current_ids)
    # A split's transfer leg shows here as a mirror row; editing it would rewrite
    # a split the user made in the other account.
    if is_split_mirror(tx):
        raise Refused(SPLIT_MIRROR_ERROR)
    # Re-pointing (or clearing) a mirror leg's category would orphan the primary.
    if would_orphan_primary(tx, category):
        raise Refused(MIRROR_EDIT_ERROR)
    # Dropping the category takes confirmed history out of the ledger. Splits
    # re-apportion rather than decategorize, so they pass.
    if decategorizes and reconciled:
        raise Refused(RECONCILED_DECATEGORIZE_ERROR)

    legs = None
    if splits is not None:
        legs = parse_legs(splits, keep_ids=current_ids)
        check_legs_total(legs, total=amount)
    # An existing split is sent with its legs or explicitly collapsed: folding it
    # silently into one category would lose the user's apportionment.
    if legs is None and category is not None and not remove_split and is_split(entry):
        raise Refused(SPLIT_NOT_SENT_ERROR)
    # Reconciliation is a fact about the bank line: re-splitting keeps its amount
    # and is allowed; changing the total is not.
    if reconciled and amount != tx.amount:
        raise Refused(RECONCILED_AMOUNT_ERROR)

    # The rest of what can change a reconciled line: a move, a re-date past its
    # statement, or dropping a transfer's other side. `apply_splits` guards legs.
    if entry is not None:
        if account.id != tx.account_id:
            for line in entry.lines.filter(account=tx.account):
                assert_line_mutable(line, new_account=account)
        assert_date_change_allowed(entry, date)
        if decategorizes:
            assert_entry_removable(entry, own_account_id=tx.account_id, verb=gettext("removing its category"))
    period_lock.assert_row_edit_allowed(tx, book=tx.book, new_date=date, categorizes=not decategorizes)

    payee = payee_for(tx.book, payee_name)
    with transaction.atomic():
        # The bank line is found by the row's *current* account, so the old one is
        # kept to re-point its lines after the move.
        old_account = tx.account
        tx.account = account
        tx.amount = amount
        tx.posted_date = date
        tx.description = description
        tx.merchant_name = payee_name
        tx.save()

        # `apply_splits` writes the lines in every case -- one category is a split
        # with one leg -- so one place decides each line's side and checks balance.
        entry_legs = legs if legs is not None else [(category, amount)]
        if decategorizes:
            if entry is not None:
                decategorize(tx)
        elif entry is not None:
            entry.entry_date = date
            entry.description = description
            entry.payee = payee
            entry.save()
            # Re-pointed one save at a time, so the audit signals fire.
            moved = entry.lines.filter(account=old_account) if old_account != account else ()
            apply_splits(tx, entry_legs, total=amount, move_lines=moved)
        else:
            tx.journal_entry = JournalEntry.objects.create(
                book=tx.book,
                entry_date=date,
                description=description,
                payee=payee,
                source=JournalEntry.SOURCE_MANUAL,
                status=JournalEntry.STATUS_POSTED,
            )
            tx.save()
            apply_splits(tx, entry_legs, total=amount)

        # Moves, creates or removes a transfer's counterpart leg to match.
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


def uncategorize_refusal(tx):
    """
    Why `tx` cannot go back to uncategorized, or None. An uncategorized row has
    nothing to take back and is never refused.
    """
    if tx.is_void:
        return VOID_EDIT_ERROR
    if is_split_mirror(tx):
        return SPLIT_MIRROR_ERROR
    if tx.is_transfer_mirror:
        return MIRROR_EDIT_ERROR
    if tx.journal_entry_id is None:
        return None
    try:
        assert_entry_removable(tx.journal_entry, own_account_id=tx.account_id, verb=gettext("removing its category"))
    except ReconciledLineError as exc:
        return str(exc)
    return period_lock.row_refusal(tx, book=tx.book)


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
