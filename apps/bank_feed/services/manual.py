"""
Add or edit one feed transaction by hand: the Inbox's Add Transaction and edit modal.

A transaction keeps its own bank row (`BankTransaction`), and once it has a category
-- or several, when split -- a journal entry behind it. `create_transaction` and
`update_transaction` decide every rule about that (which account, which category,
whether a split may be dropped, what reconciliation forbids) and then hand the lines
to `splits.apply_splits`, the one place that decides which side of a line an amount
lands on. Every refusal is a `FeedError` raised before anything is written.

Amounts follow Plaid's convention: positive = outflow, negative = inflow.
"""

from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext

from apps.accounts.guards import assert_category_allowed
from apps.accounts.models import Account, Payee
from apps.journal.models import JournalEntry, JournalLine
from apps.reconciliation.services.guards import (
    ReconciledLineError,
    assert_date_change_allowed,
    assert_entry_removable,
    assert_line_mutable,
)

from ..models import BankTransaction
from .categorize import MIRROR_EDIT_ERROR, decategorize
from .errors import FeedError
from .splits import SplitError, apply_splits, check_legs_total, is_split, parse_legs
from .transfer_mirror import is_split_mirror, sync_transfer, would_orphan_primary

VOID_EDIT_ERROR = "This transaction is void. Restore it before editing it."
# A split's transfer leg is mirrored into the other account's feed; that row is
# part of the split and is edited from the split's own row.
SPLIT_MIRROR_ERROR = "This is one part of a split transaction in another account. Open the split there to change it."


def editable_transaction(book, pk):
    """The feed row `pk` in `book`, if it may be edited at all. Raises `FeedError`."""
    try:
        bank_tx = BankTransaction.objects.select_related("account", "journal_entry").get(id=pk, book=book)
    except BankTransaction.DoesNotExist:
        raise FeedError.not_found("Transaction not found") from None
    # A void transaction counts toward nothing; editing it would change what
    # the user restores later without them seeing it. Restore first.
    if bank_tx.is_void:
        raise FeedError(VOID_EDIT_ERROR)
    return bank_tx


def create_transaction(
    book, *, account_id, date, category_id=None, inflow=None, outflow=None, payee="", description="", splits=None
):
    """
    Add a transaction to `account_id`'s feed, categorized when a category or
    splits are given and uncategorized (no journal entry) otherwise.
    """
    bank_account = _account(book, account_id, "Bank account not found")

    # Category is optional — a blank category creates an uncategorized transaction
    # (no journal entry) that the user can categorize later.
    category_account = None
    if category_id is not None:
        category_account = _category(book, category_id)

    amount = _amount(inflow, outflow)
    # Split legs, when the client sent them. Validated before anything is
    # written, so a bad payload never opens a transaction.
    legs = _legs(splits, amount)
    payee_obj = _payee(book, payee)

    with transaction.atomic():
        # Only categorized transactions get a journal entry; a blank category
        # and no splits leave the transaction uncategorized (journal_entry=None).
        journal_entry = None
        entry_legs = legs if legs is not None else ([(category_account, amount)] if category_account else None)
        if entry_legs is not None:
            journal_entry = _new_entry(book, bank_account, date, description, payee_obj)

        bank_tx = BankTransaction.objects.create(
            book=book,
            account=bank_account,
            amount=amount,
            posted_date=date,
            description=description,
            merchant_name=payee,
            source=BankTransaction.SOURCE_MANUAL,
            journal_entry=journal_entry,
        )

        if entry_legs is not None:
            apply_splits(bank_tx, entry_legs, total=amount)

        # Mirror the leg into the counterpart account's feed if it's a transfer.
        # (No-op for an uncategorized transaction with no journal entry.)
        sync_transfer(bank_tx)
    return bank_tx


