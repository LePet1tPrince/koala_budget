"""
Applying an archive to a team: read, safety-export, wipe, write, verify
(§4.4, §6, §7 Phase 3 of `docs/export-import-plan.md`).

One `transaction.atomic` block, in the order that ordering exists to enforce:
**parse and validate first, wipe second, write third** (§6). A file that
cannot be imported must never have cost the user their books, and a check
that fails after the write must roll back everything, including the wipe --
which is exactly why the wipe has no transaction of its own (`wipe.py`'s
docstring).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from apps.accounts.models import Account, AccountGroup, Institution, Payee
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.bank_feed.models import BankTransaction
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.journal.models import JournalEntry, JournalLine
from apps.reconciliation.models import Reconciliation

from . import export, read, schema, write
from .schema import UNCATEGORIZED_STATUS
from .wipe import WipeCounts, wipe_team

ZERO = Decimal("0")


class ApplyError(ValueError):
    """User-facing: the archive was refused, or the import did not verify."""


@dataclass
class ApplyResult:
    wipe_counts: WipeCounts
    institutions: int
    payees: int
    account_groups: int
    accounts: int
    goals: int
    budgets: int
    goal_allocations: int
    entries: int
    lines: int
    bank_transactions: int
    reconciliations: int = 0

    def as_dict(self) -> dict:
        return {
            "wipe_counts": self.wipe_counts.as_dict(),
            "institutions": self.institutions,
            "payees": self.payees,
            "account_groups": self.account_groups,
            "accounts": self.accounts,
            "goals": self.goals,
            "budgets": self.budgets,
            "goal_allocations": self.goal_allocations,
            "entries": self.entries,
            "lines": self.lines,
            "bank_transactions": self.bank_transactions,
            "reconciliations": self.reconciliations,
        }


def build_safety_archive(team) -> bytes:
    """
    A copy of `team`'s **own current** books, taken before anything about it
    changes. This is the recovery path for "I imported the wrong file" (§4.4)
    -- it uses the exact same export path a user's own Export button does, so
    it is exactly as trustworthy as the feature it is insurance for.

    **Callers must persist the result durably -- outside `apply_archive`'s
    transaction -- before calling `apply_archive`.** The whole point of a
    safety copy is that it survives the wipe+import failing and rolling back;
    if it were taken and saved *inside* that same `transaction.atomic` block,
    a rollback would undo the save along with everything else, and the one
    scenario the safety copy exists for -- the import going wrong -- is
    exactly the scenario in which it would vanish. `tasks.py` is where this
    function is actually called, and it calls it, and saves the result,
    before opening the transaction `apply_archive` wraps.
    """
    accounts, journal_rows, budget_rows = export.build_archive(team)
    checks = export.build_checks(team)
    omitted = export.build_omitted(team)
    return write.build_archive_bytes(
        accounts=accounts,
        journal=journal_rows,
        budget=budget_rows,
        reconciliations=export.build_reconciliation_rows(team),
        source={"team_name": team.name},
        checks=checks,
        omitted=omitted,
    )


@transaction.atomic
def apply_archive(team, archive_bytes: bytes, *, user=None, on_progress=None) -> ApplyResult:
    """
    Wipe `team` and write `archive_bytes` into it. One transaction: any
    failure, including a failed check at the end, leaves `team` exactly as it
    was (§6's "parse and validate first, wipe second, write third") -- and
    since the two `AuditEvent`s below are ordinary writes inside that same
    transaction, a failure rolls them back too, rather than leaving an audit
    trail describing a wipe that did not, in the end, happen.

    Does **not** take the safety copy -- see `build_safety_archive`'s
    docstring for why that has to happen before this is even called.
    """
    report = on_progress or (lambda *_: None)

    report(5, "Reading the export")
    tables = read.read_archive(archive_bytes)  # raises DocumentError -- nothing written yet

    report(15, "Clearing this team's existing books")
    wipe_counts = wipe_team(team)
    log_event(AuditEvent.DATA_WIPED, user=user, team=team, metadata={"counts": wipe_counts.as_dict()})

    report(25, "Writing accounts")
    institution_by_name = _insert_institutions(team, tables.accounts)
    payee_by_name = _insert_payees(team, tables.journal_rows)
    group_by_name = _insert_account_groups(team, tables.accounts)
    account_id_map = _insert_accounts(team, tables.accounts, institution_by_name, group_by_name)

    report(40, "Writing goals")
    goal_id_by_account_id = _insert_goals(team, tables.accounts, account_id_map)

    report(50, "Writing budgets")
    _insert_budgets(team, tables.budget_rows, account_id_map)
    _insert_goal_allocations(team, tables.budget_rows, account_id_map, goal_id_by_account_id)

    report(55, "Writing statements")
    reconciliation_id_map = _insert_reconciliations(team, tables.reconciliations, account_id_map)

    report(60, "Writing the journal")
    entry_id_map, uncategorized_rows, lines_created = _insert_journal(
        team, tables.journal_rows, account_id_map, payee_by_name, reconciliation_id_map
    )

    report(85, "Writing the bank feed")
    bank_transactions_created = _insert_bank_transactions(
        team, tables.journal_rows, uncategorized_rows, account_id_map, entry_id_map
    )

    report(95, "Checking the numbers")
    _verify(tables, account_id_map, team)

    result = ApplyResult(
        wipe_counts=wipe_counts,
        institutions=len(institution_by_name),
        payees=len(payee_by_name),
        account_groups=len(group_by_name),
        accounts=len(account_id_map),
        goals=len(goal_id_by_account_id),
        budgets=sum(1 for row in tables.budget_rows if row["kind"] == "budget"),
        goal_allocations=sum(1 for row in tables.budget_rows if row["kind"] == "goal"),
        entries=len(entry_id_map),
        lines=lines_created,
        bank_transactions=bank_transactions_created,
        reconciliations=len(reconciliation_id_map),
    )
    log_event(AuditEvent.DATA_IMPORTED, user=user, team=team, metadata={"result": result.as_dict()})
    report(100, "Done")
    return result


# --- inserts, in the order the foreign keys require ------------------------


def _first_by_key(rows, key):
    """The first row per distinct value of `key(row)`, in first-seen order."""
    seen = {}
    order = []
    for row in rows:
        value = key(row)
        if value is not None and value not in seen:
            seen[value] = row
            order.append(value)
    return order, seen


def _insert_institutions(team, account_rows) -> dict[str, int]:
    order, by_name = _first_by_key(account_rows, lambda row: row["institution"])
    objs = [
        Institution(
            team=team,
            # NOT NULL, and the column is blank on every account with no
            # institution, so a name first seen on such a row decodes it None.
            is_archived=bool(by_name[name]["institution_is_archived"]),
            **schema.model_kwargs(schema.INSTITUTION, by_name[name], skip={"is_archived"}),
        )
        for name in order
    ]
    created = Institution.objects.bulk_create(objs)
    return {obj.name: obj.id for obj in created}


def _insert_payees(team, journal_rows) -> dict[str, int]:
    order, _by_name = _first_by_key(journal_rows, lambda row: row["payee"])
    objs = [Payee(team=team, name=name) for name in order]
    created = Payee.objects.bulk_create(objs)
    return {obj.name: obj.id for obj in created}


def _insert_account_groups(team, account_rows) -> dict[str, int]:
    order, by_name = _first_by_key(account_rows, lambda row: row["group_name"])
    objs = [AccountGroup(team=team, **schema.model_kwargs(schema.ACCOUNT_GROUP, by_name[name])) for name in order]
    created = AccountGroup.objects.bulk_create(objs)
    return {obj.name: obj.id for obj in created}


def _insert_accounts(team, account_rows, institution_by_name, group_by_name) -> dict[int, int]:
    objs = [
        Account(
            team=team,
            account_group_id=group_by_name[row["group_name"]],
            institution_id=institution_by_name.get(row["institution"]) if row["institution"] else None,
            **schema.model_kwargs(schema.ACCOUNT, row, skip={"id"}),
        )
        for row in account_rows
    ]
    # bulk_create preserves the caller's ordering in its return value, so this
    # zip is a positional match with account_rows -- see Django's own docs on
    # bulk_create's return value ordering.
    created = Account.objects.bulk_create(objs)
    return {row["account_id"]: obj.id for row, obj in zip(account_rows, created, strict=True)}


def _insert_goals(team, account_rows, account_id_map) -> dict[int, int]:
    """
    `{new_account_id: new_goal_id}`. Built with `bulk_create`, never
    `Goal.save()` -- that method creates its own backing `Account` when
    `pk is None and not account_id`, which is exactly wrong here: the account
    already exists and is already mapped (`apps/budget/models.py:124`).
    """
    goal_rows = [row for row in account_rows if row["goal_name"] is not None]
    objs = [
        Goal(
            team=team,
            account_id=account_id_map[row["account_id"]],
            # Three NOT NULL columns that read.py does not require a goal row
            # to fill, the way _REQUIRED_WITH_FEED_SOURCE requires a feed
            # row's, so a hand-edited file can still leave them blank.
            is_complete=bool(row["goal_is_complete"]),
            is_archived=bool(row["goal_is_archived"]),
            order=row["goal_order"] or 0,
            **schema.model_kwargs(schema.GOAL, row, skip={"is_complete", "is_archived", "order"}),
        )
        for row in goal_rows
    ]
    created = Goal.objects.bulk_create(objs)
    return {obj.account_id: obj.id for obj in created}


def _insert_budgets(team, budget_rows, account_id_map) -> None:
    objs = [
        Budget(
            team=team,
            category_id=account_id_map[row["account_id"]],
            **schema.model_kwargs(schema.BUDGET, row, skip={"category"}),
        )
        for row in budget_rows
        if row["kind"] == "budget"
    ]
    Budget.objects.bulk_create(objs)


def _insert_goal_allocations(team, budget_rows, account_id_map, goal_id_by_account_id) -> None:
    objs = []
    for row in budget_rows:
        if row["kind"] != "goal":
            continue
        new_account_id = account_id_map[row["account_id"]]
        objs.append(
            GoalAllocation(
                team=team,
                goal_id=goal_id_by_account_id[new_account_id],
                **schema.model_kwargs(schema.GOAL_ALLOCATION, row, skip={"goal"}),
            )
        )
    GoalAllocation.objects.bulk_create(objs)


def _insert_reconciliations(team, rows, account_id_map) -> dict[int, int]:
    """`{file reconciliation_id: new id}`. Before the journal, whose lines point at these."""
    objs = [
        Reconciliation(
            team=team,
            account_id=account_id_map[row["account_id"]],
            adjustment_amount=row["adjustment_amount"] or Decimal("0"),
            **schema.model_kwargs(schema.RECONCILIATION, row, skip={"id", "account", "adjustment_amount"}),
        )
        for row in rows
    ]
    created = Reconciliation.objects.bulk_create(objs)
    return {row["reconciliation_id"]: obj.id for row, obj in zip(rows, created, strict=True)}


def _insert_journal(
    team, journal_rows, account_id_map, payee_by_name, reconciliation_id_map=None
) -> tuple[dict[int, int], list[dict], int]:
    """`(entry_id_map, uncategorized_rows, lines_created)`."""
    entry_order: list[int] = []
    entry_row_by_id: dict[int, dict] = {}
    line_rows_by_entry: dict[int, list[dict]] = defaultdict(list)
    uncategorized_rows: list[dict] = []

    for row in journal_rows:
        if row["status"] == UNCATEGORIZED_STATUS:
            uncategorized_rows.append(row)
            continue
        file_entry_id = row["entry_id"]
        if file_entry_id not in entry_row_by_id:
            entry_row_by_id[file_entry_id] = row
            entry_order.append(file_entry_id)
        line_rows_by_entry[file_entry_id].append(row)

    entry_objs = [
        JournalEntry(
            team=team,
            payee_id=payee_by_name.get(entry_row_by_id[file_id]["payee"]),
            **schema.model_kwargs(schema.JOURNAL_ENTRY, entry_row_by_id[file_id], skip={"id", "payee"}),
        )
        for file_id in entry_order
    ]
    created_entries = JournalEntry.objects.bulk_create(entry_objs)
    entry_id_map = {file_id: obj.id for file_id, obj in zip(entry_order, created_entries, strict=True)}

    line_objs = [
        JournalLine(
            team=team,
            journal_entry_id=entry_id_map[file_id],
            account_id=account_id_map[row["account_id"]],
            reconciliation_id=(reconciliation_id_map or {}).get(row.get("reconciliation_id")),
            **schema.model_kwargs(schema.JOURNAL_LINE, row, skip={"account", "reconciliation"}),
        )
        for file_id in entry_order
        for row in line_rows_by_entry[file_id]
    ]

    # (account_id, month) -> Budget.id, resolved once here rather than a query
    # per line -- see JournalLine.save()'s own docstring on why that matters
    # at import volume, and bulk_create_for_import for why it is the shared
    # implementation rather than a second one that could drift from it.
    budget_map = {(b.category_id, b.month): b.id for b in Budget.objects.filter(team=team)}
    JournalLine.objects.bulk_create_for_import(line_objs, budget_map)

    return entry_id_map, uncategorized_rows, len(line_objs)


def _insert_bank_transactions(team, journal_rows, uncategorized_rows, account_id_map, entry_id_map) -> int:
    """
    A straight insert, not a reconstruction: `feed_is_mirror` already says
    which leg is the mirror, so `transfer_mirror.sync_transfer` is never
    called -- re-deriving the mirror relationship would be exactly the
    inference §2.4 exists to avoid.
    """
    objs = []
    for row in journal_rows:
        if row["status"] == UNCATEGORIZED_STATUS or row["feed_source"] is None:
            continue
        objs.append(
            BankTransaction(
                team=team,
                account_id=account_id_map[row["account_id"]],
                journal_entry_id=entry_id_map[row["entry_id"]],
                **schema.model_kwargs(schema.BANK_TRANSACTION, row),
            )
        )
    for row in uncategorized_rows:
        objs.append(
            BankTransaction(
                team=team,
                account_id=account_id_map[row["account_id"]],
                journal_entry=None,
                **schema.model_kwargs(schema.BANK_TRANSACTION, row),
            )
        )
    BankTransaction.objects.bulk_create(objs)
    return len(objs)


# --- the integrity gate (§6) -------------------------------------------


def _verify(tables: read.Tables, account_id_map: dict[int, int], team) -> None:
    """
    Recompute `checks` from the destination and compare against what the file
    said before anything was deleted. Any mismatch raises -- which, inside
    `apply_archive`'s `@transaction.atomic`, rolls back everything, wipe
    included. Money is compared as the canonical strings `schema.py` already
    produces, so this is a plain equality, not a tolerance.
    """
    expected = tables.manifest.checks
    if not expected:
        # An archive built without checks (e.g. a hand-assembled test file)
        # has nothing to verify against; nothing to compare is not a failure.
        return

    actual = export.build_checks(team)

    _require_equal("trial_balance", expected.get("trial_balance"), actual["trial_balance"])
    _require_equal("net_worth", expected.get("net_worth"), actual["net_worth"])
    _require_equal("date_range", expected.get("date_range"), actual["date_range"])
    _require_equal("budget_totals", expected.get("budget_totals"), actual["budget_totals"])
    _require_equal("feed_counts", expected.get("feed_counts"), actual["feed_counts"])
    _require_equal("counts", expected.get("counts"), actual["counts"])
    if "statements" in expected:  # absent from version-1 archives, which carried none
        _require_equal("statements", expected["statements"], actual["statements"])

    _require_equal_remapped(
        "account_balances", expected.get("account_balances"), actual["account_balances"], account_id_map
    )
    _require_equal_remapped("goal_totals", expected.get("goal_totals"), actual["goal_totals"], account_id_map)


def _require_equal(label: str, expected, actual) -> None:
    if expected != actual:
        raise ApplyError(
            f"The import did not verify ({label} did not match after writing). Nothing was changed -- "
            "the whole import ran in one transaction and it has been rolled back."
        )


def _require_equal_remapped(label: str, expected: dict | None, actual: dict, account_id_map: dict[int, int]) -> None:
    """
    `expected` is keyed by the file's account ids; `actual` is keyed by the
    ids those accounts just received. Remap one side rather than the other so
    a truly missing key (an id that never made it into `account_id_map`) is a
    loud `KeyError`-turned-`ApplyError`, not a silently-skipped comparison.
    """
    if expected is None:
        expected = {}
    remapped = {}
    for file_account_id_str, value in expected.items():
        try:
            new_id = account_id_map[int(file_account_id_str)]
        except (KeyError, ValueError) as error:
            raise ApplyError(
                f"The import did not verify ({label} referenced an account that was never written)."
            ) from error
        remapped[str(new_id)] = value
    if remapped != actual:
        raise ApplyError(
            f"The import did not verify ({label} did not match after writing). Nothing was changed -- "
            "the whole import ran in one transaction and it has been rolled back."
        )
