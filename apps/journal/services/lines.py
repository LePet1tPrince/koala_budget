"""
The one place a transaction's journal lines are written.

A transaction is one `JournalEntry`: a **home line** on the account the money sat
in (a bank account, a card, cash) and one or more **category legs** -- one for a
plain transaction, several for a split. Every path that creates, re-amounts,
re-points or removes those lines comes through this module: the bank feed
(categorize, edit, batch edit, manual add), CSV import, the Transactions page,
Plaid revisions, transfer matching, opening balances, reconciliation
adjustments, and the journal API.

Two things hang off that, and they are why it is one module rather than five
copies of the same arithmetic:

* **The leg-expansion seam** -- `expand_legs`. Every categorization goes through
  `write_lines`, and `write_lines` passes its legs through `expand_legs` before
  writing them. Today it is a no-op. It is where a sales-tax code will turn one
  leg into a net leg plus a tax leg (to an HST Payable / ITC account), once,
  for every path above.

* **The line choke point** -- `create_line`, `save_line`, `delete_line`. Every
  line this module writes is written through one of the three, so a rule that
  must see every write to a transaction's lines (a period lock, say) is one
  call in each, not one per call site.

The signed-amount convention is the feed's (Plaid's): positive is an outflow. A
leg takes the same side as its own sign; the home line takes the opposite side
of the total:

    leg  a > 0  ->  dr = a          leg  a < 0  ->  cr = -a
    total  > 0  ->  home cr = total    total < 0  ->  home dr = -total

which balances for any mix of signs, including a refund leg inside an outflow
(+100, -20 against a total of +80) and a gross paycheque with deductions
(-4000, +800, +200 against a total of -3000).

**What does not come through here**, deliberately, and is the allowlist of the
structural test in `apps/journal/test_lines.py`:

* `apps.ynab_import.services.apply` and `apps.portability.services.apply` --
  whole-book bulk imports into an *empty* book. They insert tens of thousands of
  already-balanced lines with `bulk_create_for_import` in one atomic block; a
  per-line `save()` (and its audit row) would turn a seconds-long import into
  minutes, and there is no existing line, reconciliation or feed row to keep.
  Both verify the result as a whole before committing.
* `apps.budget.ledger` -- budget entries. They are not transactions: one entry
  per book-month moving money between budget buckets, never touching a balance
  that counts, with its own single writer and integrity check.

`JournalLine.save()` itself keeps the budget-ledger rule (a bucket only in a
budget entry) for every path, this one included.
"""

from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.journal.models import JournalLine
from apps.journal.services import period_lock
from apps.reconciliation.services.guards import assert_line_mutable, assert_line_removable

ZERO = Decimal("0")
CENT = Decimal("0.01")


class SplitError(ValueError):
    """
    Lines the caller asked for that cannot be written.

    The message is shown to the user, so it says what to do about it. Subclasses
    ValueError because the feed's endpoints already turn a ValueError into a 400.
    (Named for the split editor, the first caller that could produce one.)
    """


def signed_amount(line) -> Decimal:
    """A line's amount in the feed's signed convention: debit positive, credit negative."""
    return line.dr_amount - line.cr_amount


def sides_of(amount: Decimal) -> tuple[Decimal, Decimal]:
    """`(dr, cr)` for a leg of signed `amount`: a leg takes the side of its own sign."""
    return (amount if amount > 0 else ZERO, -amount if amount < 0 else ZERO)


def check_legs_total(legs, *, total):
    """
    Raise unless the legs add up to the transaction total, to the cent.

    Separate from `write_lines` so a view can reject a mismatch *before* it
    opens a transaction, and still report it in the same words.
    """
    leg_total = sum((amount for _, amount in legs), ZERO)
    if leg_total != total:
        raise SplitError(
            _("Splits must add up to the transaction total. They add up to %(legs)s, but the transaction is %(total)s.")
            % {"legs": leg_total, "total": total}
        )


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------


