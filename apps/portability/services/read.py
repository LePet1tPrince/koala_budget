"""
Parsing and validating the zip/CSV archive (§3, §6 of `docs/export-import-plan.md`).

`read_archive(data: bytes) -> Tables` is the whole surface. Pure -- no
database access, and nothing here writes anything. It is deliberately strict:
a file that will not parse, or does not describe a set of books that balances,
raises `DocumentError` with a message written to be shown to the user
directly, rather than being coerced into something plausible. Phase 3's
`apply.py` calls this before touching a book's data (§6's "parse and validate
first, wipe second, write third"), and the wizard's preview screen calls it
before anything is queued.

Business-rule validation here is intentionally the three checks named in §6 --
entries balance, an entry's repeated columns agree, every reference resolves
-- plus the enum-membership and required-field checks needed to keep a
malformed file from being silently misread as zero or blank. It is not an
exhaustive presence matrix over every column combination (a goal's
`archived_at` being blank means nothing about whether the goal exists, since
"never archived" and "no goal" look identical there); Phase 5's round-trip
test is what catches an encode/decode asymmetry that this file's checks would
not.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from . import upgrade
from .schema import (
    ACCOUNT_TYPES,
    ACCOUNTS_FILE,
    BUDGET_FILE,
    BUDGET_ROW_KINDS,
    COLUMNS_ADDED_IN,
    DATA_FILES,
    ENTRY_SOURCES,
    ENTRY_STATUSES,
    FEED_SOURCES,
    FILE_COLUMNS,
    FILES_ADDED_IN,
    FORMAT,
    FORMAT_VERSION,
    JOURNAL_FILE,
    MANIFEST_FILE,
    RECONCILIATION_STATUSES,
    RECONCILIATIONS_FILE,
    UNCATEGORIZED_STATUS,
    DocumentError,
    decode_cell,
)

# The entry-level columns that are repeated on every line of a JournalEntry
# (§3.3) and must therefore agree across all of an entry's rows.
_REPEATED_ENTRY_COLUMNS = (
    "entry_date",
    "payee",
    "description",
    "source",
    "status",
    "entry_is_archived",
    "entry_archived_at",
)

# feed_* columns that must be present together whenever a line has a feed row
# at all, i.e. whenever feed_source is non-blank.
#
# Only columns whose model field can neither be null nor be meaningfully empty
# belong here. Three feed_* columns are deliberately excluded:
#
#   feed_merchant     BankTransaction.merchant_name is nullable, so None is a
#                     real value rather than a missing one.
#   feed_is_mirror    a plain False, not blank -- it decodes to a value either
#                     way, so there is nothing to enforce.
#   feed_description  BankTransaction.description is NOT NULL but "" is an
#                     ordinary value for it (an empty CSV column, a Plaid row
#                     with no description, a mirror copied from a primary that
#                     had none). It is KIND_STR, so a blank cell decodes to ""
#                     and never to None -- listing it here would test a
#                     condition that cannot arise.
#
# That last one was a real bug, hit on real books: feed_description used to be
# KIND_STR_OR_NONE, so an empty description decoded to None and this check
# rejected it as missing -- making the exporter capable of producing an
# archive its own importer refused. See BANK_TRANSACTION in schema.py.
_REQUIRED_WITH_FEED_SOURCE = ("feed_amount", "feed_posted_date", "feed_is_archived")

ZERO = Decimal("0")


@dataclass
class Manifest:
    format: str
    format_version: int
    exported_at: datetime | None
    source: dict
    files: dict
    checks: dict
    omitted: dict


@dataclass
class Tables:
    manifest: Manifest
    accounts: list = field(default_factory=list)
    journal_rows: list = field(default_factory=list)
    budget_rows: list = field(default_factory=list)
    reconciliations: list = field(default_factory=list)
    # Non-fatal: a per-file sha256 in the manifest did not match the file's
    # actual contents (§3.1) -- shown to the user, does not block the import.
    hash_warnings: list = field(default_factory=list)


def read_archive(data: bytes) -> Tables:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise DocumentError("This file is not a valid Koala Budget export (it is not a zip archive).") from None

    with zf:
        manifest = _read_manifest(zf)
        _check_version(manifest.format_version)

        version = manifest.format_version
        expected_files = [filename for filename in DATA_FILES if FILES_ADDED_IN.get(filename, 1) <= version]
        names = set(zf.namelist())
        missing_files = [filename for filename in expected_files if filename not in names]
        if missing_files:
            raise DocumentError(f"This export is missing: {', '.join(missing_files)}.")

        file_bytes = {filename: zf.read(filename) for filename in expected_files}

    hash_warnings = _check_hashes(manifest, file_bytes)

    def read_file(filename):
        if filename not in file_bytes:
            return []
        return _read_csv(file_bytes[filename], filename, _columns_for(filename, version))

    parsed = upgrade.upgrade_to_current(
        {
            "accounts": read_file(ACCOUNTS_FILE),
            "journal_rows": read_file(JOURNAL_FILE),
            "budget_rows": read_file(BUDGET_FILE),
            "reconciliations": read_file(RECONCILIATIONS_FILE),
        },
        from_version=version,
    )
    accounts = parsed["accounts"]
    journal_rows = parsed["journal_rows"]
    budget_rows = parsed["budget_rows"]
    reconciliations = parsed["reconciliations"]

    _validate_enums(accounts, journal_rows, budget_rows)
    _validate_journal_row_shape(journal_rows)
    _validate_entries_balance(journal_rows)
    _validate_entry_columns_consistent(journal_rows)

    account_ids = {row["account_id"] for row in accounts}
    _validate_account_references(journal_rows, budget_rows, account_ids)
    _validate_months(budget_rows)
    _validate_reconciliations(reconciliations, journal_rows, account_ids)

    return Tables(
        manifest=manifest,
        accounts=accounts,
        journal_rows=journal_rows,
        budget_rows=budget_rows,
        reconciliations=reconciliations,
        hash_warnings=hash_warnings,
    )


def _columns_for(filename: str, version: int) -> tuple:
    """The columns an archive of `version` has for `filename` -- later ones are `upgrade.py`'s to fill."""
    return tuple(
        column for column in FILE_COLUMNS[filename] if COLUMNS_ADDED_IN.get((filename, column.name), 1) <= version
    )


