"""
Reading a journal entry the way a user sees a transaction.

The app hides double-entry, so nothing in the UI may say "debit" or "credit". A
transaction is instead an **account** -- where the money sat, an asset or a
liability -- and a **category**, or several of them when it is a split. This
module is the one place that decides which of an entry's lines is which.

The structural invariant that makes it possible: every entry this editor writes
has exactly one line on one side and one or more on the other. `apply_splits`
(`apps.bank_feed.services.splits`) writes that shape, `apps.ynab_import` imports
it, and `TransactionRowSerializer` renders it. The one-line side is the account;
the rest are the legs.

Getting this wrong is not a cosmetic bug -- an edit applied to the wrong line
moves money between the wrong two accounts -- so the rules below are ordered and
exhaustive rather than heuristic, and the ambiguous cases are broken by a
deterministic tie rather than left to line ordering.
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY

#: The account types a transaction's money side can be. An expense or income
#: account is a category; equity is only ever the far side of an opening balance
#: or a goal, never the account a user thinks of the transaction as "in".
MONEY_TYPES = (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)


class UnsupportedEntry(Exception):
    """
    An entry whose shape this editor cannot safely present as one transaction.

    The message is shown to the user, so it says what is wrong rather than
    naming the invariant that failed.
    """


@dataclass(frozen=True)
class Sides:
    """An entry split into the account it happened in and what it was for."""

    #: The line on the money account -- the one the user thinks of as "where".
    home_line: object
    #: The other lines. One for a plain transaction, several for a split.
    legs: list
    #: The feed row that owns this entry, if any. Never a mirror leg.
    bank_tx: object | None
    #: Mirror legs sharing this entry (the counterpart side of a transfer).
    mirror_txs: list
    #: True when the entry apportions one transaction across several categories.
    is_split: bool
    #: False when no line looks like a money account, so the modal can say so.
    normal: bool

    @property
    def account(self):
        return self.home_line.account

    @property
    def inflow(self) -> Decimal:
        """Money into the account. Debit on the home line, in user words."""
        return self.home_line.dr_amount

    @property
    def outflow(self) -> Decimal:
        """Money out of the account. Credit on the home line."""
        return self.home_line.cr_amount

    @property
    def total(self) -> Decimal:
        """The signed transaction total: positive is an outflow.

        The same convention `apps.bank_feed.services.splits` and the Plaid feed
        use, so a total means the same thing on both sides of the app.
        """
        return self.outflow - self.inflow


def _account_type(line) -> str:
    return line.account.account_group.account_type


def _is_money(line) -> bool:
    return _account_type(line) in MONEY_TYPES


def resolve_sides(entry) -> Sides:
    """
    Split `entry`'s lines into its account line and its category legs.

    Expects `lines__account__account_group` and `bank_feed_transactions` to be
    loaded by the caller; it does no prefetching of its own so a batch can pay
    for the query once.
    """
    lines = list(entry.lines.all())
    if len(lines) < 2:
        raise UnsupportedEntry(
            "This transaction's ledger entry is incomplete and cannot be edited here.",
        )

    feed_rows = list(entry.bank_feed_transactions.all())
    bank_tx = next((tx for tx in feed_rows if not tx.is_transfer_mirror), None)
    mirror_txs = [tx for tx in feed_rows if tx.is_transfer_mirror]

    home_line, normal = _pick_home_line(lines, bank_tx)
    legs = [line for line in lines if line.id != home_line.id]

    return Sides(
        home_line=home_line,
        legs=legs,
        bank_tx=bank_tx,
        mirror_txs=mirror_txs,
        is_split=len(lines) > 2,
        normal=normal,
    )


def _pick_home_line(lines, bank_tx):
    """
    Which line is the account side, and whether that reading is a normal one.

    Ordered; the first rule that fires wins.
    """
    # 1. A feed row names its own account. This is also what settles a transfer:
    #    both legs share one entry, and the primary's account is the one the
    #    user opened the transaction from.
    if bank_tx is not None:
        match = next((line for line in lines if line.account_id == bank_tx.account_id), None)
        if match is not None:
            return match, _is_money(match)

    # 2. A split's shape decides it: one line on one side, several on the other.
    if len(lines) > 2:
        debits = [line for line in lines if line.dr_amount > 0]
        credits = [line for line in lines if line.cr_amount > 0]
        for side in (debits, credits):
            if len(side) == 1:
                return side[0], _is_money(side[0])
        raise UnsupportedEntry(
            "This transaction is spread across several accounts on both sides and cannot be edited here.",
        )

    # 3. Exactly one money account: the ordinary purchase, paycheque, credit-card
    #    charge, and the opening balance against the system equity account.
    money = [line for line in lines if _is_money(line)]
    if len(money) == 1:
        return money[0], True

    # 4. Two money accounts -- a transfer with no feed row. Prefer the one with a
    #    feed; failing that the credit line, because money leaving an account is
    #    how a user describes a transfer ("I moved $500 *from* chequing").
    if len(money) == 2:
        fed = [line for line in money if line.account.has_feed]
        pool = fed if len(fed) == 1 else money
        credit = next((line for line in pool if line.cr_amount > 0), None)
        return credit or min(pool, key=lambda line: line.id), True

    # 5. Neither side is a money account -- a mis-categorized expense-to-expense
    #    pair, say. Still editable; the modal notes that the labels are a guess.
    #    `>=` rather than testing each line against zero, so a $0.00 entry (where
    #    every amount is zero) still resolves, matching TransactionRowSerializer.
    first, second = lines
    return (first if first.dr_amount >= second.dr_amount else second), False