def expand_legs(legs):
    """
    The legs `write_lines` actually writes, given the legs the caller asked for.

    **This is where sales-tax codes will go.** A leg categorized to an account
    carrying a tax code becomes two: the net amount on the category, and the tax
    on the tax account (HST Payable for a sale, an input-tax-credit account for a
    purchase). The expanded legs must still sum to what the caller's legs summed
    to, so the home line -- the amount the bank reported -- never changes.

    Today no account carries a tax code, so this returns the legs unchanged.
    Every categorization path reaches it through `write_lines`; nothing else
    needs to learn about tax.
    """
    return list(legs)


# ---------------------------------------------------------------------------
# The choke point: every line this module writes goes through one of these
# ---------------------------------------------------------------------------


def create_line(*, entry, book, account, dr_amount=ZERO, cr_amount=ZERO, **fields):
    """Create one line on `entry`. `account` and `book` may each be an instance or its id."""
    fields["account_id" if isinstance(account, int) else "account"] = account
    fields["book_id" if isinstance(book, int) else "book"] = book
    return JournalLine.objects.create(journal_entry=entry, dr_amount=dr_amount, cr_amount=cr_amount, **fields)


def save_line(line):
    """Save a changed line, one `save()` at a time so the audit signals record the diff."""
    line.save()
    return line


def delete_line(line):
    """Delete one line."""
    line.delete()


def repoint_line(line, account):
    """
    Move one existing line to `account`, keeping its amount and its flags.

    For the callers that move a line rather than re-categorize a transaction --
    moving a feed row to another bank account, or the journal API's
    `recategorize` of any single line. The caller has already asked
    `assert_line_mutable`. A category change on a feed transaction goes through
    `write_lines(..., repoint=True)` instead, so it reaches `expand_legs`.
    """
    line.account = account
    return save_line(line)


# ---------------------------------------------------------------------------
# Transactions: a home line and its category legs
# ---------------------------------------------------------------------------


