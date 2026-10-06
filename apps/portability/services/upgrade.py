"""
The `format_version` upgrade chain (§3.7 of `docs/export-import-plan.md`).

Each step is a pure function over already-*parsed* rows -- a dict of
`{"accounts", "journal_rows", "budget_rows", "reconciliations", "goal_links"}` lists, in the
shape `read.py` produces -- never over raw CSV/zip bytes, so steps compose and
are testable in isolation from parsing. `read.py` reads an older archive with
only the files and columns that version had (`schema.FILES_ADDED_IN`,
`schema.COLUMNS_ADDED_IN`) and hands the result here.
"""

from __future__ import annotations

from collections.abc import Callable

from .schema import FORMAT_VERSION, DocumentError


def upgrade_1_to_2(tables: dict) -> dict:
    """
    Version 2 added statements (apps.reconciliation). A version-1 archive has
    none: no `reconciliations.csv`, and no line points at one. Lines it marks
    reconciled stay reconciled -- they become the opening balance of the
    destination's first statement, exactly as reconciled lines from before
    statements existed do in place.
    """
    for row in tables["journal_rows"]:
        row.setdefault("reconciliation_id", None)
    tables["reconciliations"] = []
    return tables


def upgrade_2_to_3(tables: dict) -> dict:
    """Version 3 added `goal_closed_at`. Before it, no goal could be closed."""
    for row in tables["accounts"]:
        row.setdefault("goal_closed_at", None)
    return tables


def upgrade_3_to_4(tables: dict) -> dict:
    """Version 4 added `hidden_from_budget`. Before it, no category could be hidden."""
    for row in tables["accounts"]:
        row.setdefault("hidden_from_budget", False)
    return tables


def upgrade_4_to_5(tables: dict) -> dict:
    """
    Version 5 added goal-linked accounts. Before it no account fed a goal, every
    goal took money out when it left (the model default) and none had a monthly
    plan.
    """
    for row in tables["accounts"]:
        row.setdefault("goal_outflow", None)
        row.setdefault("goal_monthly_contribution", None)
    tables["goal_links"] = []
    return tables


def upgrade_5_to_6(tables: dict) -> dict:
    """
    Version 6 has one void state. Before it a feed row could be archived while
    its entry stayed posted (the entry then counted toward nothing anyway), and
    entries and lines carried archive flags nothing read.

    `feed_is_archived` becomes `feed_is_void`; an entry with any archived row is
    voided, and every row on a void entry is void. The entry and row counts
    this changes are kept in `void_upgrade`, so the integrity gate can still
    compare against the manifest the archive was written with.
    """
    rows = tables["journal_rows"]
    for row in rows:
        row["feed_is_void"] = bool(row.pop("feed_is_archived", False))
        row["feed_voided_at"] = row.pop("feed_archived_at", None)
        for retired in ("entry_is_archived", "entry_archived_at", "is_archived", "archived_at"):
            row.pop(retired, None)

    void_entries = {
        row["entry_id"]
        for row in rows
        if row.get("entry_id") is not None
        and (row.get("status") == "void" or (row.get("feed_source") is not None and row["feed_is_void"]))
    }
    newly_voided_entries = {
        row["entry_id"] for row in rows if row.get("entry_id") in void_entries and row.get("status") != "void"
    }
    newly_voided_rows = 0
    for row in rows:
        if row.get("entry_id") in void_entries:
            row["status"] = "void"
            if row.get("feed_source") is not None and not row["feed_is_void"]:
                row["feed_is_void"] = True
                newly_voided_rows += 1

    tables["void_upgrade"] = {"entry_ids": newly_voided_entries, "rows": newly_voided_rows}
    return tables


# {from_version: fn(tables) -> tables at from_version + 1}
CHAIN: dict[int, Callable[[dict], dict]] = {
    1: upgrade_1_to_2,
    2: upgrade_2_to_3,
    3: upgrade_3_to_4,
    4: upgrade_4_to_5,
    5: upgrade_5_to_6,
}


def check_path(from_version: int) -> None:
    """Raise `DocumentError` unless every step from `from_version` up to `FORMAT_VERSION` exists."""
    for version in range(from_version, FORMAT_VERSION):
        if version not in CHAIN:
            raise DocumentError(
                f"This export uses format version {from_version}, which this version of Koala Budget no "
                "longer knows how to read."
            )


def upgrade_to_current(tables: dict, from_version: int) -> dict:
    """
    Walk `CHAIN` from `from_version` up to `FORMAT_VERSION`, applying each
    step in order. Raises `DocumentError` the moment a step is missing --
    there is no partial upgrade.
    """
    check_path(from_version)
    for version in range(from_version, FORMAT_VERSION):
        tables = CHAIN[version](tables)
    return tables
