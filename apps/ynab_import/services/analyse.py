"""
What a YNAB export means, worked out from what it contains.

The export is missing everything Koala Budget needs to know structurally: account
type, on-budget vs tracking, what any inflow was income *from*, which savings
categories are goals. Every rule here recovers one of those from the data, and
every one of them is shown to the user for review before anything is written --
which is why this module is pure. Nothing here touches the database, so the
preview and the apply cannot drift apart.

The rules and the measurements behind them are documented in
`docs/ynab-import-plan.md` (D1-D13); the figures are re-derivable from the sample
export by `docs/reference/checks/verify_ynab_assumptions.py`.
"""

import collections
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .parse import PlanRow, RegisterRow

ZERO = Decimal("0")

# YNAB's own structural buckets, neither of which is a category in KB's sense.
CREDIT_CARD_GROUP = "Credit Card Payments"  # D3: payment envelopes, never in the register
INFLOW_GROUP = "Inflow"  # D4: the single category every inflow carries
SAVINGS_GROUP = "Savings"  # D6: the categories that become goals
HIDDEN_GROUP = "Hidden Categories"  # D10: parked at the bottom of the board

# D6's carve-out: a valuation change wearing a savings label. Never a goal.
INVESTMENT_CATEGORY = "Investment Gain/Loss"

# What a category becomes in KB.
KIND_EXPENSE = "expense"
KIND_GOAL = "goal"
KIND_INVESTMENT = "investment"

# What an inflow payee becomes.
INCOME = "income"
NOT_INCOME = "not_income"

# Payees that are bookkeeping rather than earnings. Routing these to an income
# account would overstate income on every report.
NON_INCOME_PAYEES = frozenset(
    {
        "starting balance",
        "reconcile",
        "reconciliation balance adjustment",
        "reconciliation adjustment",
        "balance adjustment",
        "manual balance adjustment",
    }
)

# YNAB's own name for a correcting entry. Posts against the system equity account,
# which is exactly what that account is for.
RECONCILIATION_PAYEES = frozenset({"reconciliation balance adjustment", "reconcile", "manual balance adjustment"})

# An account with a zero balance and no transaction in this many days before the
# export's last one is left out of the Inbox by default.
DORMANT_DAYS = 365

# An inflow payee earns its own income account at this much recurrence, or this
# much money. Below both, it lands in "Other Income" -- which the user can undo on
# the mapping screen, where the counts and totals behind this are shown.
INCOME_PAYEE_MIN_ROWS = 3
INCOME_PAYEE_MIN_TOTAL = Decimal("1000")

OTHER_INCOME = "Other Income"

# The accounts an uncategorized row falls back to (D5). Two pairs rather than one:
# on a tracking account an uncategorized row is real investment activity, while on
# an on-budget account it is a category the user never picked, and calling that
# "investment income" would be a fiction.
INVESTMENT_INCOME = "Investment Income"
INVESTMENT_LOSS = "Investment Loss"
UNCATEGORIZED_INCOME = "Uncategorized Income"
UNCATEGORIZED_EXPENSE = "Uncategorized Expense"

# Group names for the generated chart of accounts. Singular nouns: a group names
# what each account in it *is* ("Credit Card"), so they read the same whether it
# holds one account or twelve. "Equity Adjustments" is the app's own system group
# and keeps the name every other chart uses.
GROUP_BANK = "Bank Account"
GROUP_TRACKING = "Tracking Account"
GROUP_CREDIT_CARD = "Credit Card"
GROUP_LOAN = "Loan"
GROUP_INCOME = "Income"
GROUP_INVESTMENT = "Investment"
GROUP_UNCATEGORIZED = "Uncategorized"
GROUP_EQUITY = "Equity Adjustments"

ASSET = "asset"
LIABILITY = "liability"

# The groups the accounts screen always offers, whether or not an inferred account
# landed in one: a user retyping an account as a debt needs "Loan" to pick from
# even when the export had no loan in it.
DEFAULT_ACCOUNT_GROUPS = (
    (GROUP_BANK, ASSET),
    (GROUP_TRACKING, ASSET),
    (GROUP_CREDIT_CARD, LIABILITY),
    (GROUP_LOAN, LIABILITY),
)


