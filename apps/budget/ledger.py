"""
The budget, written into the ledger (phase 2 of docs/double-entry-budget-plan.md).

Every month that has budget amounts or goal allocations gets **one budget entry**
(`JournalEntry.SOURCE_BUDGET`, dated the first of the month) with one line per
budget bucket (`apps.budget.buckets`) plus one balancing line on Unassigned:

- an expense budget of A:   Dr Unassigned A / Cr the category's envelope A
- a goal allocation of A:   Dr Unassigned A / Cr the goal's bucket A
- an income budget of A:    Dr the category's expected income A / Cr Unassigned A

Negative amounts post to the other side. Unassigned carries the net of the month,
so the entry always balances.

In this phase the `Budget` and `GoalAllocation` rows are still the source of
truth: the entry is *derived* from them and rebuilt whenever they change, never
edited on its own. `sync_month` is the one writer, wired by `post_save` signals
(`apps.budget.signals`) for single saves and called explicitly by every path that
writes rows in bulk or deletes them. `check_book` proves the mirror faithful:
each bucket's balance equals the rows behind it, and `ledger_unassigned` — the
same Unassigned formula read off bucket balances instead of rows — equals
`compute_unassigned` for every month.

Lines are written with `bulk_create`/`bulk_update`/`QuerySet.delete`, not
`save()`: a budget amount autosaves on every keystroke-and-blur, and a field diff
in the audit log for each one would bury the real history. The ledger guard still
holds, since every line written here is on a bucket of a budget entry.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from apps.accounts.models import ACCOUNT_TYPE_BUDGET, ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account

ZERO = Decimal("0")


def _first(month) -> date:
    """The first of `month`'s month. A model saved with an ISO string keeps the string on the instance."""
    if isinstance(month, str):
        month = date.fromisoformat(month[:10])
    if isinstance(month, datetime):
        month = month.date()
    return month.replace(day=1)


def _bucket_map(book, category_ids, goal_ids):
    """`({category_id: bucket}, {goal_id: bucket})`, creating any bucket that is missing."""
    from apps.budget.buckets import sync_bucket
    from apps.budget.models import Goal

    goal_accounts = dict(Goal.objects.filter(pk__in=goal_ids).values_list("pk", "account_id"))
    wanted = set(category_ids) | set(goal_accounts.values())
    buckets = {b.paired_account_id: b for b in Account.objects.filter(paired_account_id__in=wanted).budget_buckets()}
    for account in Account.objects.filter(pk__in=wanted - buckets.keys()).select_related("account_group"):
        sync_bucket(account)
    if wanted - buckets.keys():
        buckets = {
            b.paired_account_id: b for b in Account.objects.filter(paired_account_id__in=wanted).budget_buckets()
        }
    by_category = {cid: buckets[cid] for cid in category_ids if cid in buckets}
    by_goal = {gid: buckets[aid] for gid, aid in goal_accounts.items() if aid in buckets}
    return by_category, by_goal


def month_claims(book, month) -> dict:
    """
    `{bucket_id: amount}` for `month`, each signed as a credit to the bucket: what the
    month's rows put into it. Expected income is a debit-normal bucket, so an income
    budget is a negative credit.
    """
    from apps.budget.models import Budget, GoalAllocation

    month = _first(month)
    budgets = list(
        Budget.objects.filter(book=book, month__gte=month, month__lt=_next(month)).values_list(
            "category_id", "category__account_group__account_type", "budget_amount"
        )
    )
    allocations = list(
        GoalAllocation.objects.filter(book=book, month__gte=month, month__lt=_next(month)).values_list(
            "goal_id", "amount"
        )
    )
    by_category, by_goal = _bucket_map(book, {c for c, _t, _a in budgets}, {g for g, _a in allocations})

    claims = defaultdict(lambda: ZERO)
    for category_id, account_type, amount in budgets:
        bucket = by_category.get(category_id)
        if bucket is None or account_type not in (ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME):
            continue
        claims[bucket.pk] += -amount if account_type == ACCOUNT_TYPE_INCOME else amount
    for goal_id, amount in allocations:
        bucket = by_goal.get(goal_id)
        if bucket is not None:
            claims[bucket.pk] += amount
    return {bucket_id: amount for bucket_id, amount in claims.items() if amount}


def _next(month: date) -> date:
    return month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)


def _sides(amount) -> tuple[Decimal, Decimal]:
    """`(dr, cr)` for a signed credit."""
    return (ZERO, amount) if amount > 0 else (-amount, ZERO)


