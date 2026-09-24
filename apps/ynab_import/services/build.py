"""
Turning an analysed export plus the user's answers into exactly what will be written.

Pure, like `analyse`: given the same export and the same choices this returns the
same `ImportPlan`, which is what lets the preview screen promise what the apply
step does. `apply.py` writes the plan and decides nothing.

Every register row lands in exactly one journal entry, and every entry balances --
both are asserted here rather than discovered by the database.
"""

import collections
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .analyse import (
    ASSET,
    GROUP_BANK,
    GROUP_CREDIT_CARDS,
    GROUP_EQUITY,
    GROUP_INCOME,
    GROUP_INVESTMENT,
    GROUP_TRACKING,
    GROUP_UNCATEGORIZED,
    HIDDEN_GROUP,
    INCOME,
    INFLOW_GROUP,
    INVESTMENT_INCOME,
    INVESTMENT_LOSS,
    KIND_EXPENSE,
    KIND_GOAL,
    KIND_INVESTMENT,
    LIABILITY,
    NOT_INCOME,
    OTHER_INCOME,
    RECONCILIATION_PAYEES,
    UNCATEGORIZED_EXPENSE,
    UNCATEGORIZED_INCOME,
    Analysis,
)
from .parse import RegisterRow

ZERO = Decimal("0")
CENT = Decimal("0.01")

INCOME_TYPE = "income"
EXPENSE_TYPE = "expense"
EQUITY_TYPE = "goal"  # KB's account-type code for equity

# The offset every opening balance and reconciliation adjustment posts against.
# Same name the onboarding template and `onboarding.services.opening` use, so a
# YNAB-imported book behaves like any other from there on.
EQUITY_ACCOUNT = "Reconciliation Adjustments"

# Account numbers follow the project convention and double as display order.
NUMBER_BASE = {ASSET: 1000, LIABILITY: 2000, EQUITY_TYPE: 3000, INCOME_TYPE: 4000, EXPENSE_TYPE: 5000}

# Goal accounts live in a non-system group of their own, never in the system
# "Equity Adjustments" group the reconciliation offset sits in.
GROUP_GOALS = "Goals"

# D10: hidden categories keep their own group, ordered after every live one, so the
# board's Type -> Group -> Account ordering parks them at the bottom of the section
# instead of interleaving finished categories with current ones.
HIDDEN_GROUP_ORDER = 9000


class BuildError(ValueError):
    """Something the user needs told about. The message is user-facing."""


@dataclass(frozen=True)
class PlannedGroup:
    name: str
    account_type: str
    sort_order: int
    is_system: bool = False
    description: str = ""


@dataclass(frozen=True)
class PlannedAccount:
    name: str
    account_type: str
    group: str
    sort_order: int
    has_feed: bool = False
    is_system: bool = False
    institution: str = ""

    @property
    def key(self) -> tuple[str, str]:
        """Name is only unique per type -- an asset `RESP` and an expense `RESP` differ."""
        return (self.account_type, self.name)


@dataclass(frozen=True)
class PlannedLine:
    account: tuple[str, str]
    dr: Decimal
    cr: Decimal
    is_reconciled: bool = False
    is_cleared: bool = False


@dataclass(frozen=True)
class PlannedEntry:
    entry_date: date
    description: str
    payee: str | None
    lines: tuple[PlannedLine, ...]

    @property
    def balances(self) -> bool:
        return sum(line.dr for line in self.lines) == sum(line.cr for line in self.lines)


@dataclass(frozen=True)
class PlannedOpening:
    """One `Starting Balance` row. The amount is signed for the account's own type."""

    account: tuple[str, str]
    amount: Decimal
    as_of: date


@dataclass(frozen=True)
class PlannedBudget:
    category: tuple[str, str]
    month: date
    amount: Decimal


@dataclass(frozen=True)
class PlannedGoal:
    name: str
    target_amount: Decimal
    allocations: tuple[tuple[date, Decimal], ...]
    # The goal's own equity account, planned with the rest of the chart so spending
    # from the savings category can post to it.
    account: tuple[str, str] | None = None
    # A savings category spent out entirely (the house was bought) arrives closed,
    # with its history, rather than being skipped.
    closed: bool = False


@dataclass
class ImportPlan:
    groups: list[PlannedGroup]
    accounts: list[PlannedAccount]
    payees: list[str]
    institutions: list[str]
    entries: list[PlannedEntry]
    openings: list[PlannedOpening]
    budgets: list[PlannedBudget]
    goals: list[PlannedGoal]
    notes: list[str] = field(default_factory=list)
    # Counts the summary screen reports, so the user is told what was inferred
    # rather than finding it later.
    stats: dict = field(default_factory=dict)
    # The choices this plan was built from, and where each YNAB account ended up.
    # The reconciliation reads both: an account can be renamed on the review screen,
    # so its name is not enough to find it again.
    choices: "Choices | None" = None
    account_keys: dict = field(default_factory=dict)
    category_keys: dict = field(default_factory=dict)
    transfer_activity: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Choices -- the wizard's answers, validated against the analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountChoice:
    name: str
    account_type: str
    group: str
    institution: str = ""
    skip: bool = False


