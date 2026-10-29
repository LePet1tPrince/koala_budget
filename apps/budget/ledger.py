"""
The budget, kept in the ledger (docs/double-entry-budget-plan.md).

Every month that has budget amounts or goal allocations has **one budget entry**
(`JournalEntry.SOURCE_BUDGET`, dated the first of the month) with one line per
budget bucket (`apps.budget.buckets`) plus one balancing line on Unassigned:

- an expense budget of A:   Dr Unassigned A / Cr the category's envelope A
- a goal allocation of A:   Dr Unassigned A / Cr the goal's bucket A
- an income budget of A:    Dr the category's expected income A / Cr Unassigned A

Negative amounts post to the other side. Unassigned carries the net of the month,
so the entry always balances; a month with nothing budgeted has no entry.

The entries are the budget: there is no other record of it. This module is the
only writer (`set_budget`, `add_to_budget`, `set_budgets`, `set_goal_allocation`,
`add_to_goal_allocation`, `set_goal_allocations`), every write going through
`write_month`, and the readers below (`budgeted_by_month_category`,
`goal_assigned_by_month`, ...) are what every figure comes from.

Lines are written with `bulk_create`/`bulk_update`/`QuerySet.delete`, not
`save()`: a budget amount autosaves on every blur, and a field diff in the audit
log for each one would bury the real history. The ledger guard still holds,
since every line written here is on a bucket of a budget entry.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account
from apps.utils.months import add_months

ZERO = Decimal("0")
PAIRED_TYPES = (ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME)


def _first(month) -> date:
    """The first of `month`'s month. A model saved with an ISO string keeps the string on the instance."""
    if isinstance(month, str):
        month = date.fromisoformat(month[:10])
    if isinstance(month, datetime):
        month = month.date()
    return month.replace(day=1)


def _sides(amount) -> tuple[Decimal, Decimal]:
    """`(dr, cr)` for a signed credit."""
    return (ZERO, amount) if amount > 0 else (-amount, ZERO)


def _buckets_for(account_ids) -> dict:
    """`{paired account id: bucket}`, creating any bucket that is missing."""
    from apps.budget.buckets import sync_bucket

    wanted = set(account_ids)
    buckets = {b.paired_account_id: b for b in Account.objects.filter(paired_account_id__in=wanted).budget_buckets()}
    missing = wanted - buckets.keys()
    if missing:
        for account in Account.objects.filter(pk__in=missing).select_related("account_group"):
            sync_bucket(account)
        buckets = {
            b.paired_account_id: b for b in Account.objects.filter(paired_account_id__in=wanted).budget_buckets()
        }
    return buckets


def _category_credit(account_type, amount):
    """A category's budget as a credit to its bucket: expected income is debit-normal."""
    return -amount if account_type == ACCOUNT_TYPE_INCOME else amount


def budget_entry(book, month):
    from apps.journal.models import JournalEntry

    return JournalEntry.objects.filter(book=book, source=JournalEntry.SOURCE_BUDGET, entry_date=_first(month)).first()


def lock(book):
    """
    The book's Unassigned bucket, locked: one budget write per book at a time, so
    two autosaves in one month can't race to create its entry (the unique
    constraint would refuse the second) or read-modify-write the same line.
    """
    from apps.budget.buckets import ensure_unassigned

    unassigned = ensure_unassigned(book)
    Account.objects.select_for_update().filter(pk=unassigned.pk).first()
    return unassigned


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


