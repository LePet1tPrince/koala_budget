"""
Splitting one bank transaction across several categories.

A split is one JournalEntry: a single line on the bank account carrying the
total, and one counter line per leg -- the shape `apps.ynab_import` already
builds, so an imported split and one made here are the same thing.

The signed-amount convention is the Plaid one used throughout the feed
(positive is an outflow). A leg takes the same side as its own sign; the bank
line takes the opposite side of the total:

    leg  a > 0  ->  dr = a          leg  a < 0  ->  cr = -a
    total  > 0  ->  bank cr = total    total < 0  ->  bank dr = -total

which balances for any mix of signs, including a refund leg inside an outflow
(+100, -20 against a total of +80) and a gross paycheque with deductions
(-4000, +800, +200 against a total of -3000).

Everything that writes a transaction's journal lines goes through
`apps.journal.services.lines.write_lines`, so the balance invariant is enforced in
one place instead of at each call site -- which is what the previous per-call-site
arithmetic got wrong. `apply_splits` is that function with a feed row's account
filled in. `write_lines`, `check_legs_total`, `signed_amount` and `SplitError` are
re-exported here, where they used to live, so existing imports keep working.
"""

from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext_lazy as _

from apps.accounts.guards import SystemCategoryError, assert_category_allowed
from apps.accounts.models import Account
from apps.journal.services.lines import CENT, SplitError, check_legs_total, signed_amount, write_lines

__all__ = [
    "CENT",
    "MAX_LEGS",
    "MIN_LEGS",
    "SplitError",
    "apply_splits",
    "check_legs_total",
    "is_split",
    "parse_legs",
    "signed_amount",
    "split_legs",
    "write_lines",
]

#: A split with one leg is a plain transaction; offer "remove split" instead.
MIN_LEGS = 2

#: Not a product limit -- an abuse ceiling, comfortably above any real receipt.
MAX_LEGS = 20


def is_split(entry) -> bool:
    """True when this entry apportions one transaction across several categories."""
    if entry is None:
        return False
    return entry.lines.count() > 2


def split_legs(entry, bank_account):
    """
    The entry's category lines -- every line except the bank account's.

    Returns [] for anything that is not a split, so callers can use the result
    as both the legs and the "is this split" test.
    """
    if entry is None:
        return []
    lines = list(entry.lines.all())
    if len(lines) <= 2:
        return []
    bank_account_id = getattr(bank_account, "id", bank_account)
    return [line for line in lines if line.account_id != bank_account_id]


def parse_legs(raw, keep_ids=()) -> list[tuple[Account, Decimal]]:
    """
    Validate a client's `splits` payload into (account, signed amount) pairs.

    Every rejection is a refusal rather than a silent drop: a leg the user
    entered that vanished without explanation is worse than an error they can
    act on. Accounts are looked up through the book-scoped manager, so another
    book's account is "not found" rather than a successful cross-tenant write.
    A system account is refused unless its id is in `keep_ids` (already on the entry).
    """
    if not isinstance(raw, list):
        raise SplitError(_("Splits must be a list."))
    if len(raw) < MIN_LEGS:
        raise SplitError(_("A split needs at least %(n)d categories.") % {"n": MIN_LEGS})
    if len(raw) > MAX_LEGS:
        raise SplitError(_("A split cannot have more than %(n)d categories.") % {"n": MAX_LEGS})

    legs = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise SplitError(_("Split %(n)d is not valid.") % {"n": index})

        try:
            account = Account.for_book.get(id=item.get("category"))
        except (Account.DoesNotExist, TypeError, ValueError):
            raise SplitError(_("Split %(n)d: category not found.") % {"n": index}) from None
        try:
            assert_category_allowed(account, keep_ids=keep_ids)
        except SystemCategoryError as e:
            raise SplitError(_("Split %(n)d: %(error)s") % {"n": index, "error": e}) from None

        try:
            amount = Decimal(str(item.get("amount"))).quantize(CENT)
        except (InvalidOperation, TypeError, ValueError):
            raise SplitError(_("Split %(n)d: amount is not a number.") % {"n": index}) from None

        if amount == 0:
            raise SplitError(_("Split %(n)d: amount cannot be zero.") % {"n": index})

        legs.append((account, amount))

    return legs


def apply_splits(bank_tx, legs, *, total, move_lines=()):
    """
    Write `legs` as the category lines of `bank_tx`'s journal entry.

    A feed row names its own home account, so this is `write_lines` with the bank
    account filled in. `move_lines` are the entry's lines on the row's previous
    account, when the edit moved it (see `write_lines`).
    """
    return write_lines(
        bank_tx.journal_entry,
        bank_tx.account_id,
        legs,
        total=total,
        book=bank_tx.book,
        move_lines=move_lines,
    )