@dataclass(frozen=True)
class IncomeChoice:
    kind: str
    account: str


@dataclass(frozen=True)
class CategoryChoice:
    kind: str
    name: str


@dataclass(frozen=True)
class Choices:
    accounts: dict[str, AccountChoice]
    income: dict[str, IncomeChoice]
    categories: dict[str, CategoryChoice]


def category_key(group: str, name: str) -> str:
    """A stable wire key for a category. `\\x1f` cannot occur in a YNAB name."""
    return f"{group}\x1f{name}"


def default_choices(analysis: Analysis) -> Choices:
    """Everything the inference suggests, before the user touches any of it."""
    return Choices(
        accounts={
            facts.name: AccountChoice(name=facts.name, account_type=facts.account_type, group=facts.group)
            for facts in analysis.accounts
        },
        income={facts.payee: IncomeChoice(kind=facts.kind, account=facts.account) for facts in analysis.income_payees},
        categories={
            category_key(facts.group, facts.name): CategoryChoice(kind=facts.kind, name=facts.name)
            for facts in analysis.categories
        },
    )


def parse_choices(analysis: Analysis, raw) -> Choices:
    """
    Read the wizard's payload over the defaults.

    The client sends edits, not a chart of accounts: anything it names that the
    export does not contain is ignored, and every value is checked against what this
    export can actually produce. That is what stops a crafted payload from inventing
    an account type or pointing a category at something the user never saw.
    """
    defaults = default_choices(analysis)
    if not isinstance(raw, dict):
        return defaults

    accounts = dict(defaults.accounts)
    for name, value in _items(raw.get("accounts")):
        if name not in accounts or not isinstance(value, dict):
            continue
        current = accounts[name]
        account_type = value.get("account_type")
        accounts[name] = AccountChoice(
            name=_clean_name(value.get("name"), current.name),
            account_type=account_type if account_type in (ASSET, LIABILITY) else current.account_type,
            group=_clean_name(value.get("group"), current.group),
            institution=_clean_name(value.get("institution"), "", allow_blank=True),
            skip=bool(value.get("skip")),
        )

    income = dict(defaults.income)
    for payee, value in _items(raw.get("income")):
        if payee not in income or not isinstance(value, dict):
            continue
        current = income[payee]
        kind = value.get("kind") if value.get("kind") in (INCOME, NOT_INCOME) else current.kind
        account = _clean_name(value.get("account"), current.account or OTHER_INCOME)
        income[payee] = IncomeChoice(kind=kind, account=account if kind == INCOME else "")

    categories = dict(defaults.categories)
    for key, value in _items(raw.get("categories")):
        if key not in categories or not isinstance(value, dict):
            continue
        current = categories[key]
        kind = value.get("kind") if value.get("kind") in (KIND_EXPENSE, KIND_GOAL, KIND_INVESTMENT) else current.kind
        categories[key] = CategoryChoice(kind=kind, name=_clean_name(value.get("name"), current.name))

    return Choices(accounts=accounts, income=income, categories=categories)


def _items(value):
    return value.items() if isinstance(value, dict) else []


def _clean_name(value, fallback: str, allow_blank: bool = False) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.split())[:200]
    if not cleaned and not allow_blank:
        return fallback
    return cleaned


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------


