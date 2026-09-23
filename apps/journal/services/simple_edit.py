"""
Editing a transaction from the Transactions page.

The single writer for an edit made against a `JournalEntry` rather than against a
bank feed row. It exists because the two are not interchangeable: most entries on
the Transactions page are backed by a `BankTransaction`, and an edit that touches
only the ledger leaves the feed showing the old date, payee or account -- and, for
a transfer, leaves the counterpart leg pointing somewhere the user never put it.
`SimpleLineSerializer` in this app does exactly that, which is why it is not
reused here.

Two rules shape everything below.

**Lines are written in one place.** The arithmetic that decides which side of a
line an amount lands on lives in `apps.bank_feed.services.splits.write_lines`,
along with the check that the entry balances. This module decides *what* to write
and never *how*, so a plain transaction and a split cannot drift apart -- a plain
transaction is a split with one leg.

**The edits object is partial by construction.** Every field defaults to `UNSET`,
so the same object describes "change this one transaction's amount" and "set the
category on these forty". That is what makes batch editing a caller change rather
than a rewrite: `apply_edits_bulk` already takes a list, and the single-row
endpoint is that list with one element in it.
"""

from dataclasses import dataclass, field
from datetime import date as date_type
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Account, Payee
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.transfer_mirror import is_transfer_target, sync_transfer, would_orphan_primary

from ..models import JournalEntry
from .sides import UnsupportedEntry, resolve_sides


class _Unset:
    """A field the caller did not mention, as distinct from one set to None."""

    def __repr__(self):  # pragma: no cover - debugging aid
        return "UNSET"

    def __bool__(self):
        return False


UNSET = _Unset()


class EditRefused(Exception):
    """
    An edit that will not be applied, with the reason shown to the user.

    Raised before anything is written. Callers surface `str(e)` verbatim, so the
    message says what to do about it rather than naming the rule that fired.
    """


@dataclass
class TransactionEdits:
    """
    A partial description of an edit.

    `category_id` and `legs` are mutually exclusive: a transaction has either one
    category or several, never both. `remove_split` is separate from both because
    collapsing a split destroys the apportionment the user typed, so it has to be
    asked for -- inferring it from a payload that merely omits the legs is how a
    split used to disappear on being opened.
    """

    date: date_type | _Unset = UNSET
    payee_name: str | _Unset = UNSET
    description: str | _Unset = UNSET
    account_id: int | _Unset = UNSET
    category_id: int | _Unset = UNSET
    legs: list | _Unset = UNSET
    remove_split: bool = False
    inflow: Decimal | _Unset = UNSET
    outflow: Decimal | _Unset = UNSET

    #: Resolved during validation so a batch looks accounts up once, not per row.
    _accounts: dict = field(default_factory=dict, repr=False)

    def touches_amount(self) -> bool:
        return self.inflow is not UNSET or self.outflow is not UNSET

    def touches_category(self) -> bool:
        return self.category_id is not UNSET or self.legs is not UNSET or self.remove_split


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_edits(entry, edits, *, team):
    """Apply `edits` to one entry. See `apply_edits_bulk`."""
    return apply_edits_bulk([entry], edits, team=team)[0]


def apply_edits_bulk(entries, edits, *, team):
    """
    Apply the same `edits` to every entry, all of them or none.

    Every entry is checked before any is written, so a batch that would be
    refused halfway leaves nothing half-applied -- the same pre-scan
    `BankFeedViewSet.batch_edit` does. Returns the entries, refreshed.
    """
    _resolve_accounts(edits, team=team)

    plans = [_plan(entry, edits) for entry in entries]

    with transaction.atomic():
        return [_write(plan, edits, team=team) for plan in plans]


def delete_transaction(entry, *, team):
    """
    Remove a transaction.

    A bank-backed transaction is *de-categorized* rather than deleted: the feed
    row is what the bank reported and deleting it would only make the next sync
    bring it back, so the entry goes and the row returns to the feed as
    uncategorized. Anything else is deleted outright.
    """
    try:
        sides = resolve_sides(entry)
    except UnsupportedEntry as exc:
        raise EditRefused(str(exc)) from exc

    if sides.home_line.is_reconciled:
        raise EditRefused(_("This transaction is reconciled. Unreconcile it before deleting it."))

    with transaction.atomic():
        if sides.bank_tx is None:
            entry.delete()
            return

        # A mirror leg exists only to surface the shared entry in the other
        # account's feed; with the entry gone it would linger as an orphan.
        for leg in sides.mirror_txs:
            leg.delete()

        bank_tx = sides.bank_tx
        bank_tx.journal_entry = None
        bank_tx.save(update_fields=["journal_entry", "updated_at"])
        entry.delete()


