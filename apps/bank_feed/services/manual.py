"""
Writing a manual bank feed transaction.

One function for both callers -- the feed API's create and the recurring
schedule -- so a generated occurrence is exactly the transaction the user would
have typed in: same journal entry shape, same split writer, same transfer mirror.
"""

from decimal import Decimal

from django.db import transaction

from apps.accounts.models import Payee
from apps.journal.models import JournalEntry, JournalLine

from ..models import BankTransaction
from .splits import apply_splits
from .transfer_mirror import sync_transfer


@transaction.atomic
def create_manual_transaction(
    *, book, account, date, amount, payee_name="", description="", legs=None, recurring=None
) -> BankTransaction:
    """
    Create a manual feed row in `account`, and its journal entry when `legs` is given.

    `amount` is signed, positive for an outflow. `legs` is a list of
    (category account, signed amount) pairs summing to `amount` -- one pair for a
    plain categorized transaction -- or None to leave the row uncategorized.
    Callers validate the legs (`parse_legs` / `check_legs_total`) first.
    """
    payee = None
    if payee_name:
        payee, _ = Payee.objects.get_or_create(book=book, name=payee_name)

    journal_entry = None
    if legs is not None:
        journal_entry = JournalEntry.objects.create(
            book=book,
            entry_date=date,
            description=description,
            payee=payee,
            source=JournalEntry.SOURCE_MANUAL,
            status=JournalEntry.STATUS_POSTED,
        )
        # Placeholder bank line; `apply_splits` below gives it the right side and
        # amount, so only one place decides that.
        JournalLine.objects.create(
            journal_entry=journal_entry,
            book=book,
            account=account,
            dr_amount=Decimal("0"),
            cr_amount=Decimal("0"),
        )

    bank_tx = BankTransaction.objects.create(
        book=book,
        account=account,
        amount=amount,
        posted_date=date,
        description=description,
        merchant_name=payee_name,
        source=BankTransaction.SOURCE_MANUAL,
        journal_entry=journal_entry,
        recurring=recurring,
    )

    if legs is not None:
        apply_splits(bank_tx, legs, total=amount)

    # Mirror the leg into the counterpart account's feed if it's a transfer.
    # (No-op for an uncategorized transaction with no journal entry.)
    sync_transfer(bank_tx)
    return bank_tx