@dataclass(frozen=True)
class AccountFacts:
    """One account from the register's `Account` column, with its type inferred."""

    name: str
    account_type: str
    group: str
    on_budget: bool
    rows: int
    first_date: date
    last_date: date
    closing_balance: Decimal
    starting_balance: Decimal | None
    starting_date: date | None
    # Which rule decided the type, so the review screen can say why.
    reason: str
    # Whether its transactions land in the Inbox, before the user says otherwise.
    suggested_feed: bool = False


@dataclass(frozen=True)
class CategoryFacts:
    """One category from the Plan, in the Plan's own order (D11)."""

    group: str
    name: str
    order: int
    kind: str
    transfer_legs: int
    plain_rows: int
    total_assigned: Decimal
    total_activity: Decimal
    # For a goal: what has been saved into it, which becomes the goal's target (D6).
    saved: Decimal = ZERO


@dataclass(frozen=True)
class IncomePayeeFacts:
    """One payee seen on an inflow row (D4)."""

    payee: str
    count: int
    total: Decimal
    kind: str
    account: str


@dataclass
class Analysis:
    """
    Everything inferred from one export.

    Carries the parsed rows and the groupings alongside the inferences, because
    building the import needs both and deriving the transfer pairing twice would be
    two chances to derive it differently.
    """

    register: list[RegisterRow]
    plan: list[PlanRow]

    accounts: list[AccountFacts]
    categories: list[CategoryFacts]
    income_payees: list[IncomePayeeFacts]
    payees: list[str]

    months: list[date]
    # index -> index, both ways, for every paired transfer leg
    transfer_mates: dict[int, int]
    unmatched_transfers: list[int]
    split_groups: list[list[int]]
    opening_rows: list[int]

    warnings: list[str] = field(default_factory=list)

    @property
    def transfer_pairs(self) -> int:
        return len(self.transfer_mates) // 2

    @property
    def split_leg_indexes(self) -> set[int]:
        return {index for group in self.split_groups for index in group}

    @property
    def entry_count(self) -> int:
        """
        How many journal entries this export becomes.

        A transfer pair with one leg inside a split is not an entry of its own -- it
        merges into that split's entry, which is where the sample's 6,644 comes from
        rather than 6,647 (D8).
        """
        in_split = self.split_leg_indexes
        merged = sum(1 for a, b in self.transfer_mates.items() if a < b and (a in in_split or b in in_split))
        plain = sum(
            1
            for row in self.register
            if row.index not in in_split
            and row.index not in self.transfer_mates
            and row.index not in set(self.opening_rows)
        )
        return len(self.split_groups) + (self.transfer_pairs - merged) + len(self.opening_rows) + plain

    @property
    def date_range(self) -> tuple[date, date]:
        dates = [row.entry_date for row in self.register]
        return (min(dates), max(dates))