def write_lines(entry, home_account, legs, *, total, book, move_lines=(), repoint=False, home_fields=None, lines=None):
    """
    Write `legs` as the category lines of `entry`, against `home_account`.

    `legs` are `(Account, signed amount)` pairs and `total` is the transaction's
    signed total (positive for an outflow). Raises SplitError when the legs do not
    sum to it -- the total is a fact about the transaction, so a mismatch is a
    caller bug and must not reach the ledger.

    The home line -- the one on the account the money sat in -- is updated in
    place, never recreated: it carries is_reconciled / is_cleared, and recreating
    it would silently unreconcile a transaction the user has already confirmed
    against a statement. An entry with no lines yet (a transaction being
    categorized for the first time) gets its home line created first, then its
    legs, with `home_fields` (e.g. `is_reconciled`) set on that new home line.

    Each leg is matched to an existing line on the same account (same amount
    first), so an unchanged leg is left exactly as it is. That matters for a
    transfer: its "category" line is the *other* feed's bank line, which carries
    that feed's reconciliation. A leg with no line on its account gets a new
    line, and a line no leg claims is deleted -- unless `repoint` is set, in
    which case an unclaimed line is moved onto the unmatched leg's account in
    place (same pk, same flags). That is "re-categorize", as opposed to
    "re-apportion".

    `move_lines` are lines on the transaction's *old* home account, re-pointed to
    `home_account` first, for an edit that moves the transaction to another
    account. Saved one at a time so the audit signals record the move.

    Everything that can refuse (the total, the entry's shape, the reconciliation
    guards) is checked before the first write, so a refusal leaves the caller's
    transaction usable -- `bank_revision` catches one and carries on -- and the
    writes need no savepoint of their own.

    `lines` are the entry's current lines when the caller has just read them (or
    `[]` for an entry it has just created), saving a query; they are read from the
    database otherwise.

    Callers call `sync_transfer` afterwards when a feed row is involved: this
    writes the ledger, the feed's mirror rows follow from it.
    """
    check_legs_total(legs, total=total)

    if entry is None:
        raise SplitError(_("This transaction has no journal entry to split."))
    # A closed period's lines don't change (`period_lock`); a PeriodLockedError is a ValueError.
    period_lock.assert_entry_mutable(entry, book=book)

    legs = expand_legs(legs)
    home_account_id = getattr(home_account, "id", home_account)

    existing = list(entry.lines.all()) if lines is None else list(lines)

    # Re-point the moved lines in memory first, so the shape check and the leg
    # matching below see the entry as it will be; they are saved with the rest.
    move_ids = {line.pk for line in move_lines}
    moved = [line for line in existing if line.pk in move_ids]
    for line in moved:
        if isinstance(home_account, int):
            line.account_id = home_account
        else:
            line.account = home_account

    if not existing:
        home_line = None
    else:
        home_lines = [line for line in existing if line.account_id == home_account_id]
        if len(home_lines) != 1:
            # Not a shape this function can safely rewrite: bail rather than guess
            # which line is the home account's and risk rewriting the wrong one.
            raise SplitError(_("This transaction's ledger entry cannot be split automatically."))
        home_line = home_lines[0]

    remaining = [line for line in existing if line is not home_line]
    plan = []
    for account, amount in legs:
        match = next(
            (line for line in remaining if line.account_id == account.id and signed_amount(line) == amount), None
        ) or next((line for line in remaining if line.account_id == account.id), None)
        if match is not None:
            remaining.remove(match)
        plan.append([match, account, amount])

    if repoint:
        for item in plan:
            if item[0] is None and remaining:
                item[0] = remaining.pop(0)

    # Refuse before writing anything: a reconciled line may be neither dropped,
    # moved nor re-amounted.
    for line in remaining:
        assert_line_removable(line, own=False, verb=_("changing its category"))
    for match, account, amount in plan:
        if match is not None:
            assert_line_mutable(match, new_account=account, new_amount=amount, own=False)

    # The home line takes the opposite side of the total.
    home_dr, home_cr = (-total if total < 0 else ZERO, total if total > 0 else ZERO)

    # No savepoint: nothing below refuses, so a failure here is one the caller's
    # transaction must not survive anyway.
    with transaction.atomic(savepoint=False):
        for line in moved:
            # Re-point at the caller's entry object, rather than the stale one the
            # line's own FK cache is holding.
            line.journal_entry = entry
            save_line(line)

        if home_line is None:
            create_line(
                entry=entry,
                book=book,
                account=home_account,
                dr_amount=home_dr,
                cr_amount=home_cr,
                **(home_fields or {}),
            )
        elif (home_line.dr_amount, home_line.cr_amount) != (home_dr, home_cr):
            home_line.dr_amount, home_line.cr_amount = home_dr, home_cr
            home_line.journal_entry = entry
            save_line(home_line)

        for line in remaining:
            delete_line(line)

        for match, account, amount in plan:
            dr, cr = sides_of(amount)
            if match is None:
                create_line(entry=entry, book=book, account=account, dr_amount=dr, cr_amount=cr)
            elif (match.account_id, match.dr_amount, match.cr_amount) != (account.id, dr, cr):
                match.account = account
                match.dr_amount, match.cr_amount = dr, cr
                match.journal_entry = entry
                save_line(match)

    return entry


# ---------------------------------------------------------------------------
# The journal API: lines given explicitly
# ---------------------------------------------------------------------------


def add_lines(entry, lines_data, *, book):
    """Create the lines the journal-entry API was sent, as given (`JournalLine` field dicts)."""
    return [create_line(entry=entry, book=book, **data) for data in lines_data]


@transaction.atomic
def replace_lines(entry, lines_data, *, book):
    """
    Replace every line of `entry` with `lines_data`, for the journal-entry API.

    That API takes an entry as a free list of debit/credit lines, with no home
    line and no legs, so there is nothing to match a new line to an old one by:
    it deletes and recreates. That is why it is only for entries no feed row
    points at -- `JournalEntrySerializer.update` refuses a feed-backed entry, whose
    home line carries the feed's reconciliation, before calling this -- and why
    the caller has already refused an entry with a reconciled line.
    """
    for line in list(entry.lines.all()):
        delete_line(line)
    return add_lines(entry, lines_data, book=book)