@transaction.atomic
def write_month(book, month, credits: dict):
    """
    Set the given buckets' amounts in `month`'s budget entry, each a signed credit
    (`{bucket_id: amount}`; zero removes the line), leaving every other bucket as
    it is, and rebalance Unassigned. Creates the entry for a month's first amount
    and deletes it once nothing is left. Returns the entry, or None.
    """
    from apps.journal.models import JournalEntry, JournalLine

    month = _first(month)
    unassigned = lock(book)
    entry = budget_entry(book, month)
    existing = {line.account_id: line for line in entry.lines.all()} if entry is not None else {}
    claims = {
        account_id: line.cr_amount - line.dr_amount
        for account_id, line in existing.items()
        if account_id != unassigned.pk
    }
    claims.update(credits)
    claims = {account_id: amount for account_id, amount in claims.items() if amount}

    if not claims:
        if entry is not None:
            entry.lines.all().delete()
            entry.delete()
        return None

    net = sum(claims.values(), ZERO)
    wanted = dict(claims)
    if net:
        wanted[unassigned.pk] = -net

    if entry is None:
        entry = JournalEntry.objects.create(
            book=book,
            entry_date=month,
            description=f"Budget for {month:%B %Y}",
            source=JournalEntry.SOURCE_BUDGET,
            status=JournalEntry.STATUS_POSTED,
        )

    to_create, to_update = [], []
    for account_id, amount in wanted.items():
        dr, cr = _sides(amount)
        line = existing.pop(account_id, None)
        if line is None:
            to_create.append(
                JournalLine(book=book, journal_entry=entry, account_id=account_id, dr_amount=dr, cr_amount=cr)
            )
        elif (line.dr_amount, line.cr_amount) != (dr, cr):
            line.dr_amount, line.cr_amount = dr, cr
            to_update.append(line)
    if existing:
        JournalLine.objects.filter(pk__in=[line.pk for line in existing.values()]).delete()
    if to_update:
        JournalLine.objects.bulk_update(to_update, ["dr_amount", "cr_amount"])
    if to_create:
        JournalLine.objects.bulk_create_for_import(to_create)
    return entry


@transaction.atomic
def write_months(book, credits_by_month: dict):
    """`write_month` for many months: `{month: {bucket_id: credit}}`."""
    for month, credits in sorted(credits_by_month.items()):
        write_month(book, month, credits)


def set_budgets(book, amounts: dict):
    """
    Set income and expense budgets: `{(category_id, month): amount}`. Categories
    that aren't income or expense are ignored, as the budget page ignores them.
    """
    if not amounts:
        return
    types = dict(
        Account.objects.filter(book=book, pk__in={cid for cid, _m in amounts}).values_list(
            "pk", "account_group__account_type"
        )
    )
    buckets = _buckets_for([cid for cid, t in types.items() if t in PAIRED_TYPES])
    by_month = {}
    for (category_id, month), amount in amounts.items():
        bucket = buckets.get(category_id)
        if bucket is None or types.get(category_id) not in PAIRED_TYPES:
            continue
        by_month.setdefault(_first(month), {})[bucket.pk] = _category_credit(types[category_id], amount)
    write_months(book, by_month)


def set_budget(book, category, month, amount):
    """Set `category`'s budget for `month` to `amount`."""
    set_budgets(book, {(category.pk, _first(month)): amount})


@transaction.atomic
def add_to_budget(book, category, month, delta):
    """Add `delta` to `category`'s budget for `month`, and return the new budget."""
    month = _first(month)
    lock(book)
    current = budgeted_in_month(book, month, [category.pk]).get(category.pk, ZERO)
    set_budget(book, category, month, current + delta)
    return current + delta


def set_goal_allocations(book, amounts: dict):
    """Set goal allocations: `{(goal_id, month): amount}` (negative = a withdrawal)."""
    from apps.budget.models import Goal

    if not amounts:
        return
    accounts = dict(Goal.objects.filter(book=book, pk__in={gid for gid, _m in amounts}).values_list("pk", "account_id"))
    buckets = _buckets_for(accounts.values())
    by_month = {}
    for (goal_id, month), amount in amounts.items():
        bucket = buckets.get(accounts.get(goal_id))
        if bucket is not None:
            by_month.setdefault(_first(month), {})[bucket.pk] = amount
    write_months(book, by_month)


def set_goal_allocation(book, goal, month, amount):
    """Set `goal`'s allocation for `month` to `amount`."""
    set_goal_allocations(book, {(goal.pk, _first(month)): amount})


def goal_allocation(book, goal, month):
    """`goal`'s allocation for `month` (0 when there is none)."""
    return goal_assigned_by_month(book, [goal.pk], _first(month), add_months(_first(month), 1)).get(
        (goal.pk, _first(month)), ZERO
    )


