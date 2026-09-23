"""
The export/import format, in one place.

This module is read three ways: `write.py` uses `FIELD_MAPS` to pull a cell
value off a model instance, `read.py` uses the same maps (and the per-file
column lists below) to parse a cell back into a Python value, and
`tests/test_schema.py` walks each model's `_meta.get_fields()` against both
halves of every `FieldMap` -- so a concrete field that belongs to neither
`columns` nor `omitted` fails a test instead of silently not travelling.

See `docs/export-import-plan.md` §2-3 for why the format is shaped this way.
That document's own column tables were built by reading each model's
*declared* fields, which is exactly the mistake this module's completeness
test exists to catch -- and did catch, twice, while this module was being
written (`goal_archived_at`, `BankTransaction.amount`). The tables here were
built from `model._meta.get_fields()`, not by inspection, for that reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from apps.accounts.models import (
    ACCOUNT_TYPE_CHOICES,
    Account,
    AccountGroup,
    Institution,
    Payee,
)
from apps.bank_feed.models import BankTransaction
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.journal.models import JournalEntry, JournalLine
from apps.reconciliation.models import Reconciliation

FORMAT = "koala-budget-export"
# 2: statements (`reconciliations.csv`, and `reconciliation_id` on journal
# lines). A version-1 archive still imports -- see `upgrade.py` -- with no
# statements, since it never had any to carry.
FORMAT_VERSION = 2

MANIFEST_FILE = "manifest.json"
ACCOUNTS_FILE = "accounts.csv"
JOURNAL_FILE = "journal.csv"
BUDGET_FILE = "budget.csv"
RECONCILIATIONS_FILE = "reconciliations.csv"
DATA_FILES = (ACCOUNTS_FILE, JOURNAL_FILE, BUDGET_FILE, RECONCILIATIONS_FILE)

#: The format version each file / column first appeared in. An older archive
#: is read without them and `upgrade.py` fills them in, so adding a file or a
#: column is not a reason to refuse every export made before it.
FILES_ADDED_IN = {RECONCILIATIONS_FILE: 2}
COLUMNS_ADDED_IN = {(JOURNAL_FILE, "reconciliation_id"): 2}

# journal.csv's `status` column carries every `JournalEntry.status` value plus
# this one, file-level sentinel for a pending bank-feed row that belongs to no
# entry at all (§2.4 of the plan). It is deliberately not a `JournalEntry`
# status and never touches that model.
UNCATEGORIZED_STATUS = "uncategorized"
ENTRY_STATUSES = frozenset({*dict(JournalEntry.STATUS_CHOICES), UNCATEGORIZED_STATUS})
ENTRY_SOURCES = frozenset(dict(JournalEntry.SOURCE_CHOICES))
RECONCILIATION_STATUSES = frozenset(dict(Reconciliation.STATUS_CHOICES))
FEED_SOURCES = frozenset(dict(BankTransaction.SOURCE_CHOICES))
ACCOUNT_TYPES = frozenset(dict(ACCOUNT_TYPE_CHOICES))

# budget.csv's `kind` column: which of the two models a row represents.
KIND_BUDGET = "budget"
KIND_GOAL = "goal"
BUDGET_ROW_KINDS = frozenset({KIND_BUDGET, KIND_GOAL})

# Columns that exist in a file for a human to read but are not any model's own
# data -- the importer parses the id column next to them and ignores these.
INFORMATIONAL_COLUMNS = frozenset({"account_name"})

# Columns the writer synthesizes to tell apart two models sharing one file
# (budget.csv's `kind` says whether a row is a Budget or a GoalAllocation).
# Not sourced from any single field, so a FieldMap has nowhere to declare it.
SYNTHETIC_COLUMNS = frozenset({"kind"})

# ---------------------------------------------------------------------------
# Cell codec
#
# Every kind decodes a blank cell the same way regardless of which column it
# is in -- "str" to "", everything else to None. Whether a given column is
# *allowed* to be blank on a given row is a business rule (which row kind,
# which other columns), not a fact about the cell's primitive type, so that
# check lives in read.py's row-shape validation, not here.
# ---------------------------------------------------------------------------

KIND_STR = "str"
KIND_STR_OR_NONE = "str_or_none"
KIND_INT = "int"
KIND_DECIMAL = "decimal"
KIND_DATE = "date"
KIND_DATETIME = "datetime"
KIND_BOOL = "bool"

_VALID_KINDS = frozenset({KIND_STR, KIND_STR_OR_NONE, KIND_INT, KIND_DECIMAL, KIND_DATE, KIND_DATETIME, KIND_BOOL})


class DocumentError(ValueError):
    """
    The archive could not be parsed, or does not describe a valid set of books.

    Every message on this exception is written to be shown to the user
    directly -- it names the file, the row and the column, the way
    `apps/bank_feed/services/csv_upload.py` and the YNAB importer's parser do.
    """


def _cell_location(file: str, row_number: int, column: str) -> str:
    return f"{file}, row {row_number}, column '{column}'"


def encode_cell(kind: str, value) -> str:
    """A Python value -> the text that goes in the CSV cell. Pure."""
    if value is None:
        return ""
    if kind in (KIND_STR, KIND_STR_OR_NONE):
        return str(value)
    if kind == KIND_INT:
        return str(int(value))
    if kind == KIND_DECIMAL:
        # Every exported DecimalField is `decimal_places=2` (verified against
        # every model in scope -- see the module docstring). Quantizing here
        # makes the output canonical regardless of how the caller's Decimal
        # was constructed, which is what makes the manifest's per-file sha256
        # (§3.1) and the round-trip test (§7 Phase 5) meaningful.
        return str(Decimal(value).quantize(Decimal("0.01")))
    if kind == KIND_DATE:
        return value.isoformat()
    if kind == KIND_DATETIME:
        # USE_TZ is True project-wide, so every archived_at is tz-aware.
        # Normalising to UTC before formatting means the file never depends on
        # the exporting server's local timezone, and `datetime.fromisoformat`
        # (Python 3.11+, this project's 3.12) reads the offset back exactly.
        return value.astimezone(UTC).isoformat()
    if kind == KIND_BOOL:
        return "true" if value else "false"
    raise ValueError(f"Unknown column kind: {kind!r}")  # pragma: no cover - schema bug, not user data


def decode_cell(kind: str, cell: str, *, file: str, row_number: int, column: str):
    """The text in a CSV cell -> a Python value, or raise DocumentError. Pure."""
    text = (cell or "").strip()
    where = _cell_location(file, row_number, column)

    if kind == KIND_STR:
        return text
    if not text:
        return None
    if kind == KIND_STR_OR_NONE:
        return text
    if kind == KIND_INT:
        try:
            return int(text)
        except ValueError:
            raise DocumentError(f"{where}: '{cell}' is not a whole number.") from None
    if kind == KIND_DECIMAL:
        try:
            return Decimal(text)
        except InvalidOperation:
            raise DocumentError(f"{where}: '{cell}' is not a valid amount.") from None
    if kind == KIND_DATE:
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise DocumentError(f"{where}: '{cell}' is not a valid date (expected YYYY-MM-DD).") from None
    if kind == KIND_DATETIME:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise DocumentError(f"{where}: '{cell}' is not a valid timestamp.") from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    if kind == KIND_BOOL:
        if text == "true":
            return True
        if text == "false":
            return False
        raise DocumentError(f"{where}: '{cell}' must be 'true' or 'false'.")
    raise ValueError(f"Unknown column kind: {kind!r}")  # pragma: no cover - schema bug, not user data


def blank_value(kind: str):
    """
    What a blank cell of this kind decodes back into.

    One rule in one place, so a row built from model instances and the same row
    read back out of a file agree on what "nothing here" looks like -- which is
    the identity the round-trip test asserts.
    """
    return "" if kind == KIND_STR else None


@dataclass(frozen=True)
class Column:
    name: str
    kind: str

    def __post_init__(self):
        if self.kind not in _VALID_KINDS:
            raise ValueError(f"Column {self.name!r} has an unknown kind {self.kind!r}")


_UNSET = object()


@dataclass(frozen=True)
class ColumnSpec:
    """
    Where one model field lands, and how to get it there and back.

    `name` and `kind` are the column and its codec. The other three exist so
    this declaration is the *only* place the mapping is written -- `export.py`
    reads a row through `build_row` and never names a field itself:

    `read`     how to get the value off a model instance, when plain attribute
               access by the field name this spec is keyed on will not do (an
               FK carried as its target's name, or as a bare id).
    `absent`   what the column holds when there is no instance at all -- no
               goal on this account, no feed row on this line. The default is
               the value the codec would decode a blank cell back into, so a
               row built here and a row read from a file agree: "" for a plain
               string column, None for everything else. Override it only where
               the file really should carry a value rather than a blank, as the
               feed's two booleans do.
    `writes`   False when another map owns the column and this spec exists only
               to account for the field. `BankTransaction.account` and
               `.journal_entry` are the cases: both are already carried, by the
               line's `account_id` and the entry's `entry_id`, and a second
               writer would overwrite them with the feed row's own values.
    """

    name: str
    kind: str
    read: object = None
    absent: object = _UNSET
    writes: bool = True

    def value_from(self, obj, field_name: str):
        """This column's value for `obj`, or its absent value when there is none."""
        if obj is None:
            return blank_value(self.kind) if self.absent is _UNSET else self.absent
        return self.read(obj) if self.read else getattr(obj, field_name)


@dataclass(frozen=True)
class FieldMap:
    """
    How one model's concrete fields become columns (or are deliberately left
    out of the format).

    `columns` maps the model's own field name to the `ColumnSpec` that carries
    it. Several fields legitimately share one column -- `JournalEntry.id` and
    `JournalLine.journal_entry` both resolve to `entry_id`, since a
    `JournalEntry` has no row of its own (§3.3) -- so this is many-to-one, not
    a bijection; `test_schema.py` only requires that every field maps
    somewhere, not that each column has exactly one source field.

    `omitted` names every other concrete field, each with the reason its data
    deliberately does not travel. An omission earns a place here the same way
    a decision earns a row in the plan's §5 -- it should be defensible on its
    own, not just "not gotten to yet".
    """

    model: type
    columns: dict = field(default_factory=dict)
    omitted: dict = field(default_factory=dict)


def build_row(*pairs, columns=None) -> dict:
    """
    `(field_map, instance), ...` -> `{column: value}`.

    The caller resolves each map's instance -- some are reached from the row's
    subject (an account's group), one is looked up entirely outside it (the
    feed row belonging to a line) -- and passing `None` for a map means "this
    row has no such object", which fills its columns with their absent values.

    Pass the file's `columns` and anything no map wrote is filled with that
    column's blank value, so a row is always the full width of its file. Two
    kinds of column rely on that: the ones no model field produces at all
    (`account_name`, informational; `kind`, telling two models apart in one
    file -- both of which the caller then sets), and the ones only *one* of a
    file's two models has (`notes` belongs to `GoalAllocation`, not `Budget`).
    """
    row: dict = {}
    for field_map, obj in pairs:
        for field_name, spec in field_map.columns.items():
            if spec.writes:
                row[spec.name] = spec.value_from(obj, field_name)
    for column in columns or ():
        row.setdefault(column.name, blank_value(column.kind))
    return row


def model_kwargs(field_map, row: dict, *, skip: set | None = None) -> dict:
    """
    `{model field name: value}` for constructing this map's model from a row --
    the reverse of `build_row`, off the same declaration.

    `skip` names the fields the caller supplies itself, which is always the
    same two kinds and no others: a foreign key, whose file value is a handle
    that has to be remapped to the destination's own id, and a primary key,
    which the destination assigns. Fields marked `writes=False` are already
    another map's to carry, so they are skipped without being asked for.

    Everything else arrives exactly as the file's codec decoded it. A field
    that needs normalising beyond that belongs in `skip` and in an explicit
    keyword at the call site, where the reason for it can be read.
    """
    skip = skip or set()
    return {
        field_name: row[spec.name]
        for field_name, spec in field_map.columns.items()
        if spec.writes and field_name not in skip
    }


_TENANT = "tenant identity, not part of the books (§2.5)"
_TIMESTAMP = "re-derived as import time, not carried (§2.6)"

# --- accounts.csv -----------------------------------------------------------
#
# One row per Account. AccountGroup, Institution and Goal are folded in as
# columns on that row rather than given files of their own (§2.1) -- each is
# either unique-by-name within the team (AccountGroup, Institution) or backed
# one-to-one by the account itself (Goal), so nothing about them needs its own
# handle.

ACCOUNT = FieldMap(
    model=Account,
    columns={
        "id": ColumnSpec("account_id", KIND_INT),
        "name": ColumnSpec("name", KIND_STR),
        "has_feed": ColumnSpec("has_feed", KIND_BOOL),
        "is_system": ColumnSpec("is_system", KIND_BOOL),
        "sort_order": ColumnSpec("sort_order", KIND_INT),
        "is_archived": ColumnSpec("is_archived", KIND_BOOL),
        "archived_at": ColumnSpec("archived_at", KIND_DATETIME),
    },
    omitted={
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "account_group": "denormalised onto this row via the ACCOUNT_GROUP field map, not carried as a raw id",
        "institution": "denormalised onto this row via the INSTITUTION field map, not carried as a raw id",
    },
)

ACCOUNT_GROUP = FieldMap(
    model=AccountGroup,
    columns={
        "name": ColumnSpec("group_name", KIND_STR),
        "account_type": ColumnSpec("account_type", KIND_STR),
        "description": ColumnSpec("group_description", KIND_STR),
        "is_system": ColumnSpec("group_is_system", KIND_BOOL),
        "sort_order": ColumnSpec("group_sort_order", KIND_INT),
        "is_archived": ColumnSpec("group_is_archived", KIND_BOOL),
        "archived_at": ColumnSpec("group_archived_at", KIND_DATETIME),
    },
    omitted={
        "id": "AccountGroup is unique per (team, name); no separate handle is needed (§2.2)",
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
    },
)

INSTITUTION = FieldMap(
    model=Institution,
    columns={
        "name": ColumnSpec("institution", KIND_STR_OR_NONE),
        "is_archived": ColumnSpec("institution_is_archived", KIND_BOOL),
        "archived_at": ColumnSpec("institution_archived_at", KIND_DATETIME),
    },
    omitted={
        "id": "Institution is unique per (team, name); no separate handle is needed (§2.2)",
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
    },
)

# Payee is the one name-only model whose archive flags are *not* carried --
# see the plan's §2.3 note on why Institution and Payee are handled
# differently (repetition cost: a payee's flag would repeat on every line
# that names it, an institution's on one row per account).
PAYEE = FieldMap(
    model=Payee,
    columns={
        # The entry is what reaches the payee, so `JournalEntry.payee` writes
        # this column; Payee is in the journal row's map set to account for its
        # own fields, not to write anything itself.
        "name": ColumnSpec("payee", KIND_STR_OR_NONE, writes=False),
    },
    omitted={
        "id": "Payee is unique per (team, name); no separate handle is needed (§2.2)",
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "is_archived": "not surfaced anywhere in the product; repeating it on every line naming this payee costs a "
        "consistency check for a fact nothing reads (§2.3)",
        "archived_at": "see is_archived, above",
    },
)

GOAL = FieldMap(
    model=Goal,
    columns={
        # "no goal at all" is told apart from "a goal with an empty
        # description" entirely by goal_name (Goal.name is never blank for a
        # real goal); goal_description mirrors group_description's kind for
        # the same reason -- Goal.description is `blank=True`, not
        # `null=True`, so a real goal's blank description decodes to "",
        # never None. Typing it STR_OR_NONE was the round-trip test's first
        # real catch while this module was being written.
        "name": ColumnSpec("goal_name", KIND_STR_OR_NONE),
        "description": ColumnSpec("goal_description", KIND_STR),
        "target_amount": ColumnSpec("goal_target_amount", KIND_DECIMAL),
        "target_date": ColumnSpec("goal_target_date", KIND_DATE),
        "is_complete": ColumnSpec("goal_is_complete", KIND_BOOL),
        "is_archived": ColumnSpec("goal_is_archived", KIND_BOOL),
        "archived_at": ColumnSpec("goal_archived_at", KIND_DATETIME),
        "order": ColumnSpec("goal_order", KIND_INT),
    },
    omitted={
        "id": "a goal has no handle of its own; it is identified by the account it backs (§2.1)",
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "account": "implicit -- a goal's columns live on its own backing account's row, by construction (§2.1)",
    },
)

ACCOUNTS_COLUMNS = (
    Column("account_id", KIND_INT),
    Column("name", KIND_STR),
    Column("account_type", KIND_STR),
    Column("group_name", KIND_STR),
    Column("group_description", KIND_STR),
    Column("group_is_system", KIND_BOOL),
    Column("group_sort_order", KIND_INT),
    Column("group_is_archived", KIND_BOOL),
    Column("group_archived_at", KIND_DATETIME),
    Column("institution", KIND_STR_OR_NONE),
    Column("institution_is_archived", KIND_BOOL),
    Column("institution_archived_at", KIND_DATETIME),
    Column("has_feed", KIND_BOOL),
    Column("is_system", KIND_BOOL),
    Column("sort_order", KIND_INT),
    Column("is_archived", KIND_BOOL),
    Column("archived_at", KIND_DATETIME),
    Column("goal_name", KIND_STR_OR_NONE),
    Column("goal_description", KIND_STR),
    Column("goal_target_amount", KIND_DECIMAL),
    Column("goal_target_date", KIND_DATE),
    Column("goal_is_complete", KIND_BOOL),
    Column("goal_is_archived", KIND_BOOL),
    Column("goal_archived_at", KIND_DATETIME),
    Column("goal_order", KIND_INT),
)

# --- journal.csv --------------------------------------------------------
#
# One row per JournalLine, entry columns repeated, plus one row per
# uncategorized bank-feed transaction (§2.4, §3.3). BankTransaction is folded
# in as `feed_*` columns on the line it belongs to, rather than a fourth file
# or an inferred fact -- see §2.4 for why inference over `JournalEntry.source`
# was tried and rejected.

JOURNAL_ENTRY = FieldMap(
    model=JournalEntry,
    columns={
        # Sourced from JournalLine.journal_entry_id when writing a line row (a
        # JournalEntry has no row of its own), but it is the same value as
        # this field, so it is mapped here rather than omitted.
        "id": ColumnSpec("entry_id", KIND_INT),
        "entry_date": ColumnSpec("entry_date", KIND_DATE),
        "payee": ColumnSpec("payee", KIND_STR_OR_NONE, read=lambda entry: entry.payee.name if entry.payee_id else None),
        "description": ColumnSpec("description", KIND_STR),
        "source": ColumnSpec("source", KIND_STR),
        "status": ColumnSpec("status", KIND_STR),
        "is_archived": ColumnSpec("entry_is_archived", KIND_BOOL),
        "archived_at": ColumnSpec("entry_archived_at", KIND_DATETIME),
    },
    omitted={
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
    },
)

JOURNAL_LINE = FieldMap(
    model=JournalLine,
    columns={
        "account": ColumnSpec("account_id", KIND_INT, read=lambda line: line.account_id),
        "dr_amount": ColumnSpec("dr_amount", KIND_DECIMAL),
        "cr_amount": ColumnSpec("cr_amount", KIND_DECIMAL),
        "is_cleared": ColumnSpec("is_cleared", KIND_BOOL),
        "is_reconciled": ColumnSpec("is_reconciled", KIND_BOOL),
        "is_archived": ColumnSpec("is_archived", KIND_BOOL),
        "archived_at": ColumnSpec("archived_at", KIND_DATETIME),
        # The statement that ticked or locked the line: a handle into
        # reconciliations.csv, remapped on import like account_id.
        "reconciliation": ColumnSpec("reconciliation_id", KIND_INT, read=lambda line: line.reconciliation_id),
    },
    omitted={
        "id": "no cross-reference needs a line handle; line order is preserved positionally (§2.6)",
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "journal_entry": "same value as JournalEntry.id, carried once as entry_id",
        "budget": "derived from (account, month) on import via bulk_create_for_import; carrying it risks "
        "staleness (§2.6)",
    },
)

BANK_TRANSACTION = FieldMap(
    model=BankTransaction,
    columns={
        # On a categorised row this is the line's own account; on an
        # uncategorized row it is this field directly. Either way it is the
        # row's `account_id` column.
        # Both of these are already carried -- `account_id` by the line this
        # feed row rides on, `entry_id` by that line's entry -- so they are
        # accounted for here but written by those maps (`writes=False`).
        "account": ColumnSpec("account_id", KIND_INT, writes=False),
        # Whether this is set is exactly what a blank `entry_id` records.
        "journal_entry": ColumnSpec("entry_id", KIND_INT, writes=False),
        "source": ColumnSpec("feed_source", KIND_STR_OR_NONE),
        "amount": ColumnSpec("feed_amount", KIND_DECIMAL),
        "posted_date": ColumnSpec("feed_posted_date", KIND_DATE),
        # STR, not STR_OR_NONE: `BankTransaction.description` is a plain
        # `CharField` -- NOT NULL, so "" is an ordinary value for it and None
        # is not one it can hold. A blank cell here therefore means "a feed
        # row whose description is empty", never "no feed row at all"; that
        # question is answered by `feed_source`, exactly as `goal_name`
        # answers it for goals above. Typing it STR_OR_NONE let a blank decode
        # to None, which read.py's completeness check then read as a *missing*
        # column -- so the exporter could produce an archive its own importer
        # refused. Reported from real books, not caught by a test.
        "description": ColumnSpec("feed_description", KIND_STR),
        # merchant_name IS nullable, so None stays the honest value here.
        "merchant_name": ColumnSpec("feed_merchant", KIND_STR_OR_NONE),
        # `absent=False`, not a blank: a line with no feed row is not a line
        # whose feed row has an unknown mirror/archived state, and the file
        # reads better saying so.
        "is_transfer_mirror": ColumnSpec("feed_is_mirror", KIND_BOOL, absent=False),
        "is_archived": ColumnSpec("feed_is_archived", KIND_BOOL, absent=False),
        "archived_at": ColumnSpec("feed_archived_at", KIND_DATETIME),
    },
    omitted={
        "id": "a feed row has no handle of its own; it is identified by the line it belongs to, or by being an "
        "uncategorized row (§2.4)",
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "raw": "the original bank payload is diagnostic only, not part of the books (§2.4)",
    },
)

JOURNAL_COLUMNS = (
    Column("entry_id", KIND_INT),
    Column("entry_date", KIND_DATE),
    Column("payee", KIND_STR_OR_NONE),
    Column("description", KIND_STR),
    Column("source", KIND_STR),
    Column("status", KIND_STR),
    Column("account_id", KIND_INT),
    Column("account_name", KIND_STR),
    Column("entry_is_archived", KIND_BOOL),
    Column("entry_archived_at", KIND_DATETIME),
    Column("dr_amount", KIND_DECIMAL),
    Column("cr_amount", KIND_DECIMAL),
    Column("is_cleared", KIND_BOOL),
    Column("is_reconciled", KIND_BOOL),
    Column("is_archived", KIND_BOOL),
    Column("archived_at", KIND_DATETIME),
    Column("reconciliation_id", KIND_INT),
    Column("feed_source", KIND_STR_OR_NONE),
    Column("feed_amount", KIND_DECIMAL),
    Column("feed_posted_date", KIND_DATE),
    Column("feed_description", KIND_STR),
    Column("feed_merchant", KIND_STR_OR_NONE),
    Column("feed_is_mirror", KIND_BOOL),
    Column("feed_is_archived", KIND_BOOL),
    Column("feed_archived_at", KIND_DATETIME),
)

# --- budget.csv ---------------------------------------------------------
#
# One row per monthly amount -- a Budget row or a GoalAllocation, told apart
# by `kind` (§2.1). A GoalAllocation's target is a Goal, identified the same
# way a Goal is everywhere else in this format: by the account_id of the
# equity account backing it.

BUDGET = FieldMap(
    model=Budget,
    columns={
        "month": ColumnSpec("month", KIND_DATE),
        "category": ColumnSpec("account_id", KIND_INT, read=lambda budget: budget.category_id),
        "budget_amount": ColumnSpec("amount", KIND_DECIMAL),
        "is_archived": ColumnSpec("is_archived", KIND_BOOL),
        "archived_at": ColumnSpec("archived_at", KIND_DATETIME),
    },
    omitted={
        "id": "no cross-reference needs a handle; a budget row is identified by (kind=budget, account_id, month), "
        "which is already unique (Budget.Meta.unique_together)",
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
    },
)

GOAL_ALLOCATION = FieldMap(
    model=GoalAllocation,
    columns={
        # Via allocation.goal.account_id -- a goal is identified by its
        # account everywhere in this format (§2.1), not by its own id.
        "goal": ColumnSpec("account_id", KIND_INT, read=lambda allocation: allocation.goal.account_id),
        "month": ColumnSpec("month", KIND_DATE),
        "amount": ColumnSpec("amount", KIND_DECIMAL),
        "notes": ColumnSpec("notes", KIND_STR),
        "is_archived": ColumnSpec("is_archived", KIND_BOOL),
        "archived_at": ColumnSpec("archived_at", KIND_DATETIME),
    },
    omitted={
        "id": "no cross-reference needs a handle; identified by (kind=goal, account_id, month), which is already "
        "unique (GoalAllocation.Meta.unique_together)",
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
    },
)

BUDGET_COLUMNS = (
    Column("kind", KIND_STR),
    Column("month", KIND_DATE),
    Column("account_id", KIND_INT),
    Column("account_name", KIND_STR),
    Column("amount", KIND_DECIMAL),
    Column("notes", KIND_STR),
    Column("is_archived", KIND_BOOL),
    Column("archived_at", KIND_DATETIME),
)

# --- reconciliations.csv -------------------------------------------------
#
# One row per statement (apps.reconciliation). Journal lines point back at a
# row by `reconciliation_id`; the amounts are in ledger sign (dr - cr), as the
# model stores them.

RECONCILIATION = FieldMap(
    model=Reconciliation,
    columns={
        "id": ColumnSpec("reconciliation_id", KIND_INT),
        "account": ColumnSpec("account_id", KIND_INT, read=lambda rec: rec.account_id),
        "statement_date": ColumnSpec("statement_date", KIND_DATE),
        "statement_balance": ColumnSpec("statement_balance", KIND_DECIMAL),
        "status": ColumnSpec("status", KIND_STR),
        "opening_balance": ColumnSpec("opening_balance", KIND_DECIMAL),
        "cleared_total": ColumnSpec("cleared_total", KIND_DECIMAL),
        "adjustment_amount": ColumnSpec("adjustment_amount", KIND_DECIMAL),
        "completed_at": ColumnSpec("completed_at", KIND_DATETIME),
        "undone_at": ColumnSpec("undone_at", KIND_DATETIME),
        "is_archived": ColumnSpec("is_archived", KIND_BOOL),
        "archived_at": ColumnSpec("archived_at", KIND_DATETIME),
    },
    omitted={
        "team": _TENANT,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "started_by": "a user of one instance is not a user of another; the books do not carry people",
        "completed_by": "a user of one instance is not a user of another; the books do not carry people",
    },
)

RECONCILIATIONS_COLUMNS = (
    Column("reconciliation_id", KIND_INT),
    Column("account_id", KIND_INT),
    Column("statement_date", KIND_DATE),
    Column("statement_balance", KIND_DECIMAL),
    Column("status", KIND_STR),
    Column("opening_balance", KIND_DECIMAL),
    Column("cleared_total", KIND_DECIMAL),
    Column("adjustment_amount", KIND_DECIMAL),
    Column("completed_at", KIND_DATETIME),
    Column("undone_at", KIND_DATETIME),
    Column("is_archived", KIND_BOOL),
    Column("archived_at", KIND_DATETIME),
)

# Every model this format exports, and the field maps that describe it. Used
# by the completeness test; iteration order does not matter.
FIELD_MAPS = (
    ACCOUNT,
    ACCOUNT_GROUP,
    INSTITUTION,
    PAYEE,
    GOAL,
    JOURNAL_ENTRY,
    JOURNAL_LINE,
    BANK_TRANSACTION,
    BUDGET,
    GOAL_ALLOCATION,
    RECONCILIATION,
)

#: Which field maps compose one row, per file. `export.py` builds rows against
#: exactly these groupings, and `test_schema.py` checks each one covers its
#: file's columns without two maps writing the same one -- the invariant
#: `build_row` depends on, since a second writer silently overwrites the first.
#:
#: A file with more than one grouping writes *alternative* row kinds rather
#: than a blend: budget.csv holds a `Budget` row or a `GoalAllocation` row, and
#: its `kind` column is what says which.
ROW_COMPOSITIONS = {
    ACCOUNTS_FILE: ((ACCOUNT, ACCOUNT_GROUP, INSTITUTION, GOAL),),
    JOURNAL_FILE: ((JOURNAL_ENTRY, JOURNAL_LINE, PAYEE, BANK_TRANSACTION),),
    BUDGET_FILE: (
        (BUDGET,),
        (GOAL_ALLOCATION,),
    ),
    RECONCILIATIONS_FILE: ((RECONCILIATION,),),
}

FILE_COLUMNS = {
    ACCOUNTS_FILE: ACCOUNTS_COLUMNS,
    JOURNAL_FILE: JOURNAL_COLUMNS,
    BUDGET_FILE: BUDGET_COLUMNS,
    RECONCILIATIONS_FILE: RECONCILIATIONS_COLUMNS,
}


def validate_schema() -> None:
    """
    Internal consistency of this module -- not of any archive. Every column
    named in `FILE_COLUMNS` must be produced by some `FieldMap`, or be a known
    informational column with no field behind it; nothing in `FILE_COLUMNS`
    may be silently orphaned from the maps that are supposed to explain it.

    Called from `PortabilityConfig.ready()` so a broken schema fails at
    startup, and from `test_schema.py` so it fails a test in CI without a
    server having to start. `apps/onboarding/questions.py::validate_catalog()`
    is the precedent for this pattern.
    """
    mapped_column_names = {spec.name for fm in FIELD_MAPS for spec in fm.columns.values()}
    accounted_for = mapped_column_names | INFORMATIONAL_COLUMNS | SYNTHETIC_COLUMNS
    for file, columns in FILE_COLUMNS.items():
        for column in columns:
            if column.name not in accounted_for:
                raise AssertionError(
                    f"{file}: column '{column.name}' is not produced by any FieldMap, and is not in "
                    "INFORMATIONAL_COLUMNS or SYNTHETIC_COLUMNS. Either map the field that should produce "
                    "it, or add it to one of those sets with a comment saying why it has none."
                )