class _Chart:
    """
    The chart of accounts being assembled, with groups created on first use.

    Two collision rules, both of them the app's own: a book cannot have two account
    groups with the same name (whatever their types), and an account name is unique
    within its type. Rather than fail on either, a colliding name is qualified --
    losing a category to a silent merge would be worse than an ugly name.
    """

    TYPE_LABELS = {ASSET: "Assets", LIABILITY: "Debt", INCOME_TYPE: "Income", EXPENSE_TYPE: "Expenses"}

    def __init__(self):
        self.groups: dict[str, PlannedGroup] = {}
        self.accounts: dict[tuple[str, str], PlannedAccount] = {}
        self._next: dict[str, int] = {}

    def group(self, name: str, account_type: str, sort_order: int | None = None, is_system: bool = False) -> str:
        name = name.strip()[:200] or self.TYPE_LABELS.get(account_type, "Accounts")
        existing = self.groups.get(name)
        if existing is not None and existing.account_type != account_type:
            name = f"{name} ({self.TYPE_LABELS.get(account_type, account_type)})"[:200]
            existing = self.groups.get(name)

        if existing is None:
            order = sort_order if sort_order is not None else len(self.groups) * 10
            self.groups[name] = PlannedGroup(
                name=name, account_type=account_type, sort_order=order, is_system=is_system
            )
        return name

    def account(
        self,
        name: str,
        account_type: str,
        group: str,
        *,
        has_feed: bool = False,
        is_system: bool = False,
        institution: str = "",
        sort_order: int | None = None,
        distinct: bool = False,
    ) -> tuple[str, str]:
        """
        Add an account, or return the one already there.

        `distinct=True` means "this is its own thing": if the name is taken by an
        account of the same type in another group, it is qualified with the group
        name rather than merged into it. Categories want that -- two YNAB groups can
        both hold a `Gifts` -- while several payees mapping onto one `Other Income`
        want the merge.
        """
        name = name.strip()[:200] or "Unnamed"
        key = (account_type, name)
        existing = self.accounts.get(key)

        if existing is not None and distinct and existing.group != group:
            name = f"{name} ({group})"[:200]
            key = (account_type, name)
            existing = self.accounts.get(key)

        if existing is None:
            if sort_order is None:
                base = NUMBER_BASE[account_type]
                sort_order = base + self._next.get(account_type, 0) * 10
                self._next[account_type] = self._next.get(account_type, 0) + 1
            self.accounts[key] = PlannedAccount(
                name=name,
                account_type=account_type,
                group=group,
                sort_order=sort_order,
                has_feed=has_feed,
                is_system=is_system,
                institution=institution,
            )
        return key


def build(analysis: Analysis, choices: Choices | None = None) -> ImportPlan:
    """Everything the import will write, decided before anything is written."""
    choices = choices or default_choices(analysis)
    chart = _Chart()
    notes: list[str] = list(analysis.warnings)

    # Equity first: the offset for opening balances and reconciliation adjustments
    # exists whatever else the export contains.
    equity_group = chart.group(GROUP_EQUITY, EQUITY_TYPE, sort_order=0, is_system=True)
    equity = chart.account(EQUITY_ACCOUNT, EQUITY_TYPE, equity_group, is_system=True, sort_order=3000)

    accounts = _build_accounts(analysis, choices, chart)
    categories = _build_categories(analysis, choices, chart)
    income = _build_income(analysis, choices, chart)

    resolver = _Resolver(
        analysis=analysis,
        choices=choices,
        chart=chart,
        accounts=accounts,
        categories=categories,
        income=income,
        equity=equity,
    )

    entries, openings, allocations, consumed = _build_entries(analysis, resolver)
    goals, spent_goals = _build_goals(analysis, choices, allocations, categories)
    # Goal categories never get a `Budget`: what was assigned to them became goal allocations.
    budget_categories = {key: account for key, account in categories.items() if not resolver.is_goal_category(*key)}
    budgets, budget_stats = _build_budgets(analysis, choices, budget_categories, entries, income)

    notes.extend(resolver.notes)
    notes.extend(_notes(analysis, choices, goals, spent_goals, budget_stats, resolver))
    plan = ImportPlan(
        groups=sorted(chart.groups.values(), key=lambda g: (g.account_type, g.sort_order, g.name)),
        accounts=sorted(chart.accounts.values(), key=lambda a: (a.account_type, a.sort_order, a.name)),
        payees=analysis.payees,
        institutions=sorted({c.institution for c in choices.accounts.values() if c.institution}),
        entries=entries,
        openings=openings,
        budgets=budgets,
        goals=goals,
        notes=notes,
        choices=choices,
        account_keys=accounts,
        category_keys=categories,
        transfer_activity=dict(resolver.transfer_activity),
    )
    resolver.spent_goals = spent_goals
    plan.stats = _stats(analysis, plan, resolver, budget_stats)
    assert_sound(plan, analysis, consumed)
    return plan


def _build_accounts(analysis: Analysis, choices: Choices, chart: _Chart) -> dict[str, tuple[str, str]]:
    """The register's own accounts, typed and grouped as the review screen left them."""
    keys: dict[str, tuple[str, str]] = {}
    for facts in analysis.accounts:
        choice = choices.accounts.get(facts.name)
        if choice is None or choice.skip:
            continue
        group = chart.group(choice.group or _default_group(choice.account_type, facts.on_budget), choice.account_type)
        keys[facts.name] = chart.account(
            choice.name,
            choice.account_type,
            group,
            # A tracking account (a pension, a GIC, home equity) has no bank feed to
            # connect; an everyday account does.
            has_feed=facts.on_budget or choice.account_type == LIABILITY,
            institution=choice.institution,
        )
    return keys


def _default_group(account_type: str, on_budget: bool) -> str:
    if account_type == LIABILITY:
        return GROUP_CREDIT_CARDS
    return GROUP_BANK if on_budget else GROUP_TRACKING


