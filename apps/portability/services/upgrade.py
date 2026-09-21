"""
The `format_version` upgrade chain (§3.7 of `docs/export-import-plan.md`).

Empty at v1 -- there is nothing older to upgrade *from* yet. This module
exists so the first breaking change to the format has somewhere to go: a new
`upgrade_1_to_2(tables)` function gets added here and chained into `CHAIN`
below. Each step is a pure function over already-*parsed* rows (dicts keyed
by column name, in the shape `read.py` produces), never over raw CSV/zip
bytes, so steps compose and are testable in isolation from parsing.

Because the chain is empty, `upgrade_to_current` always raises for any
`from_version` older than `FORMAT_VERSION` -- which is the honest behaviour
today: nothing produced a version 1 file before format_version 1 existed, so
there is truthfully no upgrade path, not a missing one.
"""

from __future__ import annotations

from collections.abc import Callable

from .schema import FORMAT_VERSION, DocumentError

# {from_version: fn(tables) -> tables at from_version + 1}
CHAIN: dict[int, Callable[[dict], dict]] = {}


def upgrade_to_current(tables: dict, from_version: int) -> dict:
    """
    Walk `CHAIN` from `from_version` up to `FORMAT_VERSION`, applying each
    step in order. Raises `DocumentError` the moment a step is missing --
    there is no partial upgrade.
    """
    version = from_version
    while version < FORMAT_VERSION:
        step = CHAIN.get(version)
        if step is None:
            raise DocumentError(
                f"This export uses format version {from_version}, which this version of Koala Budget no "
                "longer knows how to read."
            )
        tables = step(tables)
        version += 1
    return tables