@transaction.atomic
def add_to_goal_allocation(book, goal, month, delta):
    """Add `delta` (negative to take money out) to `goal`'s allocation for `month`; return the new amount."""
    month = _first(month)
    lock(book)
    current = goal_allocation(book, goal, month)
    set_goal_allocation(book, goal, month, current + delta)
    return current + delta


@transaction.atomic
def flip_bucket(account):
    """
    Move `account`'s budget to the other side of every entry: a category moved
    between an income and an expense group keeps the amounts it was budgeted, but
    expected income is debit-normal and an envelope credit-normal.
    """
    from apps.journal.models import JournalEntry, JournalLine

    lock(account.book)
    lines = list(
        JournalLine.objects.filter(
            account__paired_account=account, journal_entry__source=JournalEntry.SOURCE_BUDGET
        ).select_related("journal_entry")
    )
    for line in lines:
        write_month(account.book, line.journal_entry.entry_date, {line.account_id: line.dr_amount - line.cr_amount})


def release_bucket_lines(buckets):
    """
    Delete the budget-entry lines on `buckets` (accounts about to be deleted, whose
    lines would otherwise block it: `JournalLine.account` is PROTECT). Returns the
    `(book, month)` pairs touched, for the caller to `rebalance` once the buckets
    are gone.
    """
    from apps.journal.models import JournalEntry, JournalLine

    lines = JournalLine.objects.filter(account__in=buckets, journal_entry__source=JournalEntry.SOURCE_BUDGET)
    touched = set(lines.values_list("journal_entry__book_id", "journal_entry__entry_date"))
    lines.delete()
    return touched


def rebalance(touched):
    """Rebalance Unassigned in each `(book_id, month)`'s entry, dropping one left with nothing."""
    from apps.books.models import Book

    books = Book.objects.in_bulk({book_id for book_id, _month in touched})
    for book_id, month in sorted(touched):
        if book_id in books:
            write_month(books[book_id], month, {})


def rebalance_book(book):
    """Rebalance every budget entry in `book`."""
    from apps.journal.models import JournalEntry

    months = JournalEntry.objects.filter(book=book, source=JournalEntry.SOURCE_BUDGET).values_list(
        "entry_date", flat=True
    )
    rebalance({(book.pk, month) for month in months})


# ---------------------------------------------------------------------------
# Reading the budget off the ledger
# ---------------------------------------------------------------------------


def _budget_lines(book):
    """Lines of `book`'s budget entries on paired buckets (Unassigned's balancing line left out)."""
    from apps.journal.models import JournalEntry, JournalLine

    return JournalLine.objects.filter(
        book=book, journal_entry__source=JournalEntry.SOURCE_BUDGET, account__paired_account__isnull=False
    )


def budgeted_by_month_category(book, start_month=None, end_month=None, category_ids=None) -> dict:
    """
    `{(month, category_id): amount}` budgeted for income and expense categories,
    months `start_month` through `end_month` inclusive. An envelope's budget is its
    bucket's credit; expected income is debit-normal, so its budget is the debit.
    Months with nothing budgeted are absent.
    """
    lines = _budget_lines(book).filter(
        account__paired_account__account_group__account_type__in=(ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME)
    )
    if start_month is not None:
        lines = lines.filter(journal_entry__entry_date__gte=_first(start_month))
    if end_month is not None:
        lines = lines.filter(journal_entry__entry_date__lt=add_months(_first(end_month), 1))
    if category_ids is not None:
        lines = lines.filter(account__paired_account_id__in=category_ids)
    result = {}
    for month, category_id, account_type, dr, cr in lines.values_list(
        "journal_entry__entry_date",
        "account__paired_account_id",
        "account__paired_account__account_group__account_type",
        "dr_amount",
        "cr_amount",
    ):
        amount = dr - cr if account_type == ACCOUNT_TYPE_INCOME else cr - dr
        key = (month, category_id)
        result[key] = result.get(key, ZERO) + amount
    return result