def _build_categories(analysis: Analysis, choices: Choices, chart: _Chart) -> dict[tuple[str, str], tuple[str, str]]:
    """
    An expense account per spending category, in the Plan's own order.

    A goal category gets the goal's own equity account instead: spending from a
    savings category is spending from the goal (docs/goals-envelopes-plan.md §4.7),
    and its *assignments* become goal allocations rather than a budget.
    """
    keys: dict[tuple[str, str], tuple[str, str]] = {}
    for facts in analysis.categories:
        choice = choices.categories.get(category_key(facts.group, facts.name))
        kind = choice.kind if choice else facts.kind
        if kind == KIND_INVESTMENT:
            continue
        if kind == KIND_GOAL:
            keys[(facts.group, facts.name)] = chart.account(
                f"Goal: {_goal_name(facts, choice)}",
                EQUITY_TYPE,
                chart.group(GROUP_GOALS, EQUITY_TYPE, sort_order=10),
                sort_order=NUMBER_BASE[EQUITY_TYPE] + 100 + facts.order * 10,
                distinct=True,
            )
            continue

        group = chart.group(
            facts.group,
            EXPENSE_TYPE,
            sort_order=HIDDEN_GROUP_ORDER if facts.group == HIDDEN_GROUP else facts.order,
        )
        keys[(facts.group, facts.name)] = chart.account(
            choice.name if choice else facts.name,
            EXPENSE_TYPE,
            group,
            sort_order=NUMBER_BASE[EXPENSE_TYPE] + facts.order * 10,
            # Two YNAB groups can each hold a `Gifts`; merging them would silently
            # lose a category the user still sees in the review screen.
            distinct=True,
        )
    return keys


def _build_income(analysis: Analysis, choices: Choices, chart: _Chart) -> dict[str, tuple[str, str] | None]:
    """
    An income account per payee the user kept as income.

    `None` means "not income": those rows post against the equity offset, which is
    what a reconciliation adjustment or a balance correction actually is.
    """
    group = chart.group(GROUP_INCOME, INCOME_TYPE)
    keys: dict[str, tuple[str, str] | None] = {}
    for facts in analysis.income_payees:
        choice = choices.income.get(facts.payee)
        kind = choice.kind if choice else facts.kind
        if kind == NOT_INCOME:
            keys[facts.payee] = None
            continue
        name = (choice.account if choice else facts.account) or OTHER_INCOME
        keys[facts.payee] = chart.account(name, INCOME_TYPE, group)
    return keys


