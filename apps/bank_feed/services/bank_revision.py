"""
The bank revising a transaction it already reported.

A bank changes its mind about a transaction in two ways: a pending
authorization settles as a posted transaction (often with a new amount -- a
restaurant tip, a fuel pre-authorization -- and a new date), and a transaction
is amended in place. Either way the feed row already exists, may already be
categorized, and may already be reconciled. `revise()` carries the bank's new
figures onto that row without losing what the user did with it:

- **Amount and date follow the bank**, on the row and on its journal entry, so
  a categorized transaction keeps its category and its balance stays true. The
  entry's lines are rewritten through `splits.write_lines`, the one writer that
  keeps them balanced, and a transfer's mirror leg follows via `sync_transfer`.
- **What the user typed stays.** On a categorized row the description and payee
  are left as they are -- the user may have fixed them, and the bank's posted
  wording is rarely better. An uncategorized row takes the bank's wording.
- **A reconciled line never changes amount, and is never re-dated past its
  statement** (`apps.reconciliation.services.guards`). When the bank's new
  amount cannot be written -- the line is reconciled, or the transaction is
  split and there is no honest way to re-apportion it -- the row keeps its
  amount and the *difference* arrives as its own uncategorized row on the same
  account. The account's balance then matches the bank once the difference is
  categorized, and nothing the user confirmed moved.

Difference rows point back at the row they correct (`raw["revision_of"]`), so a
second revision adjusts the existing difference instead of stacking another.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from apps.journal.models import JournalEntry
from apps.reconciliation.services.guards import (
    ReconciledLineError,
    assert_date_change_allowed,
    assert_line_mutable,
)

from ..models import BankTransaction
from .splits import SplitError, is_split, write_lines
from .transfer_mirror import sync_transfer

#: Where a difference row records the row it corrects.
REVISION_OF = "revision_of"


@dataclass(frozen=True)
class Revision:
    """What the bank now says about a transaction (amount signed, positive = outflow)."""

    amount: Decimal
    posted_date: date
    description: str
    merchant_name: str | None = None


@dataclass
class RevisionResult:
    amount_changed: bool = False
    date_changed: bool = False
    #: The uncategorized row carrying an amount change the ledger could not take.
    difference_row: BankTransaction | None = None
    #: Why the row's own date was kept (the reconciliation guard's message).
    date_kept_reason: str | None = None


def difference_rows(bank_tx):
    """The rows that carry bank amount changes `bank_tx` itself could not take."""
    return BankTransaction.objects.filter(book=bank_tx.book, **{f"raw__{REVISION_OF}": bank_tx.pk})


def bank_amount(bank_tx) -> Decimal:
    """What the bank last said `bank_tx` was for: its own amount plus any difference rows."""
    return bank_tx.amount + sum((row.amount for row in difference_rows(bank_tx)), Decimal("0"))


@transaction.atomic
def revise(bank_tx, revision: Revision) -> RevisionResult:
    """Carry the bank's `revision` onto `bank_tx`. See the module docstring for the rules."""
    bank_tx = BankTransaction.objects.select_for_update(of=("self",)).select_related("journal_entry").get(pk=bank_tx.pk)
    entry = bank_tx.journal_entry
    result = RevisionResult()

    if entry is None:
        bank_tx.description = revision.description
        bank_tx.merchant_name = revision.merchant_name

    if revision.posted_date != bank_tx.posted_date:
        try:
            assert_date_change_allowed(entry, revision.posted_date)
        except ReconciledLineError as exc:
            result.date_kept_reason = str(exc)
        else:
            bank_tx.posted_date = revision.posted_date
            if entry is not None:
                entry.entry_date = revision.posted_date
                entry.save(update_fields=["entry_date", "updated_at"])
            result.date_changed = True

    delta = revision.amount - bank_amount(bank_tx)
    if delta:
        target = bank_tx.amount + delta
        if entry is None or _rewrite_amount(bank_tx, entry, target):
            bank_tx.amount = target
            result.amount_changed = True
        elif entry.status != JournalEntry.STATUS_VOID:
            # A void entry counts toward nothing, so a figure it cannot take has
            # nowhere it would matter; anything else gets a difference row.
            result.difference_row = _carry_difference(bank_tx, delta, revision)

    bank_tx.save()
    if entry is not None:
        sync_transfer(bank_tx)
    return result


def _rewrite_amount(bank_tx, entry, total) -> bool:
    """
    Re-amount a plain categorized entry to `total`; False when it can't be done
    without moving a reconciled line or re-apportioning a split.
    """
    if is_split(entry):
        return False
    lines = list(entry.lines.select_related("account"))
    home = [line for line in lines if line.account_id == bank_tx.account_id]
    others = [line for line in lines if line.account_id != bank_tx.account_id]
    if len(home) != 1 or len(others) != 1:
        return False
    try:
        # The home line holds the opposite side of the total (dr - cr = -total).
        assert_line_mutable(home[0], new_amount=-total)
        write_lines(entry, bank_tx.account_id, [(others[0].account, total)], total=total, book=bank_tx.book)
    except (ReconciledLineError, SplitError):
        return False
    return True


def _carry_difference(bank_tx, delta, revision):
    """Add `delta` to the row's open difference row, or open one."""
    existing = difference_rows(bank_tx).filter(journal_entry__isnull=True, is_void=False).select_for_update().first()
    if existing is not None:
        existing.amount += delta
        if not existing.amount:
            existing.delete()
            return None
        existing.save(update_fields=["amount", "updated_at"])
        return existing

    note = _("the bank changed this transaction's amount from %(old)s to %(new)s") % {
        "old": f"{bank_amount(bank_tx):.2f}",
        "new": f"{revision.amount:.2f}",
    }
    return BankTransaction.objects.create(
        book=bank_tx.book,
        account_id=bank_tx.account_id,
        amount=delta,
        posted_date=bank_tx.posted_date,
        description=f"{revision.description} ({note})"[:255],
        merchant_name=bank_tx.merchant_name,
        source=bank_tx.source,
        raw={REVISION_OF: bank_tx.pk, "from": str(bank_amount(bank_tx)), "to": str(revision.amount)},
    )
