"""
The Inbox's batch bar: what happens to a selection of feed rows.

Each function takes the book and the selected ids, checks every row before it
writes any -- a batch is all or nothing -- and answers what it changed, so the
view only has to log the audit event and answer. A refusal is a `FeedError`, or
`RowsRefused` naming each row that blocked the batch (`voiding.VoidRefused` does
the same for void and restore).
"""

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.accounts.guards import assert_category_allowed
from apps.accounts.models import Account, Payee
from apps.journal.models import JournalEntry
from apps.journal.services import voiding
from apps.reconciliation.services.guards import ReconciledLineError, assert_date_change_allowed

from ..models import BankTransaction
from .categorize import MIRROR_EDIT_ERROR, create_entry, repoint_category
from .errors import FeedError, RowsRefused
from .manual import SPLIT_MIRROR_ERROR, VOID_EDIT_ERROR
from .splits import is_split
from .transfer_mirror import is_split_mirror, sync_transfer, would_orphan_primary


def categorize(book, tx_ids, category_id):
    """
    Give every row in `tx_ids` the category `category_id`: a new entry for an
    uncategorized row, a re-pointed category line for a categorized one. Answers
    how many rows it categorized.
    """
    try:
        category_account = Account.objects.get(book=book, id=category_id)
    except Account.DoesNotExist:
        raise FeedError.not_found("Category account not found") from None
    try:
        assert_category_allowed(category_account)
    except ValueError as e:
        raise FeedError(str(e)) from None

    # Resolve all transactions up front so a bad id can't partially apply the batch
    transactions = list(
        BankTransaction.objects.select_related("account", "journal_entry").filter(id__in=tx_ids, book=book)
    )
    if len(transactions) != len(tx_ids):
        raise FeedError.not_found("One or more transactions not found")

    try:
        with transaction.atomic():
            for bank_tx in transactions:
                if bank_tx.journal_entry:
                    # Already categorized: move the category line instead of
                    # creating a duplicate journal entry
                    repoint_category(bank_tx, category_account)
                else:
                    create_entry(_fresh(book, bank_tx), category_account)
    except ValueError as e:
        raise FeedError(str(e)) from None
    return len(transactions)


def edit(book, ids, *, category_id=None, account_id=None, payee=None, description=None, date=None):
    """
    Bulk edit: only the fields given (not None) change. `account_id` moves the
    rows to another feed account; a blank `payee` clears the entry's payee.
    """
    # Validate referenced objects up front
    category_account = None
    if category_id is not None:
        try:
            category_account = Account.objects.get(book=book, id=category_id)
        except Account.DoesNotExist:
            raise FeedError.not_found("Category account not found") from None
        try:
            assert_category_allowed(category_account)
        except ValueError as e:
            raise FeedError(str(e)) from None

    target_account = None
    if account_id is not None:
        try:
            target_account = Account.objects.get(book=book, id=account_id)
        except Account.DoesNotExist:
            raise FeedError.not_found("Target account not found") from None
        if not target_account.has_feed:
            raise FeedError("Target account must have bank feed enabled")

    # A blank payee is how the caller clears one, so it must not create a
    # nameless Payee row — the entry's payee is unset instead.
    payee_obj = None
    if payee:
        payee_obj, _created = Payee.objects.get_or_create(book=book, name=payee)

    transactions = list(
        BankTransaction.objects.filter(id__in=ids, book=book)
        .select_related("account", "journal_entry")
        .prefetch_related("journal_entry__lines")
    )

    # A transfer's mirror leg follows its original. With both legs selected,
    # re-categorizing the mirror as well would be the same transfer twice (or
    # refused outright), so the mirror is left to `sync_transfer`.
    if category_account is not None:
        primaries = {tx.journal_entry_id for tx in transactions if tx.journal_entry_id and not tx.is_transfer_mirror}
        transactions = [tx for tx in transactions if not (tx.is_transfer_mirror and tx.journal_entry_id in primaries)]

    # Every row is checked before any is written, and every refusal is named,
    # so a selection spanning several accounts says which rows to deselect.
    refused = []
    for tx in transactions:
        error = edit_refusal(tx, category_account, target_account, date)
        if error:
            refused.append({"kind": "row", "id": tx.id, "error": str(error)})
    if refused:
        raise RowsRefused(refused)

    try:
        _apply_edit(book, transactions, category_account, target_account, payee, payee_obj, description, date)
    except ValueError as e:
        # Raised inside the atomic block, so nothing in the batch was written.
        raise FeedError(str(e)) from None