class _Resolver:
    """
    Where the counter-side of a row goes.

    Kept as an object rather than a pile of arguments because the fallback accounts
    are created on first use -- an export with no uncategorized rows should not
    produce an "Uncategorized Expense" account the user then has to look at.
    """

    def __init__(self, *, analysis, choices, chart, accounts, categories, income, equity):
        self.analysis = analysis
        self.choices = choices
        self.chart = chart
        self.accounts = accounts
        self.categories = categories
        self.income = income
        self.equity = equity
        self.notes: list[str] = []
        self.dropped_transfer_categories = 0
        self.zero_openings = 0
        self.spent_goals = 0
        # Goal funding, by (group, category, month), and -- in the same shape -- all
        # the category activity that rode on a transfer leg. No transfer can post to
        # a category account without misstating net worth, so the reconciliation
        # subtracts the second: the deviation is measured rather than hidden.
        self.allocations: dict[tuple[str, str, date], Decimal] = collections.defaultdict(lambda: ZERO)
        self.transfer_activity: dict[tuple[str, str, date], Decimal] = collections.defaultdict(lambda: ZERO)
        self.kinds = {
            (facts.group, facts.name): (
                choices.categories[category_key(facts.group, facts.name)].kind
                if category_key(facts.group, facts.name) in choices.categories
                else facts.kind
            )
            for facts in analysis.categories
        }
        self.tracking = {facts.name for facts in analysis.accounts if not facts.on_budget}

    def is_goal_category(self, group: str, name: str) -> bool:
        return self.kinds.get((group, name)) == KIND_GOAL

    def note_transfer_leg(self, row: RegisterRow):
        """
        A category on a transfer leg is YNAB's idiom for "move this money *and*
        record it as budgeted".

        A savings category survives as a goal allocation. Anything else cannot be
        kept: posting a move between the user's own accounts to a spending category
        would misstate net worth, so the money still moves and the category is
        dropped -- counted here, reported in the summary, and subtracted by the
        reconciliation so the remaining comparison stays exact.
        """
        if not row.category:
            return
        key = (row.category_group, row.category, row.month)
        self.transfer_activity[key] += row.net
        if self.is_goal_category(row.category_group, row.category):
            self.allocations[key] += -row.net
        else:
            self.dropped_transfer_categories += 1

    def account_for(self, row: RegisterRow) -> tuple[str, str] | None:
        """The account line for the row's own account, or None when it was dropped."""
        return self.accounts.get(row.account)

    def investment(self, inflow: bool) -> tuple[str, str]:
        """
        Growth and loss on a tracking account (D5).

        A TFSA's interest or a mortgage's principal has no counter-account anywhere in
        the export, and burying it in equity would understate income -- these are real
        economic events, so they get real income and expense accounts.
        """
        if inflow:
            return self.chart.account(INVESTMENT_INCOME, INCOME_TYPE, self.chart.group(GROUP_INCOME, INCOME_TYPE))
        return self.chart.account(INVESTMENT_LOSS, EXPENSE_TYPE, self.chart.group(GROUP_INVESTMENT, EXPENSE_TYPE))

    def uncategorized(self, inflow: bool) -> tuple[str, str]:
        """
        A row on an everyday account that YNAB never categorised.

        Calling that investment activity would be a fiction, so it lands somewhere
        obvious that the user can re-categorise from the transactions page.
        """
        if inflow:
            return self.chart.account(UNCATEGORIZED_INCOME, INCOME_TYPE, self.chart.group(GROUP_INCOME, INCOME_TYPE))
        return self.chart.account(
            UNCATEGORIZED_EXPENSE, EXPENSE_TYPE, self.chart.group(GROUP_UNCATEGORIZED, EXPENSE_TYPE)
        )

    def counter_for(self, row: RegisterRow) -> tuple[str, str]:
        """
        What the other side of an ordinary row is.

        Order matters. An inflow is answered by the payee mapping, because YNAB never
        categorises income -- every inflow carries the one category `Ready to Assign`,
        which says nothing. Then the row's own category, which is the whole point of
        having categorised in YNAB. Only a row with no category at all falls back, and
        what it falls back to depends on the account it is in.
        """
        inflow = row.net > ZERO

        if row.category_group == INFLOW_GROUP:
            mapped = self.income.get(row.payee, _MISSING)
            if mapped is _MISSING:
                # A payee the analysis never saw: an inflow leg inside a split, say.
                return self.chart.account(OTHER_INCOME, INCOME_TYPE, self.chart.group(GROUP_INCOME, INCOME_TYPE))
            return mapped if mapped is not None else self.equity

        if row.category:
            key = (row.category_group, row.category)
            if key in self.categories:
                return self.categories[key]
            # No expense account for this category: it is the investment carve-out
            # (D6), which is exactly what the investment accounts are for.
            return self.investment(inflow)

        if row.payee.strip().lower() in RECONCILIATION_PAYEES:
            # YNAB's own name for a correcting entry. It posts against the system
            # equity account, which is what that account is for.
            return self.equity

        return self.investment(inflow) if self._is_tracking(row.account) else self.uncategorized(inflow)

    def _is_tracking(self, account_name: str) -> bool:
        return account_name in self.tracking


_MISSING = object()


def _build_entries(analysis: Analysis, resolver: _Resolver):
    """
    Every register row, in file order, folded into journal entries.

    Splits come first because a split leg can itself be one half of a transfer: that
    pair has to merge into the split's entry rather than becoming an entry of its
    own, or the movement is counted twice (D8).
    """
    by_index = {row.index: row for row in analysis.register}
    split_of = {index: group for group in analysis.split_groups for index in group}
    openings = set(analysis.opening_rows)
    mates = analysis.transfer_mates

    entries: list[PlannedEntry] = []
    planned_openings: list[PlannedOpening] = []
    consumed: set[int] = set()
    note = resolver.note_transfer_leg

    for row in analysis.register:
        if row.index in consumed:
            continue

        account = resolver.account_for(row)
        if account is None:
            consumed.add(row.index)
            continue  # the user dropped this account

        if row.index in openings:
            opening = _opening(row, account, resolver)
            # A `Starting Balance` of zero is how YNAB records an account that was
            # added empty. It is still accounted for -- it just has no money in it,
            # and an entry with nothing on either side is not a journal entry.
            if opening.amount != ZERO:
                planned_openings.append(opening)
            else:
                resolver.zero_openings += 1
            consumed.add(row.index)
            continue

        if row.index in split_of:
            group = [by_index[i] for i in split_of[row.index]]
            entry, used = _split_entry(group, account, resolver, mates, by_index)
            entries.append(entry)
            consumed.update(used)
            continue

        if row.index in mates:
            mate = by_index[mates[row.index]]
            mate_account = resolver.account_for(mate)
            consumed.update({row.index, mate.index})
            if mate_account is None:
                # The other side's account was dropped, so the movement has nowhere
                # to go but the equity offset.
                entries.append(_simple_entry(row, account, resolver.equity, resolver))
                continue
            entries.append(_transfer_entry(row, mate, account, mate_account, resolver))
            note(row)
            note(mate)
            continue

        consumed.add(row.index)
        entries.append(_simple_entry(row, account, resolver.counter_for(row), resolver))

    return entries, planned_openings, resolver.allocations, consumed


