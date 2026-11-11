"""
The entry posted when a statement is finished with a difference.

Moved here from `bank_feed.views` (the feed's old quick reconcile) and given the
one thing it lacked: it is told the amount in LEDGER sign by a caller that has
converted it (`signs.to_ledger`), instead of trusting a user-typed "true
balance" that was ledger-signed for cards without saying so.

It posts against the system equity account "Reconciliation Adjustments" -- the
same offset opening balances use -- so an adjustment never shows up in income
or expense reports.
"""

from decimal import Decimal

from django.db import transaction

from apps.accounts.models import ACCOUNT_TYPE_EQUITY, Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry
from apps.journal.services.lines import write_lines

OFFSET_ACCOUNT_NAME = "Reconciliation Adjustments"
OFFSET_GROUP_NAME = "Equity Adjustments"
ADJUSTMENT_DESCRIPTION = "Reconciliation Adjustment"


def offset_account(book) -> Account:
    """The system equity account adjustments post against, created on first use."""
    account = Account.objects.filter(
        book=book, name=OFFSET_ACCOUNT_NAME, account_group__account_type=ACCOUNT_TYPE_EQUITY
    ).first()
    if account is not None:
        if not account.is_system:
            account.is_system = True
            account.save(update_fields=["is_system"])
        return account

    group = AccountGroup.objects.filter(book=book, name=OFFSET_GROUP_NAME).first()
    if group is None:
        group = AccountGroup.objects.create(
            book=book, name=OFFSET_GROUP_NAME, account_type=ACCOUNT_TYPE_EQUITY, is_system=True
        )
    return Account.objects.create(
        book=book, name=OFFSET_ACCOUNT_NAME, account_group=group, has_feed=False, is_system=True
    )


@transaction.atomic
def create_adjustment(reconciliation, ledger_amount: Decimal) -> JournalEntry:
    """
    Post `ledger_amount` (dr - cr on the reconciled account) on the statement date.

    The account's line is reconciled on `reconciliation` at once -- it exists only
    to make that statement balance. A feed row is added only for an account that
    has a feed, so the adjustment is visible where the user reconciles from.
    """
    book = reconciliation.book
    account = reconciliation.account
    date = reconciliation.statement_date

    entry = JournalEntry.objects.create(
        book=book,
        entry_date=date,
        description=ADJUSTMENT_DESCRIPTION,
        source=JournalEntry.SOURCE_RECONCILIATION,
        status=JournalEntry.STATUS_POSTED,
    )
    # One leg on the equity offset; the account's own line is the home line, created
    # already reconciled. `total` is in the writer's signed convention (positive is
    # a credit to the account), so the account is debited when `ledger_amount` > 0.
    total = -ledger_amount
    write_lines(
        entry,
        account,
        [(offset_account(book), total)],
        total=total,
        book=book,
        home_fields={"is_reconciled": True, "reconciliation": reconciliation},
    )
    if account.has_feed:
        BankTransaction.objects.create(
            book=book,
            account=account,
            # Feed convention: positive is an outflow, i.e. a credit to the account.
            amount=-ledger_amount,
            posted_date=date,
            description=ADJUSTMENT_DESCRIPTION,
            source=BankTransaction.SOURCE_SYSTEM,
            journal_entry=entry,
        )
    return entry