def budgeted_in_month(book, month, category_ids=None) -> dict:
    """`{category_id: amount}` budgeted in `month`."""
    month = _first(month)
    return {
        category_id: amount
        for (_month, category_id), amount in budgeted_by_month_category(book, month, month, category_ids).items()
    }


def budget_amount(book, category, month):
    """`category`'s budget for `month` (0 when there is none)."""
    return budgeted_in_month(book, month, [category.pk]).get(category.pk, ZERO)


def first_category_budget_month(book, category_ids=None):
    """The earliest month with an income or expense budget, or None."""
    lines = _budget_lines(book).filter(
        account__paired_account__account_group__account_type__in=(ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME)
    )
    if category_ids is not None:
        lines = lines.filter(account__paired_account_id__in=category_ids)
    return lines.order_by("journal_entry__entry_date").values_list("journal_entry__entry_date", flat=True).first()


def goal_assigned_by_month(book, goal_ids=None, start=None, end=None) -> dict:
    """
    `{(goal_id, month): amount}` of manual allocations, months from `start`
    (inclusive) to `end` (exclusive): each goal bucket's credit on budget entries.
    """
    from apps.budget.models import Goal

    goal_of_account = dict(
        (Goal.objects.filter(book=book) if goal_ids is None else Goal.objects.filter(pk__in=goal_ids)).values_list(
            "account_id", "pk"
        )
    )
    lines = _budget_lines(book).filter(account__paired_account_id__in=goal_of_account.keys())
    if start is not None:
        lines = lines.filter(journal_entry__entry_date__gte=_first(start))
    if end is not None:
        lines = lines.filter(journal_entry__entry_date__lt=end)
    result = {}
    for account_id, month, dr, cr in lines.values_list(
        "account__paired_account_id", "journal_entry__entry_date", "dr_amount", "cr_amount"
    ):
        key = (goal_of_account[account_id], month)
        result[key] = result.get(key, ZERO) + cr - dr
    return result


def has_budget(book) -> bool:
    """Whether any income or expense category in `book` has been budgeted."""
    return first_category_budget_month(book) is not None


# ---------------------------------------------------------------------------
# Checking the mirror
# ---------------------------------------------------------------------------


def _bucket_balances(book, end):
    """`{paired_account_id: credit balance}` of every paired bucket, through the day before `end`."""
    from apps.journal.models import counted_entries

    rows = (
        Account.objects.filter(book=book, paired_account__isnull=False)
        .budget_buckets()
        .annotate(
            cr=Sum(
                "journal_lines__cr_amount",
                filter=counted_entries("journal_lines__journal_entry__")
                & Q(journal_lines__journal_entry__entry_date__lt=end),
            ),
            dr=Sum(
                "journal_lines__dr_amount",
                filter=counted_entries("journal_lines__journal_entry__")
                & Q(journal_lines__journal_entry__entry_date__lt=end),
            ),
        )
        .values_list("paired_account_id", "cr", "dr")
    )
    return {paired: (cr or ZERO) - (dr or ZERO) for paired, cr, dr in rows}


def _actuals(book, categories, end):
    """Cumulative actuals through the day before `end`: expense dr−cr, income cr−dr."""
    from apps.journal.models import JournalLine, counted_entries

    totals = dict(
        (row["account_id"], (row["dr"] or ZERO) - (row["cr"] or ZERO))
        for row in JournalLine.objects.filter(
            counted_entries("journal_entry__"),
            book=book,
            account__in=categories,
            journal_entry__entry_date__lt=end,
        )
        .values("account_id")
        .annotate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
    )
    return {
        c.pk: (
            -totals.get(c.pk, ZERO) if c.account_group.account_type == ACCOUNT_TYPE_INCOME else totals.get(c.pk, ZERO)
        )
        for c in categories
    }