def _opening(row: RegisterRow, account: tuple[str, str], resolver: _Resolver) -> PlannedOpening:
    """
    A `Starting Balance` row, signed for the account's own type.

    YNAB writes what the account held; KB records what is owned (a debit) or owed (a
    credit), so a liability's negative starting balance becomes a positive amount
    owed.
    """
    amount = row.net if account[0] == ASSET else -row.net
    return PlannedOpening(account=account, amount=amount.quantize(CENT), as_of=row.entry_date)


def _lines_for(row: RegisterRow, account: tuple[str, str], counter: tuple[str, str]) -> tuple[PlannedLine, ...]:
    amount = abs(row.net).quantize(CENT)
    inflow = row.net > ZERO
    return (
        PlannedLine(
            account=account,
            dr=amount if inflow else ZERO,
            cr=ZERO if inflow else amount,
            # D9: YNAB flags a transaction, KB flags a line. The flag belongs on the
            # bank-account side, which is the side a bank statement can confirm --
            # the same rule the transfer-mirror code already follows.
            is_reconciled=row.is_reconciled,
            is_cleared=row.is_cleared,
        ),
        PlannedLine(account=counter, dr=ZERO if inflow else amount, cr=amount if inflow else ZERO),
    )


def _simple_entry(row: RegisterRow, account, counter, resolver: _Resolver) -> PlannedEntry:
    return PlannedEntry(
        entry_date=row.entry_date,
        description=_description(row),
        payee=_payee(row),
        lines=_lines_for(row, account, counter),
    )


def _transfer_entry(row, mate, account, mate_account, resolver: _Resolver) -> PlannedEntry:
    """
    One entry for both legs of a transfer.

    Each leg keeps its own reconciliation flag: in KB the two sides reconcile
    independently, because two banks clear the same movement on their own schedules.
    """
    amount = abs(row.net).quantize(CENT)
    inflow = row.net > ZERO

    lines = (
        PlannedLine(
            account=account,
            dr=amount if inflow else ZERO,
            cr=ZERO if inflow else amount,
            is_reconciled=row.is_reconciled,
            is_cleared=row.is_cleared,
        ),
        PlannedLine(
            account=mate_account,
            dr=ZERO if inflow else amount,
            cr=amount if inflow else ZERO,
            is_reconciled=mate.is_reconciled,
            is_cleared=mate.is_cleared,
        ),
    )
    description = _description(row) or _description(mate) or f"Transfer: {row.account} → {mate.account}"
    return PlannedEntry(entry_date=row.entry_date, description=description, payee=None, lines=lines)


def _split_entry(group, account, resolver: _Resolver, mates, by_index):
    """
    One entry for a split: a single line on the account, one counter line per leg.

    A leg that is itself a transfer takes its counter from the *other account* and
    consumes that pair, so the money moves once.
    """
    used = {row.index for row in group}
    total = sum(row.net for row in group)
    parent = group[0]

    lines = [
        PlannedLine(
            account=account,
            dr=abs(total).quantize(CENT) if total > ZERO else ZERO,
            cr=abs(total).quantize(CENT) if total <= ZERO else ZERO,
            is_reconciled=parent.is_reconciled,
            is_cleared=parent.is_cleared,
        )
    ]

    for leg in group:
        amount = abs(leg.net).quantize(CENT)
        inflow = leg.net > ZERO
        counter = None

        if leg.index in mates:
            mate = by_index[mates[leg.index]]
            mate_account = resolver.account_for(mate)
            used.add(mate.index)
            resolver.note_transfer_leg(leg)
            resolver.note_transfer_leg(mate)
            counter = mate_account if mate_account is not None else resolver.equity
        else:
            counter = resolver.counter_for(leg)

        lines.append(PlannedLine(account=counter, dr=ZERO if inflow else amount, cr=amount if inflow else ZERO))

    payee = next((_payee(leg) for leg in group if _payee(leg)), None)
    description = next((leg.clean_memo for leg in group if leg.clean_memo), "") or (payee or "Split transaction")

    return (
        PlannedEntry(entry_date=parent.entry_date, description=description, payee=payee, lines=tuple(lines)),
        used,
    )


def _payee(row: RegisterRow) -> str | None:
    if row.transfer_account or row.is_starting_balance or not row.payee.strip():
        return None
    return row.payee.strip()[:200]


def _description(row: RegisterRow) -> str:
    """
    What the transaction says it is.

    The memo first, then the payee, then the category -- and never blank, because a
    row with none of the three still has to be findable in the ledger.
    """
    return row.clean_memo or (_payee(row) or "") or row.category or f"{row.account} transaction"


# ---------------------------------------------------------------------------
# Goals and budgets
# ---------------------------------------------------------------------------


def _goal_name(facts, choice) -> str:
    return (choice.name if choice else facts.name)[:200]