# --- manifest ----------------------------------------------------------


def _read_manifest(zf: zipfile.ZipFile) -> Manifest:
    if MANIFEST_FILE not in zf.namelist():
        raise DocumentError(f"This export is missing {MANIFEST_FILE}.")
    try:
        raw = json.loads(zf.read(MANIFEST_FILE).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise DocumentError(f"{MANIFEST_FILE} is not valid JSON.") from None
    if not isinstance(raw, dict):
        raise DocumentError(f"{MANIFEST_FILE} is not a valid manifest.")

    if raw.get("format") != FORMAT:
        raise DocumentError("This file is not a Koala Budget export.")

    try:
        format_version = int(raw["format_version"])
    except (KeyError, TypeError, ValueError):
        raise DocumentError(f"{MANIFEST_FILE} does not name a valid format_version.") from None

    exported_at = None
    if raw.get("exported_at"):
        try:
            exported_at = datetime.fromisoformat(raw["exported_at"])
        except ValueError:
            exported_at = None  # informational only; a bad value here should not block the import

    return Manifest(
        format=raw["format"],
        format_version=format_version,
        exported_at=exported_at,
        source=raw.get("source") or {},
        files=raw.get("files") or {},
        checks=raw.get("checks") or {},
        omitted=raw.get("omitted") or {},
    )


def _check_version(declared_version: int) -> None:
    if declared_version > FORMAT_VERSION:
        raise DocumentError(
            "This export was made by a newer version of Koala Budget. Update this instance, or export "
            "again from the older one."
        )
    if declared_version < FORMAT_VERSION:
        # Refuse up front, before any file is read, if there is no path from
        # this version; the upgrade itself runs once the files are parsed.
        upgrade.check_path(declared_version)


def _check_hashes(manifest: Manifest, file_bytes: dict) -> list[str]:
    warnings = []
    for filename, data in file_bytes.items():
        expected = (manifest.files.get(filename) or {}).get("sha256")
        if not expected:
            continue
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            warnings.append(
                f"{filename} was modified after it was exported -- its contents no longer match the export's checksum."
            )
    return warnings


# --- CSV parsing ---------------------------------------------------------


def _read_csv(raw: bytes, filename: str, columns: tuple) -> list[dict]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentError(f"{filename} is not valid UTF-8.") from None

    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    missing_columns = [column.name for column in columns if column.name not in header]
    if missing_columns:
        raise DocumentError(f"{filename} is missing required column(s): {', '.join(missing_columns)}.")

    rows = []
    for row_number, raw_row in enumerate(reader, start=2):  # the header occupies line 1
        decoded = {
            column.name: decode_cell(
                column.kind, raw_row.get(column.name, ""), file=filename, row_number=row_number, column=column.name
            )
            for column in columns
        }
        rows.append(decoded)
    return rows


# --- business-rule validation (§6) ---------------------------------------


def _validate_enums(accounts: list[dict], journal_rows: list[dict], budget_rows: list[dict]) -> None:
    for row in accounts:
        if row["account_type"] not in ACCOUNT_TYPES:
            raise DocumentError(
                f"{ACCOUNTS_FILE}: account_id {row['account_id']} has an unknown account_type '{row['account_type']}'."
            )

    for row in journal_rows:
        if row["status"] not in ENTRY_STATUSES:
            raise DocumentError(
                f"journal.csv: row for entry_id {row['entry_id']} has an unknown status '{row['status']}'."
            )
        if row["status"] != UNCATEGORIZED_STATUS and row["source"] not in ENTRY_SOURCES:
            raise DocumentError(f"journal.csv: entry_id {row['entry_id']} has an unknown source '{row['source']}'.")
        if row["feed_source"] is not None and row["feed_source"] not in FEED_SOURCES:
            raise DocumentError(
                f"journal.csv: entry_id {row['entry_id']} has an unknown feed_source '{row['feed_source']}'."
            )

    for row in budget_rows:
        if row["kind"] not in BUDGET_ROW_KINDS:
            raise DocumentError(
                f"{BUDGET_FILE}: row for account_id {row['account_id']}, month {row['month']} has an "
                f"unknown kind '{row['kind']}'."
            )


def _validate_journal_row_shape(journal_rows: list[dict]) -> None:
    """
    Required-field checks that the cell codec deliberately does not make
    (§2.6 -- blank-vs-required is a row-kind question, not a cell-type one).

    Kept to what a silently-wrong import actually needs guarded: a missing
    account_id or amount on a real line would otherwise decode to `None` and
    either vanish from a reference check with a confusing message or,
    treated as zero, misstate a balance without ever raising at all.
    """
    for row_number, row in enumerate(journal_rows, start=2):
        where = f"journal.csv, row {row_number}"

        if row["account_id"] is None:
            raise DocumentError(f"{where}: account_id is required.")

        if row["status"] == UNCATEGORIZED_STATUS:
            continue

        if row["entry_id"] is None:
            raise DocumentError(f"{where}: entry_id is required unless status is '{UNCATEGORIZED_STATUS}'.")
        if row["dr_amount"] is None or row["cr_amount"] is None:
            raise DocumentError(f"{where}: entry_id {row['entry_id']}: dr_amount and cr_amount are both required.")

        if row["feed_source"] is not None:
            missing = [col for col in _REQUIRED_WITH_FEED_SOURCE if row[col] is None]
            if missing:
                raise DocumentError(
                    f"{where}: entry_id {row['entry_id']} has feed_source set but is missing {', '.join(missing)}."
                )


def _validate_entries_balance(journal_rows: list[dict]) -> None:
    totals: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for row in journal_rows:
        entry_id = row["entry_id"]
        if entry_id is None:  # uncategorized feed row -- belongs to no entry (§6)
            continue
        totals[entry_id][0] += row["dr_amount"] or ZERO
        totals[entry_id][1] += row["cr_amount"] or ZERO

    for entry_id, (dr_total, cr_total) in totals.items():
        if dr_total != cr_total:
            raise DocumentError(
                f"journal.csv: entry_id {entry_id} does not balance (debits {dr_total}, credits {cr_total})."
            )


def _validate_entry_columns_consistent(journal_rows: list[dict]) -> None:
    seen: dict[int, tuple] = {}
    for row_number, row in enumerate(journal_rows, start=2):
        entry_id = row["entry_id"]
        if entry_id is None:
            continue
        signature = tuple(row[column] for column in _REPEATED_ENTRY_COLUMNS)
        if entry_id not in seen:
            seen[entry_id] = signature
        elif seen[entry_id] != signature:
            raise DocumentError(
                f"journal.csv, row {row_number}: entry_id {entry_id}'s {', '.join(_REPEATED_ENTRY_COLUMNS)} "
                "do not match the values on this entry's other line(s)."
            )


def _validate_account_references(journal_rows: list[dict], budget_rows: list[dict], account_ids: set) -> None:
    for row_number, row in enumerate(journal_rows, start=2):
        if row["account_id"] not in account_ids:
            raise DocumentError(
                f"journal.csv, row {row_number}: account_id {row['account_id']} does not appear in {ACCOUNTS_FILE}."
            )

    for row_number, row in enumerate(budget_rows, start=2):
        if row["account_id"] is None:
            raise DocumentError(f"{BUDGET_FILE}, row {row_number}: account_id is required.")
        if row["account_id"] not in account_ids:
            raise DocumentError(
                f"{BUDGET_FILE}, row {row_number}: account_id {row['account_id']} does not appear in {ACCOUNTS_FILE}."
            )


def _validate_months(budget_rows: list[dict]) -> None:
    for row_number, row in enumerate(budget_rows, start=2):
        month = row["month"]
        if month is None:
            raise DocumentError(f"{BUDGET_FILE}, row {row_number}: month is required.")
        if month.day != 1:
            raise DocumentError(
                f"{BUDGET_FILE}, row {row_number}: month {month.isoformat()} is not the first of the month."
            )


def _validate_reconciliations(reconciliations: list[dict], journal_rows: list[dict], account_ids: set) -> None:
    """Statements name real accounts and statuses, at most one draft per account, and lines name real statements."""
    ids = set()
    drafts = set()
    for row_number, row in enumerate(reconciliations, start=2):
        where = f"{RECONCILIATIONS_FILE}, row {row_number}"
        if row["reconciliation_id"] is None:
            raise DocumentError(f"{where}: reconciliation_id is required.")
        if row["reconciliation_id"] in ids:
            raise DocumentError(f"{where}: reconciliation_id {row['reconciliation_id']} appears twice.")
        ids.add(row["reconciliation_id"])
        if row["account_id"] not in account_ids:
            raise DocumentError(f"{where}: account_id {row['account_id']} does not appear in {ACCOUNTS_FILE}.")
        if row["status"] not in RECONCILIATION_STATUSES:
            raise DocumentError(f"{where}: unknown status '{row['status']}'.")
        if row["statement_date"] is None or row["statement_balance"] is None:
            raise DocumentError(f"{where}: statement_date and statement_balance are required.")
        if row["status"] == "draft":
            if row["account_id"] in drafts:
                raise DocumentError(f"{where}: account_id {row['account_id']} has more than one draft statement.")
            drafts.add(row["account_id"])

    for row_number, row in enumerate(journal_rows, start=2):
        if row.get("reconciliation_id") is not None and row["reconciliation_id"] not in ids:
            raise DocumentError(
                f"{JOURNAL_FILE}, row {row_number}: reconciliation_id {row['reconciliation_id']} does not appear "
                f"in {RECONCILIATIONS_FILE}."
            )