def ledger_unassigned(book, month, future_income: bool | None = None):
    """
    `compute_unassigned` by a second road: every available from its bucket's
    cumulative balance rather than `BudgetService`'s month-by-month walk. The two
    must agree; `check_book` holds them to it.
    """
    from apps.budget.linked import linked_allocated_subquery
    from apps.budget.models import Goal, goal_spent_subquery
    from apps.budget.services import NetWorthService
    from apps.budget.unassigned import Unassigned, _positive, budget_categories

    month = _first(month)
    end = add_months(month, 1)
    if future_income is None:
        future_income = book.budget_future_income
    categories = budget_categories(book)
    expense = [c for c in categories if c.account_group.account_type == ACCOUNT_TYPE_EXPENSE]
    income = [c for c in categories if c.account_group.account_type == ACCOUNT_TYPE_INCOME] if future_income else []

    balances = _bucket_balances(book, end)
    actual = _actuals(book, expense + income, end)
    # Envelopes are credit-normal (budget − spent); expected income is debit-normal
    # (its credit balance is minus what was budgeted), so available = received − budgeted.
    expense_available = [balances.get(c.pk, ZERO) - actual[c.pk] for c in expense]
    income_available = [actual[c.pk] + balances.get(c.pk, ZERO) for c in income]

    goals = Goal.objects.filter(book=book, is_archived=False).annotate(
        linked_to_date=linked_allocated_subquery(None, end),
        spent_to_date=goal_spent_subquery(end=end),
    )
    goal_left = [balances.get(g.account_id, ZERO) + g.linked_to_date - g.spent_to_date for g in goals]

    return Unassigned(
        month=month,
        net_worth=NetWorthService(book).get_net_worth(month),
        income_due=sum((-a for a in income_available if a < 0), ZERO),
        envelopes=_positive(expense_available),
        goals=_positive(goal_left),
        overspent=-sum((a for a in expense_available if a < 0), ZERO),
        goals_overspent=-sum((v for v in goal_left if v < 0), ZERO),
    )


@dataclass
class CheckResult:
    book: object
    months_checked: int = 0
    # (month, problem) for each budget entry that is malformed.
    entry_problems: list = field(default_factory=list)
    # (month, compute_unassigned, ledger_unassigned) where the two read paths disagree.
    unassigned_mismatches: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.entry_problems and not self.unassigned_mismatches


def _entry_problems(entry, unassigned_id):
    lines = list(entry.lines.all())
    if entry.entry_date.day != 1:
        yield "not dated the first of the month"
    if entry.status != entry.STATUS_POSTED:
        yield f"status is {entry.status}"
    claims = [line.cr_amount - line.dr_amount for line in lines if line.account_id != unassigned_id]
    if not claims:
        yield "no budget lines"
    balancing = sum((line.cr_amount - line.dr_amount for line in lines if line.account_id == unassigned_id), ZERO)
    if balancing != -sum(claims, ZERO):
        yield f"Unassigned carries {balancing}, not {-sum(claims, ZERO)}"
    if sum(1 for line in lines if line.account_id == unassigned_id) > 1:
        yield "more than one Unassigned line"
    if len({line.account_id for line in lines}) != len(lines):
        yield "a bucket appears twice"


def check_book(book, through: date | None = None) -> CheckResult:
    """
    Check the book's budget entries: each one dated the first, posted, made of
    bucket lines balanced by exactly one Unassigned line. Then compare
    `ledger_unassigned` (cumulative bucket balances) with `compute_unassigned` (the
    month-by-month walk of availables) for every month from the book's first
    activity through `through` (default: this month).
    """
    from apps.budget.buckets import unassigned_account
    from apps.budget.services import BudgetService
    from apps.budget.unassigned import compute_unassigned
    from apps.journal.models import JournalEntry

    result = CheckResult(book=book)
    unassigned = unassigned_account(book)
    entries = JournalEntry.objects.filter(book=book, source=JournalEntry.SOURCE_BUDGET).prefetch_related("lines")
    for entry in entries.order_by("entry_date"):
        for problem in _entry_problems(entry, unassigned.pk if unassigned else None):
            result.entry_problems.append((entry.entry_date, problem))

    first = BudgetService(book).get_first_activity_month()
    if first is not None:
        last = _first(through or date.today())
        month = first
        while month <= last:
            expected = compute_unassigned(book, month)
            actual = ledger_unassigned(book, month)
            result.months_checked += 1
            if expected != actual:
                result.unassigned_mismatches.append((month, expected, actual))
            month = add_months(month, 1)
    return result