def _build_goals(analysis: Analysis, choices: Choices, allocations, categories) -> tuple[list[PlannedGoal], int]:
    """
    A goal per savings category, funded month by month from its categorised transfers.

    `target_amount` is what has already been saved -- the export carries no YNAB
    targets, and inventing one would be a number the user never chose. That makes
    every imported goal arrive fully funded, which the import summary says plainly,
    because a funded goal's quick-assign button is disabled until the target is
    raised.

    A category whose transfers net to nothing or less is one the user saved into and
    then spent: the house was bought, the trip was taken. It arrives as a *closed*
    goal with its allocations and spending history -- open, it would put "$20,464
    still to save" on the dashboard for money deliberately spent. Its target is what
    was ever put in.
    """
    goals = []
    spent = 0
    for facts in analysis.categories:
        choice = choices.categories.get(category_key(facts.group, facts.name))
        kind = choice.kind if choice else facts.kind
        if kind != KIND_GOAL:
            continue

        months = sorted(
            (month, amount)
            for (group, name, month), amount in allocations.items()
            if (group, name) == (facts.group, facts.name) and amount != ZERO
        )
        saved = sum((amount for _, amount in months), ZERO)
        closed = saved <= ZERO
        if closed:
            spent += 1
            target = sum((amount for _, amount in months if amount > ZERO), ZERO)
        else:
            target = saved

        goals.append(
            PlannedGoal(
                name=_goal_name(facts, choice),
                target_amount=target.quantize(CENT),
                allocations=tuple((month, amount.quantize(CENT)) for month, amount in months),
                account=categories.get((facts.group, facts.name)),
                closed=closed,
            )
        )
    return goals, spent


def budget_amount(assigned: Decimal, previous_available: Decimal | None) -> Decimal:
    """
    What YNAB actually put in a category that month (D2).

    YNAB resets a negative `Available` to zero at the month boundary, covering the
    overspend out of Ready to Assign; KB carries negatives forward. The `Assigned`
    column does not show the money that covered the overspend, so importing it
    verbatim would leave a migrated user with most categories deeply in the red.
    Adding back the reset -- `x + max(0, -x)` is exactly that reset -- records the
    money that really went in, and reproduces YNAB's `Available` under KB's own
    unchanged rollover.
    """
    top_up = max(ZERO, -previous_available) if previous_available is not None else ZERO
    return assigned + top_up


def _build_budgets(analysis, choices, categories, entries, income):
    """
    A `Budget` row per category-month, plus the income back-fill.

    Income is the gap YNAB leaves: it never assigns to income categories, so there is
    nothing in the export to import. Setting each income budget to that month's own
    actual makes KB's income formula (`Actual - Budget + previous`) contribute zero
    every month, so the migrated user starts with income `Available` at 0 rather than
    a surplus of every dollar they have ever earned (D1).
    """
    budgets: list[PlannedBudget] = []
    top_up_months = 0
    top_up_total = ZERO

    previous: dict[tuple[str, str], Decimal] = {}
    for row in analysis.plan:
        key = row.key
        account = categories.get(key)
        if account is not None:
            amount = budget_amount(row.assigned, previous.get(key))
            if amount != row.assigned:
                top_up_months += 1
                top_up_total += amount - row.assigned
            if amount != ZERO:
                budgets.append(PlannedBudget(category=account, month=row.month, amount=amount.quantize(CENT)))
        previous[key] = row.available

    # The back-fill runs off the entries this same build produced, not a query, so it
    # stays inside the one pure pass and cannot disagree with what gets written.
    income_keys = {key for key in income.values() if key is not None}
    actuals: dict[tuple[tuple[str, str], date], Decimal] = collections.defaultdict(lambda: ZERO)
    for entry in entries:
        for line in entry.lines:
            if line.account in income_keys:
                actuals[(line.account, entry.entry_date.replace(day=1))] += line.cr - line.dr

    for (account, month), amount in sorted(actuals.items()):
        if amount != ZERO:
            budgets.append(PlannedBudget(category=account, month=month, amount=amount.quantize(CENT)))

    return budgets, {"top_up_months": top_up_months, "top_up_total": str(top_up_total.quantize(CENT))}


# ---------------------------------------------------------------------------
# Self-checks and summary
# ---------------------------------------------------------------------------


