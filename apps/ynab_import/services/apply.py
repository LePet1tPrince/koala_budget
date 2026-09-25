"""
Writing an `ImportPlan` to a set of books.

One `transaction.atomic` block: an import that half-worked is worse than one that
did not run, because the failure is invisible -- the user sees accounts and some
transactions and has no way to know what is missing.

This module decides nothing. Every judgement was made in `analyse` and `build`,
where it could be previewed; here it is inserts, in the order the foreign keys
require, at the volume the data actually has.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.accounts.models import ACCOUNT_TYPE_INCOME, Account, AccountGroup, Institution, Payee
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.transfer_detection import dismiss_all_candidates
from apps.bank_feed.services.transfer_mirror import mirror_rows_for
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.journal.models import JournalEntry, JournalLine, counted_entries
from apps.onboarding.services.opening import OpeningRow, create_opening_balances

from .build import ASSET, EQUITY_TYPE, ImportPlan

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

# Entries and lines go in batches rather than one statement: a single INSERT with
# 13,000 rows is a large query to hold in memory on both sides of the connection.
BATCH_SIZE = 1000


class ApplyError(ValueError):
    """Something the user needs told about. The message is user-facing."""


@dataclass
class ApplyResult:
    accounts: int
    entries: int
    lines: int
    budgets: int
    goals: int
    payees: int
    openings: int
    feed_rows: int = 0
    inbox_rows: int = 0
    dismissed_transfer_matches: int = 0

    def as_dict(self) -> dict:
        return {
            "accounts": self.accounts,
            "entries": self.entries,
            "lines": self.lines,
            "budgets": self.budgets,
            "goals": self.goals,
            "payees": self.payees,
            "openings": self.openings,
            "feed_rows": self.feed_rows,
            "inbox_rows": self.inbox_rows,
            "dismissed_transfer_matches": self.dismissed_transfer_matches,
        }


def can_import(book) -> bool:
    """
    A YNAB import is a whole set of books, not an addition to one.

    Merging it into a book that already has transactions would double history
    wherever the two overlap and leave no way to tell which copy is which -- so a
    book with any live entry is refused, and told to start a fresh book or clear
    this one. So is one with any bank-feed row: an uploaded but uncategorized
    statement has no entry yet, and is the same history again.
    """
    if BankTransaction.objects.filter(book=book).exists():
        return False
    return not JournalEntry.objects.filter(book=book).exclude(status=JournalEntry.STATUS_VOID).exists()


@transaction.atomic
def apply_plan(book, plan: ImportPlan, user=None, on_progress=None) -> ApplyResult:
    """Write the plan. Nothing here is conditional on anything the plan did not decide."""
    if not can_import(book):
        raise ApplyError(
            "This set of books already has transactions. A YNAB import brings a whole set of books, so it needs an "
            "empty one -- create a new set of books, or delete the existing transactions first."
        )

    report = on_progress or (lambda *_: None)

    report(5, "Creating your accounts")
    groups = _create_groups(book, plan)
    institutions = _create_institutions(book, plan)
    accounts = _create_accounts(book, plan, groups, institutions)

    report(15, "Creating your payees")
    payees = _create_payees(book, plan)

    report(25, "Creating your budgets")
    budgets = _create_budgets(book, plan, accounts)

    report(40, "Importing your transactions")
    entries, lines, feed_rows = _create_entries(book, plan, accounts, payees, budgets, report)
    inbox_rows = _create_inbox_rows(book, plan, accounts)

    report(82, "Checking for look-alike transfers")
    # The detector reads every feed row just written; let the planner know they exist.
    _refresh_planner_statistics()
    # Every real transfer in the export is already one entry with one feed row per
    # side. What the transfer detector would pair across the imported rows is a
    # coincidence of amount and date; left in, it would offer to void real entries.
    dismissed = dismiss_all_candidates(book)

    report(85, "Setting your savings goals")
    goals = _create_goals(book, plan, accounts)

    report(92, "Recording your opening balances")
    openings = _create_openings(book, plan, accounts)

    report(98, "Checking the numbers")
    _refresh_planner_statistics()
    return ApplyResult(
        accounts=len(accounts),
        entries=entries,
        lines=lines,
        budgets=len(budgets),
        goals=goals,
        payees=len(payees),
        openings=openings,
        feed_rows=feed_rows + inbox_rows,
        inbox_rows=inbox_rows,
        dismissed_transfer_matches=dismissed,
    )


# Every table the import fills.
ANALYZED_MODELS = (JournalLine, JournalEntry, Account, AccountGroup, Budget, GoalAllocation, Payee, BankTransaction)


def _refresh_planner_statistics():
    """
    Tell Postgres how much was just written, before anyone reads it.

    The import lands ~13,000 lines in one go. Until the tables are analyzed, the
    planner's statistics still describe them as they were before the import --
    often empty -- so it picks nested loops and the dashboard's net-worth aggregate
    runs for minutes. Autovacuum fixes that eventually, but the user reaches the
    dashboard seconds after the import, and autovacuum can be kept off these tables
    by the locks this very transaction holds. ANALYZE inside the import's
    transaction counts the rows it inserted, and the statistics commit with them.

    A savepoint, so a failed ANALYZE costs a slow first page rather than the import.
    """
    if connection.vendor != "postgresql":
        return

    tables = ", ".join(model._meta.db_table for model in ANALYZED_MODELS)
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"ANALYZE {tables}")
    except DatabaseError:
        logger.warning("Could not refresh planner statistics after a YNAB import", exc_info=True)


def _create_groups(book, plan: ImportPlan) -> dict[str, AccountGroup]:
    """
    `get_or_create` rather than `bulk_create`: a book can arrive here with the stock
    chart already applied (onboarding skipped, then the user found their export), and
    `AccountGroup` is unique on name per book.
    """
    groups = {}
    for spec in plan.groups:
        group, _created = AccountGroup.objects.get_or_create(
            book=book,
            name=spec.name,
            defaults={
                "account_type": spec.account_type,
                "description": spec.description,
                "is_system": spec.is_system,
                "sort_order": spec.sort_order,
            },
        )
        groups[spec.name] = group
    return groups


def _create_institutions(book, plan: ImportPlan) -> dict[str, Institution]:
    return {
        name: Institution.objects.get_or_create(book=book, name=name)[0] for name in plan.institutions if name.strip()
    }


def _create_accounts(book, plan: ImportPlan, groups, institutions) -> dict[tuple[str, str], Account]:
    """
    One `Account` per planned account, keyed the way the plan refers to them.

    An account name is only unique within its type, so the key is the pair -- an
    asset `RESP` and an expense `RESP` are two different accounts and the lines have
    to reach the right one.
    """
    existing = {
        (account.account_group.account_type, account.name): account
        for account in Account.objects.filter(book=book).select_related("account_group")
    }

    to_create = []
    for spec in plan.accounts:
        if spec.key in existing:
            continue
        to_create.append(
            Account(
                book=book,
                name=spec.name,
                account_group=groups[spec.group],
                institution=institutions.get(spec.institution),
                has_feed=spec.has_feed,
                is_system=spec.is_system,
                sort_order=spec.sort_order,
            )
        )
    Account.objects.bulk_create(to_create, batch_size=BATCH_SIZE)

    return {
        (account.account_group.account_type, account.name): account
        for account in Account.objects.filter(book=book).select_related("account_group")
    }


def _create_payees(book, plan: ImportPlan) -> dict[str, Payee]:
    """
    A YNAB export names over a thousand payees; they go in one statement.

    `ignore_conflicts` because the book may already carry some of them, and because
    the payee list is the one part of this import that is safe to be relaxed about.
    """
    Payee.objects.bulk_create(
        [Payee(book=book, name=name) for name in plan.payees],
        batch_size=BATCH_SIZE,
        ignore_conflicts=True,
    )
    return {payee.name: payee for payee in Payee.objects.filter(book=book)}


def _create_budgets(book, plan: ImportPlan, accounts) -> dict[tuple[int, object], Budget]:
    """
    Budgets before transactions, because `JournalLine.budget` points at them.

    Deduplicated on the way in: `Budget` is unique per book, month and category, and
    two YNAB categories that the user merged into one account would otherwise collide
    at the database rather than here.
    """
    # A book that doesn't budget income before it arrives gets no income budgets
    # (D1's back-fill exists only to zero an income envelope it won't show).
    skip_income = not book.budget_future_income
    seen = {}
    for spec in plan.budgets:
        account = accounts.get(spec.category)
        if account is None:
            continue
        if skip_income and account.account_group.account_type == ACCOUNT_TYPE_INCOME:
            continue
        seen.setdefault((account.id, spec.month), spec.amount)

    Budget.objects.bulk_create(
        [
            Budget(book=book, category_id=account_id, month=month, budget_amount=amount)
            for (account_id, month), amount in seen.items()
        ],
        batch_size=BATCH_SIZE,
    )
    return {(budget.category_id, budget.month): budget for budget in Budget.objects.filter(book=book)}


def _create_entries(book, plan: ImportPlan, accounts, payees, budgets, report) -> tuple[int, int, int]:
    """
    The transactions themselves, in batches of entries, their lines, their feed rows.

    Entries are inserted first because a line needs an entry id; the lines are then
    inserted through `bulk_create_for_import`, which resolves the budget link from an
    in-memory map rather than one query per line (see the queryset's docstring for
    what that costs and what it skips). Feed rows last: each entry's own row, then
    the mirror rows the bank feed's rule derives from the lines -- the rows
    `sync_transfer` would have made, without a save per transfer.
    """
    budget_map = {key: budget.id for key, budget in budgets.items()}
    total_entries = total_lines = total_feed = 0
    batches = max(1, (len(plan.entries) + BATCH_SIZE - 1) // BATCH_SIZE)

    for number, start in enumerate(range(0, len(plan.entries), BATCH_SIZE), start=1):
        chunk = plan.entries[start : start + BATCH_SIZE]

        entries = JournalEntry.objects.bulk_create(
            [
                JournalEntry(
                    book=book,
                    entry_date=spec.entry_date,
                    description=spec.description,
                    payee=payees.get(spec.payee) if spec.payee else None,
                    source=JournalEntry.SOURCE_IMPORT,
                    # Posted, not draft: a draft entry is excluded from every balance,
                    # so an imported history in draft would report a net worth of zero.
                    status=JournalEntry.STATUS_POSTED,
                )
                for spec in chunk
            ],
            batch_size=BATCH_SIZE,
        )

        lines = []
        lines_by_entry = []
        for spec, entry in zip(chunk, entries, strict=True):
            entry_lines = [
                JournalLine(
                    book=book,
                    journal_entry=entry,
                    account=accounts[line.account],
                    dr_amount=line.dr,
                    cr_amount=line.cr,
                    # Never reconciled on import: the user reconciles against statements.
                    is_reconciled=False,
                    is_cleared=line.is_cleared,
                )
                for line in spec.lines
            ]
            lines.extend(entry_lines)
            lines_by_entry.append(entry_lines)
        JournalLine.objects.bulk_create_for_import(lines, budget_map, batch_size=BATCH_SIZE)

        primaries = []
        for spec, entry, entry_lines in zip(chunk, entries, lines_by_entry, strict=True):
            if spec.feed is not None:
                primary = _bank_transaction(book, spec.feed, accounts, journal_entry=entry)
                primaries.append((primary, entry_lines))
        feed = [primary for primary, _lines in primaries]
        for primary, entry_lines in primaries:
            feed.extend(mirror_rows_for(primary, entry_lines))
        BankTransaction.objects.bulk_create(feed, batch_size=BATCH_SIZE)

        total_entries += len(entries)
        total_lines += len(lines)
        total_feed += len(feed)
        done = f"{total_entries:,} of {len(plan.entries):,}"
        report(40 + int(42 * number / batches), f"Importing your transactions ({done})")

    return total_entries, total_lines, total_feed


def _bank_transaction(book, spec, accounts, journal_entry=None) -> BankTransaction:
    return BankTransaction(
        book=book,
        account=accounts[spec.account],
        journal_entry=journal_entry,
        amount=spec.amount,
        posted_date=spec.posted_date,
        description=spec.description,
        merchant_name=spec.merchant,
        source=BankTransaction.SOURCE_YNAB,
        raw={"ynab": {"row": spec.row_index}},
    )


def _create_inbox_rows(book, plan: ImportPlan, accounts) -> int:
    """The rows YNAB never categorised: uncategorized feed rows, waiting in the Inbox."""
    rows = [_bank_transaction(book, spec, accounts) for spec in plan.inbox_rows]
    BankTransaction.objects.bulk_create(rows, batch_size=BATCH_SIZE)
    return len(rows)


def _create_goals(book, plan: ImportPlan, accounts) -> int:
    """
    A goal per savings category, funded month by month.

    Each goal gets the equity account the plan made for it, which the savings
    category's spending already posts to. Created one at a time: there are a
    handful, and `Goal.save()` still backs any goal whose account is missing.
    """
    created = 0
    for spec in plan.goals:
        if Goal.objects.filter(book=book, name=spec.name).exists():
            continue
        goal = Goal.objects.create(
            book=book,
            name=spec.name,
            target_amount=spec.target_amount,
            description="Imported from YNAB",
            account=accounts.get(spec.account) if spec.account else None,
            # Left not-funded deliberately: the user is very likely still saving for it.
            is_complete=False,
            closed_at=timezone.now() if spec.closed else None,
        )
        GoalAllocation.objects.bulk_create(
            [GoalAllocation(book=book, goal=goal, month=month, amount=amount) for month, amount in spec.allocations],
            batch_size=BATCH_SIZE,
        )
        created += 1
    return created


def _create_openings(book, plan: ImportPlan, accounts) -> int:
    """
    The `Starting Balance` rows, through the same code the onboarding step uses.

    Grouped by date first: that helper takes one date for a whole batch, while a real
    export carries a different one per account (each opened when the user added it).
    Posting them all on one date would put the money in the wrong months and break
    the reconciliation.
    """
    by_date: dict[object, list[OpeningRow]] = {}
    for spec in plan.openings:
        account = accounts.get(spec.account)
        if account is None or spec.amount == ZERO:
            continue
        by_date.setdefault(spec.as_of, []).append(OpeningRow(account=account, amount=spec.amount))

    created = 0
    for as_of, rows in sorted(by_date.items()):
        created += len(create_opening_balances(book, rows, as_of=as_of))
    return created


def equity_account(book) -> Account | None:
    return Account.objects.filter(book=book, is_system=True, account_group__account_type=EQUITY_TYPE).first()


def net_worth_of(book) -> Decimal:
    """Assets minus liabilities, the same sum the dashboard runs."""
    from django.db.models import Sum

    totals = (
        JournalLine.objects.filter(
            book=book,
            account__account_group__account_type__in=(ASSET, "liability"),
        )
        .filter(counted_entries("journal_entry__"))
        .aggregate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
    )
    return (totals["dr"] or ZERO) - (totals["cr"] or ZERO)