def budget_entry(book, month):
    from apps.journal.models import JournalEntry

    return JournalEntry.objects.filter(book=book, source=JournalEntry.SOURCE_BUDGET, entry_date=_first(month)).first()


@transaction.atomic
def sync_month(book, month):
    """
    Rebuild `month`'s budget entry from the month's rows: create it, rewrite its
    lines in place, or delete it once nothing is budgeted. Idempotent.
    """
    from apps.budget.buckets import ensure_unassigned
    from apps.journal.models import JournalEntry, JournalLine

    month = _first(month)
    # One sync per book at a time: two autosaves in the same month would otherwise
    # race to create its entry (the unique constraint would refuse the second).
    unassigned = ensure_unassigned(book)
    Account.objects.select_for_update().filter(pk=unassigned.pk).first()

    claims = month_claims(book, month)
    entry = budget_entry(book, month)

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

    existing = {line.account_id: line for line in entry.lines.all()}
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
        JournalLine.objects.bulk_create_for_import(to_create, {})
    return entry


def sync_months(book, months):
    for month in sorted({_first(m) for m in months}):
        sync_month(book, month)


@transaction.atomic
def sync_book(book):
    """Rebuild every budget entry in `book`: for each month with rows, and any stale entry without."""
    from apps.budget.models import Budget, GoalAllocation
    from apps.journal.models import JournalEntry

    months = set(Budget.objects.filter(book=book).values_list("month", flat=True))
    months |= set(GoalAllocation.objects.filter(book=book).values_list("month", flat=True))
    months |= set(
        JournalEntry.objects.filter(book=book, source=JournalEntry.SOURCE_BUDGET).values_list("entry_date", flat=True)
    )
    sync_months(book, months)


def release_bucket_lines(buckets):
    """
    Delete the budget-entry lines on `buckets` (accounts about to be deleted, whose
    lines would otherwise block it: `JournalLine.account` is PROTECT). Returns the
    `(book, month)` pairs touched, for the caller to `sync_month` once the rows
    behind those lines are gone.
    """
    from apps.journal.models import JournalEntry, JournalLine

    lines = JournalLine.objects.filter(account__in=buckets, journal_entry__source=JournalEntry.SOURCE_BUDGET)
    touched = set(lines.values_list("journal_entry__book_id", "journal_entry__entry_date"))
    lines.delete()
    return touched


def resync(touched):
    from apps.books.models import Book

    books = Book.objects.in_bulk({book_id for book_id, _month in touched})
    for book_id, month in sorted(touched):
        if book_id in books:
            sync_month(books[book_id], month)


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
    `compute_unassigned`, read off the ledger: the budget side of every available
    comes from its bucket's balance instead of the `Budget`/`GoalAllocation` rows.
    Equal to `compute_unassigned` exactly when the mirror is faithful.
    """
    from apps.budget.linked import linked_allocated_subquery
    from apps.budget.models import Goal, goal_spent_subquery, month_after
    from apps.budget.services import NetWorthService
    from apps.budget.unassigned import Unassigned, _positive, budget_categories

    month = _first(month)
    end = month_after(month)
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
    bucket_mismatches: list = field(default_factory=list)
    unassigned_mismatches: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.bucket_mismatches and not self.unassigned_mismatches


def check_book(book, through: date | None = None) -> CheckResult:
    """
    Compare the mirror with the rows: every budget entry against `month_claims`, and
    `ledger_unassigned` against `compute_unassigned` for every month from the book's
    first activity through `through` (default: this month).
    """
    from apps.budget.services import BudgetService
    from apps.budget.unassigned import compute_unassigned
    from apps.journal.models import JournalEntry

    result = CheckResult(book=book)
    entries = {e.entry_date: e for e in JournalEntry.objects.filter(book=book, source=JournalEntry.SOURCE_BUDGET)}
    months = set(entries)
    from apps.budget.models import Budget, GoalAllocation

    months |= {_first(m) for m in Budget.objects.filter(book=book).values_list("month", flat=True)}
    months |= {_first(m) for m in GoalAllocation.objects.filter(book=book).values_list("month", flat=True)}
    unassigned = Account.objects.filter(
        book=book, account_group__account_type=ACCOUNT_TYPE_BUDGET, paired_account__isnull=True
    ).values_list("pk", flat=True)
    for month in sorted(months):
        claims = month_claims(book, month)
        entry = entries.get(month)
        posted = {}
        if entry is not None:
            posted = {
                line.account_id: line.cr_amount - line.dr_amount
                for line in entry.lines.all()
                if line.account_id not in unassigned
            }
        if posted != claims:
            result.bucket_mismatches.append((month, claims, posted))

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
            month = _next(month)
    return result
