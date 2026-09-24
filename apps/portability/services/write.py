"""
Serialising rows to the zip/CSV archive (§3 of `docs/export-import-plan.md`).

Pure: takes already-built row dicts (Python values, one dict per CSV row,
keyed by column name) and returns bytes. Nothing here queries the database --
that is Phase 2's `export.py`, which will gather rows from a book and call
`build_archive_bytes`. Kept separate so the round-trip test in Phase 1 can
exercise the whole write -> read path without a database, and so `read.py`'s
counterpart has something to be tested against before Phase 2 exists.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal

from django.utils import timezone as dj_timezone

from .schema import (
    ACCOUNTS_FILE,
    BUDGET_FILE,
    DATA_FILES,
    FILE_COLUMNS,
    FORMAT,
    FORMAT_VERSION,
    JOURNAL_FILE,
    MANIFEST_FILE,
    RECONCILIATIONS_FILE,
    Column,
    encode_cell,
)

FILE_COLUMN_LISTS = FILE_COLUMNS


def _json_default(value):
    """
    A safety net for `checks`/`omitted`/`source`, not a licence to skip
    stringifying amounts deliberately (§3.5's "amounts are strings, always").
    Callers should already have turned a Decimal into `str(...)` before it
    reaches here; this only saves a caller that forgot from crashing.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_csv(columns: tuple[Column, ...], rows: list[dict]) -> bytes:
    """
    `rows`: dicts keyed by column name, values already Python-typed (Decimal,
    date, datetime, bool, int, str, or None). UTF-8 with a BOM (§3.5) --
    `utf-8-sig` on the way in is what pairs with this on the way out.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([column.name for column in columns])
    for row in rows:
        writer.writerow([encode_cell(column.kind, row.get(column.name)) for column in columns])
    return buf.getvalue().encode("utf-8-sig")


def build_archive_bytes(
    *,
    accounts: list[dict],
    journal: list[dict],
    budget: list[dict],
    reconciliations: list[dict] = (),
    source: dict,
    checks: dict,
    omitted: dict,
    exported_at: datetime | None = None,
) -> bytes:
    """
    Assemble the zip: the data CSVs plus `manifest.json` (§3.1). A caller with
    no statements to carry may leave `reconciliations` out; the file is still
    written, header only. `checks` and
    `omitted` are written through as-is -- Phase 2's `export.py` is what
    computes them from the database (§6); this function only serialises
    whatever it is given.
    """
    exported_at = exported_at or dj_timezone.now()

    rows_by_file = {
        ACCOUNTS_FILE: accounts,
        JOURNAL_FILE: journal,
        BUDGET_FILE: budget,
        RECONCILIATIONS_FILE: list(reconciliations),
    }
    file_bytes = {filename: write_csv(FILE_COLUMN_LISTS[filename], rows_by_file[filename]) for filename in DATA_FILES}

    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        # UTC, always -- the file should not depend on the exporting server's
        # local timezone (same reasoning as archived_at's own encoding).
        "exported_at": exported_at.astimezone(UTC).isoformat(),
        "source": source,
        "files": {
            filename: {
                "rows": len(rows_by_file[filename]),
                "sha256": hashlib.sha256(file_bytes[filename]).hexdigest(),
            }
            for filename in DATA_FILES
        },
        "checks": checks,
        "omitted": omitted,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_FILE, json.dumps(manifest, indent=2, default=_json_default, sort_keys=True))
        for filename in DATA_FILES:
            zf.writestr(filename, file_bytes[filename])
    return buf.getvalue()
