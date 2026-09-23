"""
Gathering a team's books into the row dicts `write.py` serialises (§7 Phase 2).

Everything here is a handful of `select_related`/`prefetch_related` queries and
some dict-building -- no judgement calls. Every judgement was made in
`schema.py` (what a column means) and `write.py`/`read.py` (how it travels);
this module's only job is to read the database in the shape those modules
already agree on.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Max, Min

from apps.accounts.models import Account, AccountGroup, Institution, Payee
from apps.bank_feed.models import BankTransaction, TransferMatchDismissal
from apps.budget.models import Budget, GoalAllocation
from apps.journal.models import JournalEntry, JournalLine
from apps.reconciliation.models import Reconciliation

from . import schema
from .schema import (
    KIND_BUDGET,
    KIND_DECIMAL,
    KIND_GOAL,
    UNCATEGORIZED_STATUS,
    encode_cell,
)

ZERO = Decimal("0")

# Rows across the three files combined, above which the export refuses rather
# than building an archive in memory (§3.6). 200,000 lines is roughly 15x the
# YNAB sample's 13,335 -- comfortably past anything real today, and the point
# past which a synchronous, in-memory export stops being the right design.
EXPORT_MAX_ROWS = 200_000


class ExportError(ValueError):
    """User-facing: the export was refused before anything was built."""


def _money(value) -> str:
    """A Decimal (or None, read as zero) as the canonical amount string (§3.5)."""
    return encode_cell(KIND_DECIMAL, value if value is not None else ZERO)


def _not_void(**extra):
    return JournalLine.objects.filter(**extra).exclude(journal_entry__status=JournalEntry.STATUS_VOID)


def build_row_count(team) -> int:
    """
    The row count `EXPORT_MAX_ROWS` guards, without building anything. Cheap:
    three `count()` queries, no row construction.
    """
    accounts = Account.objects.filter(team=team).count()
    journal = (
        JournalLine.objects.filter(team=team).count()
        + BankTransaction.objects.filter(team=team, journal_entry__isnull=True).count()
    )
    budget = Budget.objects.filter(team=team).count() + GoalAllocation.objects.filter(team=team).count()
    return accounts + journal + budget


def build_archive(team) -> tuple[list[dict], list[dict], list[dict]]:
    """
    `(accounts, journal_rows, budget_rows)` -- ready for
    `write.build_archive_bytes`. Raises `ExportError` over `EXPORT_MAX_ROWS`.
    """
    total_rows = build_row_count(team)
    if total_rows > EXPORT_MAX_ROWS:
        raise ExportError(
            f"This team has {total_rows:,} rows to export, more than the {EXPORT_MAX_ROWS:,} this export "
            "supports. Contact support -- this is a real limit worth raising, not a wall."
        )

    accounts = _build_accounts(team)
    journal = _build_journal_rows(team)
    budget = _build_budget_rows(team)
    _assert_every_feed_row_travels(team, journal)
    return accounts, journal, budget


def _assert_every_feed_row_travels(team, journal_rows: list[dict]) -> None:
    """
    Exactly as many feed rows in the file as in the database, checked before
    the file is written.

    `build_checks` counts feed rows straight from the database while the rows
    are assembled by walking journal lines, and three separate bugs have made
    those two disagree: a row no line could carry was dropped, two rows
    claiming one line lost the loser, and one row on an entry with two lines
    on its account was emitted twice. Every one of them surfaced the same way
    -- an import that ran, wiped the destination, failed `_verify` with
    "feed_counts did not match after writing" and rolled back -- which says
    nothing about which end was wrong or why.

    So the invariant is asserted here instead, where it can name the mismatch
    and where nothing has been written yet. A file that would fail the
    importer's gate is never produced in the first place.
    """
    in_file = sum(1 for row in journal_rows if row["feed_source"] is not None)
    in_db = BankTransaction.objects.filter(team=team).count()
    if in_file != in_db:
        raise ExportError(
            f"This export is inconsistent and has not been written: the team has {in_db:,} bank feed row(s) "
            f"but the file would carry {in_file:,}. This is a bug in the exporter, not something you did -- "
            "please report it."
        )


def _build_accounts(team) -> list[dict]:
    """One row per account, with its group, institution and goal folded in (§2.1)."""
    accounts = (
        Account.objects.filter(team=team)
        .select_related("account_group", "institution", "goal")
        .order_by(*Account._meta.ordering)
    )
    return [
        schema.build_row(
            (schema.ACCOUNT, account),
            (schema.ACCOUNT_GROUP, account.account_group),
            (schema.INSTITUTION, account.institution),
            (schema.GOAL, getattr(account, "goal", None)),
            columns=schema.ACCOUNTS_COLUMNS,
        )
        for account in accounts
    ]


def _place_feed_rows(team) -> tuple[dict[tuple[int, int], BankTransaction], list[BankTransaction]]:
    """
    Decide where every categorized feed row goes: `(lookup, unplaceable)`.

    A feed row rides on the journal line whose account it shares, keyed
    `(journal_entry_id, account_id)`. Categorizing writes exactly one
    `BankTransaction` per (entry, feed account) pair, so in healthy data every
    row places and `unplaceable` is empty.

    Two states break that, and both exist in real books:

    * the row's entry has **no line on the row's own account** -- the link
      points at an entry that, as far as the ledger is concerned, never
      touched that account;
    * **two rows claim the same line**, so only one can ride on it.

    Both were previously silent: the lookup overwrote on collision and simply
    never asked about the orphan, so those rows vanished from journal.csv
    while `build_checks` went on counting them straight from the database. The
    export then produced a file that failed its own integrity gate on import
    ("feed_counts did not match after writing") with nothing to say about why.

    They are returned instead of dropped, and the caller emits them as
    standalone feed rows (§2.4's uncategorized shape). That loses the entry
    link and nothing else -- the entry, its lines and every balance are
    carried by the line rows regardless -- and it is the honest landing place:
    a feed row whose account the entry never touched has no category the
    product can name. `bank_transaction_to_feed_row()` picks an arbitrary line
    for such a row today, which is the same class of bug the split work fixed.
    The count is reported in the manifest so the repair is disclosed rather
    than done quietly.
    """
    line_accounts: set[tuple[int, int]] = set(
        JournalLine.objects.filter(team=team).values_list("journal_entry_id", "account_id")
    )

    lookup: dict[tuple[int, int], BankTransaction] = {}
    unplaceable: list[BankTransaction] = []

    # Ordered by id so which of two colliding rows keeps the line is stable
    # across exports of the same team, rather than query-order dependent.
    rows = (
        BankTransaction.objects.filter(team=team, journal_entry__isnull=False).select_related("account").order_by("id")
    )
    for bank_tx in rows:
        key = (bank_tx.journal_entry_id, bank_tx.account_id)
        if key in line_accounts and key not in lookup:
            lookup[key] = bank_tx
        else:
            unplaceable.append(bank_tx)
    return lookup, unplaceable


def _build_journal_rows(team) -> list[dict]:
    """
    One row per journal line, then one per feed row that rides on no line
    (§2.4) -- the uncategorized ones, plus any the ledger could not place.
    """
    feed_lookup, unplaceable = _place_feed_rows(team)

    lines = (
        JournalLine.objects.filter(team=team)
        .select_related("journal_entry", "journal_entry__payee", "account")
        .order_by("journal_entry__entry_date", "journal_entry_id", "id")
    )

    rows = []
    # A feed row rides on exactly *one* line. The lookup is keyed by
    # (entry, account), and an entry may hold more than one line on the same
    # account -- a split with a leg pointing back at the bank account is the
    # ordinary way that happens -- so consulting it per line would hand the
    # same `BankTransaction` to two rows and write it twice on import. That
    # was one feed row in the database against two in the file, which the
    # integrity gate caught as `feed_counts did not match after writing`.
    # Lines arrive ordered by (entry_date, entry_id, id), so the row rides on
    # the lowest-id line of its account and the choice is stable.
    attached: set[int] = set()
    for line in lines:
        bank_tx = feed_lookup.get((line.journal_entry_id, line.account_id))
        if bank_tx is not None:
            if bank_tx.id in attached:
                bank_tx = None
            else:
                attached.add(bank_tx.id)
        row = schema.build_row(
            (schema.JOURNAL_ENTRY, line.journal_entry),
            (schema.JOURNAL_LINE, line),
            (schema.BANK_TRANSACTION, bank_tx),
            columns=schema.JOURNAL_COLUMNS,
        )
        row["account_name"] = line.account.name  # informational only (§2.2)
        rows.append(row)

    # Feed rows belonging to no line: never categorized, or categorized
    # against an entry no line of which uses their account (`_place_feed_rows`).
    # Entry-level and line-level columns are genuinely absent here, which is
    # what passing None for those two maps records.
    uncategorized = list(
        BankTransaction.objects.filter(team=team, journal_entry__isnull=True).select_related("account")
    )
    for bank_tx in uncategorized + unplaceable:
        row = schema.build_row(
            (schema.JOURNAL_ENTRY, None),
            (schema.JOURNAL_LINE, None),
            (schema.BANK_TRANSACTION, bank_tx),
            columns=schema.JOURNAL_COLUMNS,
        )
        row["status"] = UNCATEGORIZED_STATUS
        row["account_id"] = bank_tx.account_id
        row["account_name"] = bank_tx.account.name
        rows.append(row)

    return rows


def build_reconciliation_rows(team) -> list[dict]:
    """
    One row per statement (`reconciliations.csv`), drafts and undone ones
    included -- a draft's ticks and an undone statement's links both ride on
    the journal lines, and would dangle without their row.
    """
    statements = Reconciliation.objects.filter(team=team).order_by("account_id", "statement_date", "id")
    return [
        schema.build_row((schema.RECONCILIATION, rec), columns=schema.RECONCILIATIONS_COLUMNS) for rec in statements
    ]


def _build_budget_rows(team) -> list[dict]:
    """One row per monthly amount -- a `Budget` or a `GoalAllocation`, told apart by `kind` (§2.1)."""
    rows = []

    budgets = Budget.objects.filter(team=team).select_related("category").order_by("month", "category__name")
    for budget in budgets:
        row = schema.build_row((schema.BUDGET, budget), columns=schema.BUDGET_COLUMNS)
        row["kind"] = KIND_BUDGET
        row["account_name"] = budget.category.name
        rows.append(row)

    allocations = (
        GoalAllocation.objects.filter(team=team).select_related("goal", "goal__account").order_by("month", "goal__name")
    )
    for allocation in allocations:
        row = schema.build_row((schema.GOAL_ALLOCATION, allocation), columns=schema.BUDGET_COLUMNS)
        row["kind"] = KIND_GOAL
        row["account_name"] = allocation.goal.account.name if allocation.goal.account_id else allocation.goal.name
        rows.append(row)

    return rows


def build_checks(team) -> dict:
    """
    The integrity gate's data (§6), computed **from the database** -- never
    from the rows this same module just built, or the check would only prove
    the exporter agrees with itself.
    """
    non_void_lines = _not_void(team=team).select_related("account", "account__account_group")

    trial_dr = ZERO
    trial_cr = ZERO
    balances: dict[int, Decimal] = defaultdict(lambda: ZERO)
    net_worth = ZERO

    for line in non_void_lines:
        dr, cr = line.dr_amount, line.cr_amount
        trial_dr += dr
        trial_cr += cr
        balances[line.account_id] += dr - cr
        if line.account.account_group.account_type in ("asset", "liability"):
            net_worth += dr - cr

    budget_totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for budget in Budget.objects.filter(team=team):
        budget_totals[budget.month.isoformat()] += budget.budget_amount

    goal_totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for allocation in GoalAllocation.objects.filter(team=team).select_related("goal"):
        if allocation.goal.account_id:
            goal_totals[allocation.goal.account_id] += allocation.amount

    date_bounds = JournalEntry.objects.filter(team=team).aggregate(first=Min("entry_date"), last=Max("entry_date"))

    statements = Reconciliation.objects.filter(team=team)
    statement_counts = {
        "total": statements.count(),
        "completed": statements.filter(status=Reconciliation.STATUS_COMPLETED).count(),
        "reconciled_lines": JournalLine.objects.filter(team=team, is_reconciled=True).count(),
    }

    accounts_count = Account.objects.filter(team=team).count()
    entries_count = JournalEntry.objects.filter(team=team).count()
    goals_count = Account.objects.filter(team=team, goal__isnull=False).count()

    # `uncategorized` counts what the *file* will hold as uncategorized, which
    # is every row with no entry plus every row no line could carry -- still
    # derived from the database (both are database queries), not read back off
    # the rows just built, so the check cannot degrade into the exporter
    # agreeing with itself.
    _placed, unplaceable = _place_feed_rows(team)
    feed_counts = {
        "total": BankTransaction.objects.filter(team=team).count(),
        "uncategorized": (
            BankTransaction.objects.filter(team=team, journal_entry__isnull=True).count() + len(unplaceable)
        ),
        "archived": BankTransaction.objects.filter(team=team, is_archived=True).count(),
        "mirror": BankTransaction.objects.filter(team=team, is_transfer_mirror=True).count(),
    }

    return {
        "counts": {
            "accounts": accounts_count,
            "entries": entries_count,
            "goals": goals_count,
        },
        "trial_balance": {"dr": _money(trial_dr), "cr": _money(trial_cr)},
        "account_balances": {str(account_id): _money(total) for account_id, total in balances.items()},
        "net_worth": _money(net_worth),
        "budget_totals": {month: _money(total) for month, total in budget_totals.items()},
        "goal_totals": {str(account_id): _money(total) for account_id, total in goal_totals.items()},
        "date_range": {
            "first": date_bounds["first"].isoformat() if date_bounds["first"] else None,
            "last": date_bounds["last"].isoformat() if date_bounds["last"] else None,
        },
        "feed_counts": feed_counts,
        # Its own key rather than a member of `counts`, so a version-1 archive
        # (which has none) still verifies: `_verify` checks it only when present.
        "statements": statement_counts,
    }


def build_omitted(team) -> dict:
    """
    What did not make it into the file, and why (§2.3, §2.4) -- shown in the
    export summary so a loss is a stated fact, not a surprise discovered
    later.
    """
    empty_account_groups = AccountGroup.objects.filter(team=team, accounts__isnull=True).count()
    unused_institutions = Institution.objects.filter(team=team, accounts__isnull=True).count()

    used_payee_ids = set(
        JournalEntry.objects.filter(team=team, payee__isnull=False).values_list("payee_id", flat=True).distinct()
    )
    unused_payees = Payee.objects.filter(team=team).exclude(id__in=used_payee_ids).count()

    dismissed_transfer_pairs = TransferMatchDismissal.objects.filter(team=team).count()

    # Not a row that was dropped -- the row travels -- but a *link* that could
    # not be carried, which is the same kind of stated loss. See
    # `_place_feed_rows` for when this is non-zero.
    _placed, unplaceable = _place_feed_rows(team)

    return {
        "empty_account_groups": empty_account_groups,
        "unused_institutions": unused_institutions,
        "unused_payees": unused_payees,
        "dismissed_transfer_pairs": dismissed_transfer_pairs,
        "unlinked_feed_rows": len(unplaceable),
    }