def analyse(register: list[RegisterRow], plan: list[PlanRow]) -> Analysis:
    """Read one export end to end. No database, no side effects."""
    warnings: list[str] = []

    split_groups = group_splits(register, warnings)
    transfer_mates, unmatched = pair_transfers(register)
    opening_rows = [row.index for row in register if row.is_starting_balance]

    if unmatched:
        warnings.append(
            f"{len(unmatched)} transfer line(s) have no matching other side and will be imported as "
            "ordinary transactions."
        )

    accounts = infer_accounts(register, plan)
    categories = infer_categories(register, plan)
    income_payees = infer_income_payees(register)

    return Analysis(
        register=register,
        plan=plan,
        accounts=accounts,
        categories=categories,
        income_payees=income_payees,
        payees=collect_payees(register),
        months=sorted({row.month for row in plan}),
        transfer_mates=transfer_mates,
        unmatched_transfers=unmatched,
        split_groups=split_groups,
        opening_rows=opening_rows,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Structure: transfers and splits (D8)
# ---------------------------------------------------------------------------


def pair_transfers(register: list[RegisterRow]) -> tuple[dict[int, int], list[int]]:
    """
    Match each transfer line to its other side.

    A YNAB transfer is exported as two lines, one in each account, each naming the
    other as `Transfer : <account>`. They are matched on account, counterpart, date
    and equal-and-opposite amount, so two transfers of the same size on the same day
    between the same pair of accounts still pair off one-to-one rather than
    collapsing into one.
    """
    legs = [row for row in register if row.transfer_account]

    index: dict[tuple, list[RegisterRow]] = collections.defaultdict(list)
    for row in legs:
        index[(row.account, row.transfer_account, row.entry_date, abs(row.net))].append(row)

    mates: dict[int, int] = {}
    for row in legs:
        if row.index in mates:
            continue
        key = (row.transfer_account, row.account, row.entry_date, abs(row.net))
        mate = next((m for m in index.get(key, []) if m.index not in mates and m.net == -row.net), None)
        if mate is not None and mate.index != row.index:
            mates[row.index] = mate.index
            mates[mate.index] = row.index

    unmatched = [row.index for row in legs if row.index not in mates]
    return mates, unmatched


def group_splits(register: list[RegisterRow], warnings: list[str] | None = None) -> list[list[int]]:
    """
    Collect the legs of each split transaction.

    YNAB numbers them in the memo (`Split (1/3)`), so the walk is: open a group on
    `(1/n)`, take the next expected `(k/n)` in the same account and date, and close
    at `(n/n)`. Grouping by account and date alone is not enough -- the sample has
    three days carrying two different splits on the same account, and one split whose
    legs are not contiguous in file order.
    """
    open_groups: dict[tuple, list[RegisterRow]] = {}
    groups: list[list[int]] = []
    orphans = 0

    for row in register:
        split = row.split
        if split is None:
            continue
        leg, of = split
        key = (row.account, row.entry_date, of)

        if leg == 1:
            open_groups[key] = [row]
        elif key in open_groups and len(open_groups[key]) == leg - 1:
            open_groups[key].append(row)
        else:
            # A leg we cannot place: its parent is missing or the file is out of
            # order. It imports as an ordinary transaction rather than being dropped.
            orphans += 1
            continue

        if len(open_groups.get(key, [])) == of:
            groups.append([r.index for r in open_groups.pop(key)])

    leftover = sum(len(rows) for rows in open_groups.values())
    if (orphans or leftover) and warnings is not None:
        warnings.append(
            f"{orphans + leftover} split line(s) could not be matched to a parent transaction and will be "
            "imported on their own."
        )

    return groups


# ---------------------------------------------------------------------------
# Accounts (D5, D7)
# ---------------------------------------------------------------------------


def credit_card_accounts(plan: list[PlanRow]) -> set[str]:
    """
    The user's credit cards, named by the Plan's Credit Card Payments group.

    Those categories never appear in the register -- they are pure YNAB machinery --
    but their names are exactly the card accounts, which makes the Plan a free and
    exact credit-card list (D3).
    """
    return {row.category for row in plan if row.category_group == CREDIT_CARD_GROUP and row.category}


def infer_accounts(register: list[RegisterRow], plan: list[PlanRow]) -> list[AccountFacts]:
    """
    Every account in the register, typed.

    Type (D7), in order: a card named by the Plan is a liability; an account whose
    running balance is never positive is a liability; a negative starting balance is
    a liability; everything else is an asset. On-budget vs tracking (D5) comes from
    whether any of the account's rows carries a category.
    """
    cards = credit_card_accounts(plan)

    rows_by_account: dict[str, list[RegisterRow]] = collections.defaultdict(list)
    for row in register:
        rows_by_account[row.account].append(row)

    latest = max((row.entry_date for row in register), default=None)

    facts = []
    for name, rows in rows_by_account.items():
        ordered = sorted(rows, key=lambda r: (r.entry_date, r.index))
        running = ZERO
        peak = None
        for row in ordered:
            running += row.net
            peak = running if peak is None else max(peak, running)

        opening = next((row for row in ordered if row.is_starting_balance), None)
        on_budget = any(row.category for row in rows)

        if name in cards:
            account_type, reason = LIABILITY, "named by the Plan's Credit Card Payments group"
        elif peak is not None and peak <= ZERO and running < ZERO:
            account_type, reason = LIABILITY, "the balance is never positive"
        elif opening is not None and opening.net < ZERO:
            account_type, reason = LIABILITY, "the starting balance is negative"
        else:
            account_type, reason = ASSET, "the balance is positive"

        facts.append(
            AccountFacts(
                name=name,
                account_type=account_type,
                group=_suggested_group(account_type, name, cards, on_budget),
                on_budget=on_budget,
                rows=len(rows),
                first_date=ordered[0].entry_date,
                last_date=ordered[-1].entry_date,
                closing_balance=running,
                starting_balance=opening.net if opening else None,
                starting_date=opening.entry_date if opening else None,
                reason=reason,
                suggested_feed=suggested_feed(account_type, on_budget, running, ordered[-1].entry_date, latest),
            )
        )

    return sorted(facts, key=lambda f: (f.account_type != ASSET, not f.on_budget, f.name))


def suggested_feed(account_type: str, on_budget: bool, closing: Decimal, last_date: date, latest: date | None) -> bool:
    """
    Whether an account's transactions should land in the Inbox by default.

    An everyday account or a debt has a statement to work through; a tracking account
    (a pension, a GIC) does not. An account emptied and left alone for a year is
    finished with -- a feed for it would put an Inbox card in front of the user for
    an account they no longer use.
    """
    if not (on_budget or account_type == LIABILITY):
        return False
    dormant = closing == ZERO and latest is not None and (latest - last_date).days > DORMANT_DAYS
    return not dormant


def _suggested_group(account_type: str, name: str, cards: set[str], on_budget: bool) -> str:
    if account_type == LIABILITY:
        return GROUP_CREDIT_CARD if name in cards else GROUP_LOAN
    return GROUP_BANK if on_budget else GROUP_TRACKING


# ---------------------------------------------------------------------------
# Categories (D3, D6, D10, D11)
# ---------------------------------------------------------------------------


def infer_categories(register: list[RegisterRow], plan: list[PlanRow]) -> list[CategoryFacts]:
    """
    Every category the Plan carries, in the Plan's own order, with what it becomes.

    The Plan lists its groups and categories in one identical order in every month --
    the user's own arrangement -- so that order becomes `sort_order` and the imported
    chart of accounts arrives arranged the way they already know it (D11).

    Credit Card Payments are dropped here: they are YNAB's internal payment
    envelopes, never appear in the register, and have nothing to map onto (D3).
    """
    transfer_legs: dict[tuple[str, str], int] = collections.Counter()
    plain_rows: dict[tuple[str, str], int] = collections.Counter()
    saved: dict[tuple[str, str], Decimal] = collections.defaultdict(lambda: ZERO)

    for row in register:
        if not row.category:
            continue
        key = (row.category_group, row.category)
        if row.transfer_account:
            transfer_legs[key] += 1
            # A categorised transfer is money moved *into* savings, which the register
            # writes as an outflow from the funding account.
            saved[key] += -row.net
        else:
            plain_rows[key] += 1

    assigned: dict[tuple[str, str], Decimal] = collections.defaultdict(lambda: ZERO)
    activity: dict[tuple[str, str], Decimal] = collections.defaultdict(lambda: ZERO)
    for row in plan:
        assigned[row.key] += row.assigned
        activity[row.key] += row.activity

    facts = []
    for order, key in enumerate(_plan_order(plan)):
        group, name = key
        if group == CREDIT_CARD_GROUP:
            continue
        facts.append(
            CategoryFacts(
                group=group,
                name=name,
                order=order,
                kind=_category_kind(group, name, transfer_legs[key]),
                transfer_legs=transfer_legs[key],
                plain_rows=plain_rows[key],
                total_assigned=assigned[key],
                total_activity=activity[key],
                saved=saved[key],
            )
        )

    # A category used in the register but absent from the Plan still needs an account
    # to post against, or its rows would have nowhere to go.
    known = {(f.group, f.name) for f in facts}
    extra = sorted({(r.category_group, r.category) for r in register if r.category} - known - {(INFLOW_GROUP, "")})
    for offset, (group, name) in enumerate(extra):
        if group in (INFLOW_GROUP, CREDIT_CARD_GROUP):
            continue
        facts.append(
            CategoryFacts(
                group=group,
                name=name,
                order=len(facts) + offset,
                kind=_category_kind(group, name, transfer_legs[(group, name)]),
                transfer_legs=transfer_legs[(group, name)],
                plain_rows=plain_rows[(group, name)],
                total_assigned=ZERO,
                total_activity=ZERO,
                saved=saved[(group, name)],
            )
        )

    return facts


def _plan_order(plan: list[PlanRow]) -> list[tuple[str, str]]:
    """The Plan's group/category order, taken from its first month."""
    order: list[tuple[str, str]] = []
    seen = set()
    for row in plan:
        if row.key not in seen:
            seen.add(row.key)
            order.append(row.key)
    return order


def _category_kind(group: str, name: str, transfer_legs: int) -> str:
    """
    What a category becomes: an expense account, a goal, or investment activity.

    A savings category funded by transfers is a goal -- `Emergency Fund`, `House`,
    `RESP` map one-to-one onto what `budget.Goal` exists for (D6). One that is never
    funded by a transfer is a spending category wearing a savings label
    (`Savings Expenses`), so it stays an expense. `Investment Gain/Loss` is neither:
    it is a valuation change, and it goes to the investment accounts.
    """
    if group == SAVINGS_GROUP and name == INVESTMENT_CATEGORY:
        return KIND_INVESTMENT
    if group == SAVINGS_GROUP and transfer_legs > 0:
        return KIND_GOAL
    return KIND_EXPENSE


# ---------------------------------------------------------------------------
# Income (D4)
# ---------------------------------------------------------------------------


def infer_income_payees(register: list[RegisterRow]) -> list[IncomePayeeFacts]:
    """
    The payees behind every inflow, clustered into suggested income accounts.

    YNAB gives every inflow the single category `Inflow: Ready to Assign`, so the
    payee is the only thing in the export that says what the money *was*. Recurring
    or large payees earn their own income account; the rest land in "Other Income".
    Bookkeeping payees are suggested as "not income" -- a starting balance or a
    reconciliation adjustment is not earnings, and importing it as income would
    overstate every income figure the app shows.
    """
    counts: dict[str, int] = collections.Counter()
    totals: dict[str, Decimal] = collections.defaultdict(lambda: ZERO)

    for row in register:
        if row.category_group != INFLOW_GROUP or row.is_starting_balance or row.transfer_account:
            continue
        counts[row.payee] += 1
        totals[row.payee] += row.net

    facts = []
    for payee, count in counts.items():
        normalised = payee.strip().lower()
        if normalised in NON_INCOME_PAYEES:
            kind, account = NOT_INCOME, ""
        elif count >= INCOME_PAYEE_MIN_ROWS or totals[payee] >= INCOME_PAYEE_MIN_TOTAL:
            kind, account = INCOME, income_account_name(payee)
        else:
            kind, account = INCOME, OTHER_INCOME
        facts.append(IncomePayeeFacts(payee=payee, count=count, total=totals[payee], kind=kind, account=account))

    return sorted(facts, key=lambda f: (-f.count, f.payee))


def income_account_name(payee: str) -> str:
    """A payee as an income account name -- trimmed, collapsed, and never blank."""
    name = re.sub(r"\s+", " ", payee).strip()[:200]
    return name or OTHER_INCOME


def collect_payees(register: list[RegisterRow]) -> list[str]:
    """
    Every real payee in the export.

    Transfers name an account rather than a payee, and `Starting Balance` is YNAB's
    own label for an opening balance -- neither is a party the user pays.
    """
    payees = {
        row.payee.strip()[:200]
        for row in register
        if row.payee.strip() and not row.transfer_account and not row.is_starting_balance
    }
    return sorted(payees)