def _notes(
    analysis: Analysis, choices: Choices, goals, spent_goals: int, budget_stats: dict, resolver: _Resolver
) -> list[str]:
    """
    What the import decided on the user's behalf, in their words.

    Every one of these is a number the importer produced that the export does not
    contain. Saying so is the difference between a figure the user can check and a
    figure that looks invented.
    """
    notes = []

    if budget_stats["top_up_months"]:
        notes.append(
            f"In {budget_stats['top_up_months']} category-month(s) your budgeted amount is higher than YNAB's "
            f"Assigned column, by {budget_stats['top_up_total']} in total. That is the money YNAB quietly took "
            "from Ready to Assign to cover an overspend; recording it keeps every category's Available matching "
            "what you see in YNAB."
        )

    open_goals = [goal for goal in goals if not goal.closed]
    if open_goals:
        notes.append(
            f"{len(open_goals)} savings categor(ies) became goals, with their target set to what you have already "
            "saved. Raise the target on any goal you are still saving for -- a goal that has met its target "
            "cannot be funded again until you do."
        )

    if spent_goals:
        notes.append(
            f"{spent_goals} savings categor(ies) had as much taken back out of them as was ever put in -- money you "
            "saved and then spent -- so they arrive as closed goals, with their savings and spending history."
        )

    goal_names = {goal.name for goal in goals}
    spent_from_goals = [
        facts
        for facts in analysis.categories
        if facts.plain_rows
        and _goal_name(facts, choices.categories.get(category_key(facts.group, facts.name))) in goal_names
    ]
    if spent_from_goals:
        notes.append(
            f"{len(spent_from_goals)} savings categor(ies) were also spent from directly. That spending comes out "
            "of the goal, the way a purchase you saved for should: it lowers what the goal has left and shows under "
            "Goal spending on the income statement. If you would rather budget for it month to month, set it to a "
            "spending category on the Savings step instead of a goal."
        )

    if resolver.dropped_transfer_categories:
        notes.append(
            f"{resolver.dropped_transfer_categories} transfer line(s) carried a category that is not a savings "
            "goal. The money still moves between the right accounts, but the category is not kept: posting a "
            "move between your own accounts to a spending category would misstate your net worth."
        )

    income_accounts = {facts.account for facts in analysis.income_payees if facts.kind == INCOME and facts.account}
    if income_accounts:
        notes.append(
            f"YNAB does not categorise income, so your {len(income_accounts)} income account(s) were worked out "
            "from who paid you. Each month's income budget is set to that month's actual income, so income "
            "Available starts at zero rather than counting every dollar you have ever earned as a surplus."
        )

    notes.append(
        "Amounts were imported exactly as exported. A YNAB export carries no currency, so they are treated as "
        "your currency."
    )
    return notes


def _stats(analysis: Analysis, plan: ImportPlan, resolver: _Resolver, budget_stats: dict) -> dict:
    """The numbers the preview and the import summary report. Counted, never estimated."""
    first, last = analysis.date_range
    return {
        "rows": len(analysis.register),
        "entries": len(plan.entries),
        "lines": sum(len(entry.lines) for entry in plan.entries),
        "accounts": len(plan.accounts),
        "groups": len(plan.groups),
        "payees": len(plan.payees),
        "budgets": len(plan.budgets),
        "goals": len(plan.goals),
        "spent_goals": resolver.spent_goals,
        "openings": len(plan.openings),
        "zero_openings": resolver.zero_openings,
        "transfer_pairs": analysis.transfer_pairs,
        "splits": len(analysis.split_groups),
        "months": len(analysis.months),
        "dropped_transfer_categories": resolver.dropped_transfer_categories,
        "skipped_accounts": sum(1 for choice in resolver.choices.accounts.values() if choice.skip),
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
        "net_worth": str(_net_worth(plan)),
        **budget_stats,
    }


def _net_worth(plan: ImportPlan) -> Decimal:
    """
    What the imported books will say the user is worth.

    Assets and liabilities only, `dr - cr` -- the same sum `NetWorthService` runs, so
    the preview can promise the figure the dashboard will show.
    """
    types = {account.key: account.account_type for account in plan.accounts}
    total = ZERO
    for entry in plan.entries:
        for line in entry.lines:
            if types.get(line.account) in (ASSET, LIABILITY):
                total += line.dr - line.cr
    for opening in plan.openings:
        total += opening.amount if types.get(opening.account) == ASSET else -opening.amount
    return total.quantize(CENT)


def assert_sound(plan: ImportPlan, analysis: Analysis, consumed: set[int]):
    """
    Three invariants, checked before anything is written.

    An unbalanced entry would be rejected by the database one row at a time, halfway
    through an import. A row that reached no entry at all would be rejected by
    nothing, which is worse: the import would look like it worked and be quietly
    short of a transaction.
    """
    unbalanced = [entry for entry in plan.entries if not entry.balances]
    if unbalanced:
        raise BuildError(f"{len(unbalanced)} imported transaction(s) do not balance. Nothing was imported.")

    missing = {line.account for entry in plan.entries for line in entry.lines} - {
        account.key for account in plan.accounts
    }
    if missing:
        raise BuildError(f"The import refers to {len(missing)} account(s) it did not create. Nothing was imported.")

    unaccounted = len(analysis.register) - len(consumed)
    if unaccounted:
        raise BuildError(f"{unaccounted} row(s) of the export reached no transaction. Nothing was imported.")
