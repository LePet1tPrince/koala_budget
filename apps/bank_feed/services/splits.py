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

Everything that writes a transaction's journal lines goes through `write_lines`,
so the balance invariant is enforced in one place instead of at each call site --
which is what the previous per-call-site arithmetic got wrong. `apply_splits` is
that function with a feed row's account filled in; the Transactions page calls
`write_lines` directly, since a manually-entered transaction has no feed row.
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Account
from apps.journal.models import JournalLine

#: A split with one leg is a plain transaction; offer "remove split" instead.
MIN_LEGS = 2

#: Not a product limit -- an abuse ceiling, comfortably above any real receipt.
MAX_LEGS = 20

CENT = Decimal("0.01")


class SplitError(ValueError):
    """
    A split the caller asked for that cannot be written.

    The message is shown to the user, so it says what to do about it. Subclasses
    ValueError because `categorize` already turns a ValueError into a 400.
    """


def is_split(entry) -> bool:
    """True when this entry apportions one transaction across several categories."""
    if entry is None:
        return False
    return entry.lines.count() > 2


def signed_amount(line) -> Decimal:
    """A line's amount in the feed's signed convention: debit positive, credit negative."""
    return line.dr_amount - line.cr_amount


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


def parse_legs(raw) -> list[tuple[Account, Decimal]]:
    """
    Validate a client's `splits` payload into (account, signed amount) pairs.

    Every rejection is a refusal rather than a silent drop: a leg the user
    entered that vanished without explanation is worse than an error they can
    act on. Accounts are looked up through the team-scoped manager, so another
    team's account is "not found" rather than a successful cross-tenant write.
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
            account = Account.for_team.get(id=item.get("category"))
        except (Account.DoesNotExist, TypeError, ValueError):
            raise SplitError(_("Split %(n)d: category not found.") % {"n": index}) from None

        try:
            amount = Decimal(str(item.get("amount"))).quantize(CENT)
        except (InvalidOperation, TypeError, ValueError):
            raise SplitError(_("Split %(n)d: amount is not a number.") % {"n": index}) from None

        if amount == 0:
            raise SplitError(_("Split %(n)d: amount cannot be zero.") % {"n": index})

        legs.append((account, amount))

    return legs


def check_legs_total(legs, *, total):
    """
    Raise unless the legs add up to the transaction total, to the cent.

    Separate from `apply_splits` so a view can reject a mismatch *before* it
    opens a transaction, and still report it in the same words.
    """
    leg_total = sum((amount for _, amount in legs), Decimal("0"))
    if leg_total != total:
        raise SplitError(
            _("Splits must add up to the transaction total. They add up to %(legs)s, but the transaction is %(total)s.")
            % {"legs": leg_total, "total": total}
        )


@transaction.atomic
def write_lines(entry, home_account, legs, *, total, team):
    """
    Write `legs` as the category lines of `entry`, against `home_account`.

    The home line -- the one on the account the money sat in -- is updated in
    place, never recreated: it carries is_reconciled / is_cleared / is_archived,
    and recreating it would silently unreconcile a transaction the user has
    already confirmed against a statement.

    `total` is signed, positive for an outflow. Raises SplitError when the legs
    do not sum to it -- the total is a fact about the transaction, so a mismatch
    is a caller bug and must not reach the ledger.

    Split out of `apply_splits` so the Transactions page can write the same lines
    for an entry that has no `BankTransaction` at all. Everything that writes a
    transaction's journal lines still goes through one function, which is what
    keeps the balance invariant and the sign convention in one place rather than
    at each call site.
    """
    check_legs_total(legs, total=total)

    if entry is None:
        raise SplitError(_("This transaction has no journal entry to split."))

    home_account_id = getattr(home_account, "id", home_account)
    existing = list(entry.lines.all())
    home_lines = [line for line in existing if line.account_id == home_account_id]
    if len(home_lines) != 1:
        # Not a shape this function can safely rewrite: bail rather than guess
        # which line is the home account's and risk rewriting the wrong one.
        raise SplitError(_("This transaction's ledger entry cannot be split automatically."))
    home_line = home_lines[0]

    # The home line takes the opposite side of the total.
    home_line.dr_amount = -total if total < 0 else Decimal("0")
    home_line.cr_amount = total if total > 0 else Decimal("0")
    # Re-point at the caller's entry object so `JournalLine.save()` resolves the
    # budget link from the entry date the caller just set, rather than from the
    # stale one its own FK cache is holding.
    home_line.journal_entry = entry
    home_line.save()

    # Replace the category lines. They carry no state the user set -- only the
    # home line does -- so recreating them is safe, and it keeps this function
    # independent of how many legs the entry had before.
    for line in existing:
        if line.id != home_line.id:
            line.delete()

    for account, amount in legs:
        JournalLine.objects.create(
            journal_entry=entry,
            team=team,
            account=account,
            dr_amount=amount if amount > 0 else Decimal("0"),
            cr_amount=-amount if amount < 0 else Decimal("0"),
        )

    return entry


def apply_splits(bank_tx, legs, *, total):
    """
    Write `legs` as the category lines of `bank_tx`'s journal entry.

    A feed row names its own home account, so this is `write_lines` with the bank
    account filled in.
    """
    return write_lines(
        bank_tx.journal_entry,
        bank_tx.account_id,
        legs,
        total=total,
        team=bank_tx.team,
    )


@transaction.atomic
def collapse_split(bank_tx, category_account, *, total):
    """
    Turn a split back into a plain two-line entry on `category_account`.

    This is what the editor's "Remove split" does. Bulk operations must not do
    it implicitly: silently collapsing a four-way split because it was caught in
    a select-all destroys work the user did deliberately.
    """
    return apply_splits(bank_tx, [(category_account, total)], total=total)