def edit_refusal(tx, category_account, target_account, new_date):
    """Why `edit` cannot apply to `tx`, or None."""
    if tx.is_void:
        return VOID_EDIT_ERROR
    # A split's transfer-leg mirror is part of a split in another account; no
    # batch field (date, payee, account, category) can be edited on it alone.
    if is_split_mirror(tx):
        return SPLIT_MIRROR_ERROR
    home = target_account or tx.account
    if category_account is not None:
        # Re-pointing a mirror leg to a non-feed category would orphan the real
        # primary; a split has no single category line to re-point.
        if would_orphan_primary(tx, category_account):
            return MIRROR_EDIT_ERROR
        if is_split(tx.journal_entry):
            return _("This transaction is split across categories. Open it to edit its categories.")
        if category_account.id == home.id:
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


@transaction.atomic
def _apply_edit(book, transactions, category_account, target_account, payee_name, payee_obj, description, new_date):
    """The writes behind `edit`, in one transaction so a refusal rolls back the whole batch."""
    for tx in transactions:
        # --- Category ---
        if category_account is not None:
            if tx.journal_entry:
                repoint_category(tx, category_account)
            else:
                create_entry(_fresh(book, tx), category_account)
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
                    for line in tx.journal_entry.lines.all():
                        if line.account == old_account:
                            line.account = target_account
                            line.save()
                            break

        # --- Payee ---
        if payee_name is not None:
            tx.merchant_name = payee_name
            if tx.journal_entry:
                tx.journal_entry.payee = payee_obj
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


def set_void(book, ids, *, restore=False):
    """
    Void (or restore) the selected rows with their entries -- a transfer's other
    leg too -- through `voiding`, the one writer of void state. Answers the rows
    whose state changed; raises `voiding.VoidRefused` naming any blocking row.
    """
    rows = list(BankTransaction.objects.filter(id__in=ids, book=book).select_related("journal_entry"))
    operation = voiding.restore if restore else voiding.void
    _entries, changed_rows = operation(rows=rows)
    return changed_rows


def delete_void(book, ids):
    """
    Permanently delete the selected void rows and their journal entries. Rows
    that aren't void are left alone.
    """
    selected = list(BankTransaction.objects.filter(id__in=ids, book=book, is_void=True).select_related("journal_entry"))
    journal_entry_ids = [tx.journal_entry_id for tx in selected if tx.journal_entry_id]

    # Delete both legs of any transfer being removed (the mirror leg may not be
    # selected), then any selected rows without an entry.
    if journal_entry_ids:
        BankTransaction.objects.filter(journal_entry_id__in=journal_entry_ids).delete()
    BankTransaction.objects.filter(id__in=[tx.id for tx in selected]).delete()

    if journal_entry_ids:
        JournalEntry.objects.filter(id__in=journal_entry_ids).delete()


def duplicate(book, ids):
    """
    Copy the selected rows as new uncategorized manual rows in their own accounts,
    answering the copies. Reconciled rows are not copied, and a transfer with both
    legs selected is copied once.
    """
    selected = list(
        BankTransaction.objects.filter(id__in=ids, book=book)
        .select_related("account")
        .prefetch_related("journal_entry__lines")
    )

    def reconciled(tx):
        lines = tx.journal_entry.lines.all() if tx.journal_entry else ()
        return any(line.account_id == tx.account_id and line.is_reconciled for line in lines)

    # With both legs of a transfer selected, copy the transfer once, from its
    # primary: copying the mirror too would make a second copy of the same
    # movement. A mirror selected on its own is copied like any other row.
    primary_entries = {tx.journal_entry_id for tx in selected if tx.journal_entry_id and not tx.is_transfer_mirror}
    transactions = [
        tx
        for tx in selected
        if not (tx.is_transfer_mirror and tx.journal_entry_id in primary_entries) and not reconciled(tx)
    ]

    return [
        BankTransaction.objects.create(
            book=book,
            account=tx.account,
            amount=tx.amount,
            posted_date=tx.posted_date,
            description=tx.description,
            merchant_name=tx.merchant_name,
            source=BankTransaction.SOURCE_MANUAL,
            raw={"duplicated_from": tx.id},
            journal_entry=None,
        )
        for tx in transactions
    ]


def unreconcile(book, ids):
    """Unreconcile each selected row: the journal line on its own account."""
    for tx in BankTransaction.objects.filter(id__in=ids, book=book).select_related("account", "journal_entry"):
        if tx.journal_entry:
            for line in tx.journal_entry.lines.all():
                if line.account == tx.account:
                    line.is_reconciled = False
                    line.save()
                    break


def _fresh(book, bank_tx):
    """`bank_tx` read again: an earlier row in the batch may have changed it (a transfer's other leg)."""
    return BankTransaction.objects.select_related("account").get(id=bank_tx.id, book=book)
