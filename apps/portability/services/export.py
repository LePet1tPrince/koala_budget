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

from .schema import (
    KIND_DECIMAL,
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

    return _build_accounts(team), _build_journal_rows(team), _build_budget_rows(team)


def _build_accounts(team) -> list[dict]:
    accounts = (
        Account.objects.filter(team=team)
        .select_related("account_group", "institution", "goal")
        .order_by(*Account._meta.ordering)
    )

    rows = []
    for account in accounts:
        group = account.account_group
        institution = account.institution
        goal = getattr(account, "goal", None)

        rows.append(
            {
                "account_id": account.id,
                "name": account.name,
                "account_type": group.account_type,
                "group_name": group.name,
                "group_description": group.description,
                "group_is_system": group.is_system,
                "group_sort_order": group.sort_order,
                "group_is_archived": group.is_archived,
                "group_archived_at": group.archived_at,
                "institution": institution.name if institution else None,
                "institution_is_archived": institution.is_archived if institution else None,
                "institution_archived_at": institution.archived_at if institution else None,
                "has_feed": account.has_feed,
                "is_system": account.is_system,
                "sort_order": account.sort_order,
                "is_archived": account.is_archived,
                "archived_at": account.archived_at,
                "goal_name": goal.name if goal else None,
                "goal_description": goal.description if goal else "",
                "goal_target_amount": goal.target_amount if goal else None,
                "goal_target_date": goal.target_date if goal else None,
                "goal_is_complete": goal.is_complete if goal else None,
                "goal_is_archived": goal.is_archived if goal else None,
                "goal_archived_at": goal.archived_at if goal else None,
                "goal_order": goal.order if goal else None,
            }
        )
    return rows


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


def _feed_columns(bank_tx: BankTransaction | None) -> dict:
    if bank_tx is None:
        return {
            "feed_source": None,
            "feed_amount": None,
            "feed_posted_date": None,
            # "" not None, mirroring goal_description on a non-goal row: the
            # discriminator (feed_source) carries the None, the KIND_STR
            # payload column carries the empty string.
            "feed_description": "",
            "feed_merchant": None,
            "feed_is_mirror": False,
            "feed_is_archived": False,
            "feed_archived_at": None,
        }
    return {
        "feed_source": bank_tx.source,
        "feed_amount": bank_tx.amount,
        "feed_posted_date": bank_tx.posted_date,
        "feed_description": bank_tx.description,
        "feed_merchant": bank_tx.merchant_name,
        "feed_is_mirror": bank_tx.is_transfer_mirror,
        "feed_is_archived": bank_tx.is_archived,
        "feed_archived_at": bank_tx.archived_at,
    }


def _build_journal_rows(team) -> list[dict]:
    feed_lookup, unplaceable = _place_feed_rows(team)

    lines = (
        JournalLine.objects.filter(team=team)
        .select_related("journal_entry", "journal_entry__payee", "account")
        .order_by("journal_entry__entry_date", "journal_entry_id", "id")
    )

    rows = []
    for line in lines:
        entry = line.journal_entry
        bank_tx = feed_lookup.get((entry.id, line.account_id))
        rows.append(
            {
                "entry_id": entry.id,
                "entry_date": entry.entry_date,
                "payee": entry.payee.name if entry.payee_id else None,
                "description": entry.description,
                "source": entry.source,
                "status": entry.status,
                "account_id": line.account_id,
                "account_name": line.account.name,
                "entry_is_archived": entry.is_archived,
                "entry_archived_at": entry.archived_at,
                "dr_amount": line.dr_amount,
                "cr_amount": line.cr_amount,
                "is_cleared": line.is_cleared,
                "is_reconciled": line.is_reconciled,
                "is_archived": line.is_archived,
                "archived_at": line.archived_at,
                **_feed_columns(bank_tx),
            }
        )

    # Uncategorized feed rows: no JournalLine at all, so nothing above touches
    # them. Entry-level and line-level columns are genuinely absent, not
    # false -- there is no entry and no line to report them for (§2.4).
    uncategorized = list(
        BankTransaction.objects.filter(team=team, journal_entry__isnull=True).select_related("account")
    )
    # Plus any categorized row no line could carry (see `_place_feed_rows`),
    # which travels in the same shape and arrives as a row to review.
    for bank_tx in uncategorized + unplaceable:
        rows.append(
            {
                "entry_id": None,
                "entry_date": None,
                "payee": None,
                "description": "",
                "source": "",
                "status": UNCATEGORIZED_STATUS,
                "account_id": bank_tx.account_id,
                "account_name": bank_tx.account.name,
                "entry_is_archived": None,
                "entry_archived_at": None,
                "dr_amount": None,
                "cr_amount": None,
                "is_cleared": None,
                "is_reconciled": None,
                "is_archived": None,
                "archived_at": None,
                **_feed_columns(bank_tx),
            }
        )

    return rows


def _build_budget_rows(team) -> list[dict]:
    rows = []

    budgets = Budget.objects.filter(team=team).select_related("category").order_by("month", "category__name")
    for budget in budgets:
        rows.append(
            {
                "kind": "budget",
                "month": budget.month,
                "account_id": budget.category_id,
                "account_name": budget.category.name,
                "amount": budget.budget_amount,
                "notes": "",
                "is_archived": budget.is_archived,
                "archived_at": budget.archived_at,
            }
        )

    allocations = (
        GoalAllocation.objects.filter(team=team).select_related("goal", "goal__account").order_by("month", "goal__name")
    )
    for allocation in allocations:
        rows.append(
            {
                "kind": "goal",
                "month": allocation.month,
                "account_id": allocation.goal.account_id,
                "account_name": allocation.goal.account.name if allocation.goal.account_id else allocation.goal.name,
                "amount": allocation.amount,
                "notes": allocation.notes,
                "is_archived": allocation.is_archived,
                "archived_at": allocation.archived_at,
            }
        )

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