def update_transaction(
    book,
    bank_tx,
    *,
    account_id,
    date,
    category_id=None,
    inflow=None,
    outflow=None,
    payee="",
    description="",
    splits=None,
    remove_split=False,
):
    """
    Rewrite `bank_tx` (from `editable_transaction`) and its journal entry.

    A blank category with no splits de-categorizes it; a category or splits
    create, re-point or re-apportion its entry. Answers the row reloaded.
    """
    bank_account = _account(book, account_id, "Bank account not found")

    # Category is optional — clearing it de-categorizes the transaction.
    # An account the entry already uses stays allowed even if it's a system
    # one, so re-saving an adjustment untouched keeps working.
    current_category_ids = (
        {line.account_id for line in bank_tx.journal_entry.lines.all() if line.account_id != bank_tx.account_id}
        if bank_tx.journal_entry_id
        else set()
    )
    category_account = None
    if category_id is not None:
        category_account = _category(book, category_id, keep_ids=current_category_ids)

    # A split's transfer leg shows here as a mirror row; any edit to it would
    # rewrite a split the user made in the other account.
    if is_split_mirror(bank_tx):
        raise FeedError(SPLIT_MIRROR_ERROR)

    # Re-pointing (or clearing) the mirror leg's category would orphan the real
    # primary transaction; reject it (edit the original transaction instead).
    if would_orphan_primary(bank_tx, category_account):
        raise FeedError(MIRROR_EDIT_ERROR)

    # Removing the category from a reconciled transaction would drop confirmed
    # history out of the ledger; refuse until it is unreconciled. A request
    # carrying `splits` has no single category by design and is re-apportioning
    # rather than de-categorizing, so it is not this guard's business -- the
    # bank line keeps its amount either way.
    if category_account is None and splits is None and bank_tx.journal_entry and _bank_line_reconciled(bank_tx):
        raise FeedError("This transaction is reconciled. Unreconcile it before removing its category.")

    amount = _amount(inflow, outflow)
    # Split legs, when the client sent them. Validated (and their sum checked
    # against the total) before anything is written, so a bad payload never
    # opens a transaction.
    legs = _legs(splits, amount, keep_ids=current_category_ids)

    # An existing split must be sent with its legs, or explicitly collapsed.
    # Dropping them silently would fold the user's apportionment into whatever
    # single category the request happened to carry -- which is exactly what the
    # old code did, and why a split could not survive being opened.
    if legs is None and category_account is not None and not remove_split and is_split(bank_tx.journal_entry):
        raise FeedError("This transaction is split across categories. Send its splits, or remove the split first.")

    # Reconciliation is a fact about the bank line, whose amount does not change
    # when legs are re-apportioned -- so re-splitting a reconciled transaction is
    # allowed, and changing its total is not.
    if amount != bank_tx.amount and bank_tx.journal_entry_id and _bank_line_reconciled(bank_tx):
        raise FeedError("This transaction is reconciled. Unreconcile it before changing its amount.")

    # The rest of what can change a reconciled line: moving it to another
    # account, re-dating it past its statement, or dropping the other side of
    # a transfer by de-categorizing. `apply_splits` guards the legs themselves.
    try:
        entry = bank_tx.journal_entry
        if entry is not None:
            if bank_account.id != bank_tx.account_id:
                for line in entry.lines.filter(account=bank_tx.account):
                    assert_line_mutable(line, new_account=bank_account)
            assert_date_change_allowed(entry, date)
            if category_account is None and splits is None:
                assert_entry_removable(entry, own_account_id=bank_tx.account_id, verb=gettext("removing its category"))
    except ReconciledLineError as e:
        raise FeedError(str(e)) from None

    payee_obj = _payee(book, payee)

    try:
        with transaction.atomic():
            # Remember the original bank account so we can still identify the bank-side
            # journal line after the account is reassigned
            old_account = bank_tx.account

            bank_tx.account = bank_account
            bank_tx.amount = amount
            bank_tx.posted_date = date
            bank_tx.description = description
            bank_tx.merchant_name = payee
            bank_tx.save()

            # Update, create, or remove the journal entry depending on the category.
            # `apply_splits` writes the lines in every case -- a plain transaction is
            # just a split with one leg -- so there is one place that decides which
            # side of a line an amount lands on, and one place that checks the
            # entry balances.
            journal_entry = bank_tx.journal_entry
            entry_legs = legs if legs is not None else [(category_account, amount)]

            if category_account is None and legs is None:
                # Blank category: leave the transaction uncategorized. Drop any
                # existing journal entry (and its mirror leg) so it disappears from
                # balances and reappears as an uncategorized feed row.
                if journal_entry is not None:
                    decategorize(bank_tx)
            elif journal_entry:
                journal_entry.entry_date = date
                journal_entry.description = description
                journal_entry.payee = payee_obj
                journal_entry.save()

                # Follow an account move before the lines are rewritten: everything
                # below finds the bank line by the transaction's *current* account.
                # Saved one at a time rather than through `QuerySet.update()` so the
                # audit signals fire.
                if old_account != bank_account:
                    for line in journal_entry.lines.filter(account=old_account):
                        line.account = bank_account
                        line.save()

                apply_splits(bank_tx, entry_legs, total=amount)
            else:
                bank_tx.journal_entry = _new_entry(book, bank_account, date, description, payee_obj)
                bank_tx.save()

                apply_splits(bank_tx, entry_legs, total=amount)

            # Keep the transfer's two legs in lockstep — moves/creates/removes the
            # counterpart leg and syncs its display fields, in either direction.
            sync_transfer(bank_tx)

    except ValueError as e:
        # A reconciled leg `apply_splits` refused to drop or re-amount.
        raise FeedError(str(e)) from None

    bank_tx.refresh_from_db()
    return bank_tx


def _account(book, account_id, missing_message):
    try:
        return Account.objects.get(book=book, id=account_id)
    except Account.DoesNotExist:
        raise FeedError.not_found(missing_message) from None


def _category(book, category_id, keep_ids=()):
    category_account = _account(book, category_id, "Category account not found")
    try:
        assert_category_allowed(category_account, keep_ids=keep_ids)
    except ValueError as e:
        raise FeedError(str(e)) from None
    return category_account


def _amount(inflow, outflow):
    """The signed amount of a transaction given as two boxes: positive = outflow."""
    return (outflow or Decimal("0")) - (inflow or Decimal("0"))


def _legs(splits, amount, keep_ids=()):
    """Parsed split legs, or None when none were sent. Raises `FeedError`."""
    if splits is None:
        return None
    try:
        legs = parse_legs(splits, keep_ids=keep_ids)
        check_legs_total(legs, total=amount)
    except SplitError as e:
        raise FeedError(str(e)) from None
    return legs


def _payee(book, name):
    """The book's payee named `name`, created on first use; None for a blank name."""
    if not name:
        return None
    payee, _ = Payee.objects.get_or_create(book=book, name=name)
    return payee


def _bank_line_reconciled(bank_tx):
    return bank_tx.journal_entry.lines.filter(account=bank_tx.account, is_reconciled=True).exists()


def _new_entry(book, bank_account, date, description, payee):
    """
    A manual journal entry holding a placeholder bank line. `apply_splits` gives
    the line its side and amount, so only one place decides that.
    """
    journal_entry = JournalEntry.objects.create(
        book=book,
        entry_date=date,
        description=description,
        payee=payee,
        source=JournalEntry.SOURCE_MANUAL,
        status=JournalEntry.STATUS_POSTED,
    )
    JournalLine.objects.create(
        journal_entry=journal_entry,
        book=book,
        account=bank_account,
        dr_amount=Decimal("0"),
        cr_amount=Decimal("0"),
    )
    return journal_entry