def set_status(entry, new_status, *, team):
    """
    Void a transaction, or restore a voided one.

    Restoring goes to `posted`, not `draft`: every path that writes an entry in
    this app posts it, and a draft is excluded from balances exactly as a void
    is, so restoring to draft would look like the void had not lifted.
    """
    if new_status not in (JournalEntry.STATUS_VOID, JournalEntry.STATUS_POSTED):
        raise EditRefused(_("A transaction can only be voided or restored."))

    if entry.status == new_status:
        return entry

    entry.status = new_status
    entry.save()
    return entry


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _resolve_accounts(edits, *, team):
    """Look up every account the edits name, once, scoped to the team."""
    ids = [i for i in (edits.account_id, edits.category_id) if i is not UNSET and i is not None]
    if edits.legs is not UNSET and edits.legs:
        ids += [account.id for account, _ in edits.legs]

    found = {a.id: a for a in Account.objects.filter(team=team, id__in=set(ids))}
    missing = set(ids) - set(found)
    if missing:
        # Another team's account reads as "not found" rather than as a refusal
        # that confirms it exists.
        raise EditRefused(_("That category no longer exists."))
    edits._accounts = found


@dataclass
class _Plan:
    """One entry's resolved edit, checked and ready to write."""

    entry: object
    sides: object
    account: object
    legs: list
    total: Decimal


def _plan(entry, edits):
    """Check `edits` against `entry` and work out the lines to write."""
    try:
        sides = resolve_sides(entry)
    except UnsupportedEntry as exc:
        raise EditRefused(str(exc)) from exc

    if entry.status == JournalEntry.STATUS_VOID:
        raise EditRefused(_("This transaction is void. Restore it before editing it."))

    account = _target_account(sides, edits)
    total = _target_total(sides, edits)
    legs = _target_legs(sides, edits, account=account, total=total)

    _check_reconciled(sides, account=account, total=total)
    _check_bank_rules(entry, sides, edits, total=total)
    _check_transfer(sides, legs)

    return _Plan(entry=entry, sides=sides, account=account, legs=legs, total=total)


def _target_account(sides, edits):
    if edits.account_id is UNSET:
        return sides.account
    account = edits._accounts[edits.account_id]
    if sides.bank_tx is not None and not is_transfer_target(account):
        # The feed row has to live somewhere it can be seen; moving it to an
        # account with no feed would take the transaction off every screen that
        # shows it.
        raise EditRefused(
            _("%(name)s has no bank feed, so this transaction would disappear from your feed.") % {"name": account.name}
        )
    return account


def _target_total(sides, edits) -> Decimal:
    """The signed total after the edit. Positive is an outflow."""
    if not edits.touches_amount():
        return sides.total
    inflow = _amount(edits.inflow, sides.inflow)
    outflow = _amount(edits.outflow, sides.outflow)
    if inflow > 0 and outflow > 0:
        raise EditRefused(_("A transaction is either money in or money out, not both."))
    if inflow == 0 and outflow == 0:
        raise EditRefused(_("Enter an amount for this transaction."))
    return outflow - inflow


def _amount(value, fallback) -> Decimal:
    return fallback if value is UNSET else (Decimal(value or 0))


def _target_legs(sides, edits, *, account, total):
    """The (account, signed amount) pairs to write as the category lines."""
    if edits.legs is not UNSET:
        if len(edits.legs) < 2:
            raise EditRefused(_("A split needs at least two categories."))
        return [(edits._accounts[a.id], amount) for a, amount in edits.legs]

    if edits.category_id is not UNSET:
        if sides.is_split and not edits.remove_split:
            # Folding a split into whatever single category the request happened
            # to carry would silently destroy the apportionment.
            raise EditRefused(
                _("This transaction is split across categories. Send its splits, or remove the split first."),
            )
        category = edits._accounts[edits.category_id]
        if category.id == account.id:
            raise EditRefused(_("A transaction cannot be categorized to the account it is in."))
        return [(category, total)]

    if edits.remove_split and sides.is_split:
        # No category named, so collapse onto the largest leg -- of the
        # categories the user chose, the likeliest one they meant.
        largest = max(sides.legs, key=lambda line: abs(line.dr_amount - line.cr_amount))
        return [(largest.account, total)]

    # Category untouched: keep the existing legs, re-scaled only if the total
    # moved. A plain transaction follows its total; a split cannot, because
    # there is no honest way to guess how the user wants the change apportioned.
    existing = [(line.account, line.dr_amount - line.cr_amount) for line in sides.legs]
    if not sides.is_split:
        return [(existing[0][0], total)]
    if total != sides.total:
        raise EditRefused(
            _("Change the amounts of this transaction's categories rather than its total, so they still add up."),
        )
    return existing


