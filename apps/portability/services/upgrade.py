"""
The `format_version` upgrade chain (§3.7 of `docs/export-import-plan.md`).

Each step is a pure function over already-*parsed* rows -- a dict of
`{"accounts", "journal_rows", "budget_rows", "reconciliations"}` lists, in the
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


# {from_version: fn(tables) -> tables at from_version + 1}
CHAIN: dict[int, Callable[[dict], dict]] = {1: upgrade_1_to_2}


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