def _check_reconciled(sides, *, account, total):
    """
    Reconciliation is a fact about the home line.

    Its amount does not change when legs are re-apportioned, so re-splitting a
    reconciled transaction is fine; changing what the bank confirmed is not.
    """
    if not sides.home_line.is_reconciled:
        return
    if total != sides.total:
        raise EditRefused(_("This transaction is reconciled. Unreconcile it before changing its amount."))
    if account.id != sides.account.id:
        raise EditRefused(_("This transaction is reconciled. Unreconcile it before changing its account."))


def _check_bank_rules(entry, sides, edits, *, total):
    """The Bank Feed's field rules, so both pages refuse the same things."""
    bank_tx = sides.bank_tx
    if bank_tx is None or bank_tx.source != BankTransaction.SOURCE_PLAID:
        return
    if edits.date is not UNSET and edits.date != entry.entry_date:
        raise EditRefused(_("Your bank sets the date on this transaction."))
    if total != sides.total:
        raise EditRefused(_("Your bank sets the amount on this transaction."))


def _check_transfer(sides, legs):
    """
    Refuse an edit that would strand the real side of a transfer.

    Barely reachable from this page: a transfer's two legs share one entry, so it
    shows as a single row and `resolve_sides` always picks the non-mirror leg.
    It costs one call and covers the entry whose only feed row is a mirror.
    """
    if sides.bank_tx is None or len(legs) != 1:
        return
    if would_orphan_primary(sides.bank_tx, legs[0][0]):
        raise EditRefused(
            _("This is the mirror side of a transfer. Edit the original transaction to change its category."),
        )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _write(plan, edits, *, team):
    # Imported here, not at module scope: `apps.bank_feed` imports from this app,
    # and `transfer_mirror` already avoids the reverse import at module level for
    # the same reason. One local import keeps the direction explicit.
    from apps.bank_feed.services.splits import SplitError, write_lines

    entry, sides = plan.entry, plan.sides

    # The entry is saved before its lines, because `JournalLine.save()` resolves
    # its budget link from `journal_entry.entry_date` -- writing lines first
    # would file them under the month the transaction just left.
    if edits.date is not UNSET:
        entry.entry_date = edits.date
    if edits.description is not UNSET:
        entry.description = edits.description
    if edits.payee_name is not UNSET:
        entry.payee = _payee(edits.payee_name, team=team)
    entry.save()

    # Follow an account move before the lines are written: `write_lines` finds
    # the home line by account, so it has to be looking at the new one. Saved
    # individually rather than through `QuerySet.update()` so the audit signals
    # fire and the change shows up in the transaction's history.
    if plan.account.id != sides.account.id:
        home_line = sides.home_line
        home_line.account = plan.account
        home_line.journal_entry = entry
        home_line.save()

    try:
        write_lines(entry, plan.account, plan.legs, total=plan.total, team=team)
    except SplitError as exc:
        raise EditRefused(str(exc)) from exc

    _sync_bank_row(sides, entry, account=plan.account, total=plan.total)

    entry.refresh_from_db()
    return entry


def _payee(name, *, team):
    name = (name or "").strip()
    if not name:
        return None
    payee, _created = Payee.objects.get_or_create(team=team, name=name)
    return payee


def _sync_bank_row(sides, entry, *, account, total):
    """
    Keep the feed row telling the same story as the ledger.

    Without this the Transactions page and the Bank Feed disagree about the same
    transaction -- which is the failure mode that makes a second editor worse
    than no second editor.
    """
    bank_tx = sides.bank_tx
    if bank_tx is None:
        return

    bank_tx.posted_date = entry.entry_date
    bank_tx.description = entry.description
    bank_tx.merchant_name = entry.payee.name if entry.payee else ""
    bank_tx.account = account
    bank_tx.amount = total
    bank_tx.save()

    # Creates, moves or removes the counterpart leg. A no-op for a split, which
    # has no single counterpart to mirror.
    sync_transfer(bank_tx)
