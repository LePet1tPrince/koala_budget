"""
Reading a YNAB export.

Two CSVs -- a Register (every transaction) and a Plan (every category in every
month) -- both UTF-8 with a BOM on the header row and amounts written with a
*trailing* currency symbol (`134.32$`, `-0.00$`).

Pure: this module reads bytes and returns dataclasses. It touches no database and
makes no decisions about what any of it means -- that is `analyse.py`.
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import BinaryIO

from apps.bank_feed.services.csv_upload import detect_encoding, parse_amount

ZERO = Decimal("0")

TRANSFER_PREFIX = "Transfer : "
STARTING_BALANCE_PAYEE = "Starting Balance"

SPLIT_MEMO = re.compile(r"^Split \((\d+)/(\d+)\)\s*")

REGISTER_COLUMNS = ("Account", "Date", "Payee", "Category Group", "Category", "Memo", "Outflow", "Inflow")
PLAN_COLUMNS = ("Month", "Category Group", "Category", "Assigned", "Activity", "Available")

# YNAB writes dates in the locale the budget was created in. Day-first is the
# non-US default and the separator usually settles it, but an export from a US
# budget is month-first, so the format is detected per file rather than assumed.
DATE_FORMATS = ("%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d.%m.%Y", "%m.%d.%Y")

# Which component of a candidate format is the day, so a value like `25-01-2024`
# can prove the ordering rather than leaving it to a coin toss.
DAY_POSITION = {"%d-%m-%Y": 0, "%m/%d/%Y": 1, "%d/%m/%Y": 0, "%Y-%m-%d": 2, "%m-%d-%Y": 1, "%d.%m.%Y": 0, "%m.%d.%Y": 1}


class ParseError(ValueError):
    """Something the user needs told about. The message is user-facing."""


@dataclass(frozen=True)
class RegisterRow:
    """One line of the Register, with the derivations every later pass needs."""

    index: int
    account: str
    entry_date: date
    payee: str
    category_group: str
    category: str
    memo: str
    net: Decimal
    cleared: str

    @property
    def month(self) -> date:
        return self.entry_date.replace(day=1)

    @property
    def transfer_account(self) -> str | None:
        """The other side of a transfer, or None for an ordinary row."""
        if self.payee.startswith(TRANSFER_PREFIX):
            return self.payee[len(TRANSFER_PREFIX) :].strip()
        return None

    @property
    def is_starting_balance(self) -> bool:
        return self.payee == STARTING_BALANCE_PAYEE

    @property
    def split(self) -> tuple[int, int] | None:
        """`(leg, of)` for a split leg -- YNAB writes `Split (1/3)` into the memo."""
        match = SPLIT_MEMO.match(self.memo)
        return (int(match.group(1)), int(match.group(2))) if match else None

    @property
    def clean_memo(self) -> str:
        """The memo without YNAB's `Split (i/n)` prefix, which is structure, not a note."""
        return SPLIT_MEMO.sub("", self.memo).strip()

    @property
    def is_reconciled(self) -> bool:
        return self.cleared == "Reconciled"

    @property
    def is_cleared(self) -> bool:
        # Reconciled implies cleared: YNAB cannot reconcile an uncleared transaction.
        return self.cleared in ("Reconciled", "Cleared")


@dataclass(frozen=True)
class PlanRow:
    """One category in one month."""

    month: date
    category_group: str
    category: str
    assigned: Decimal
    activity: Decimal
    available: Decimal

    @property
    def key(self) -> tuple[str, str]:
        return (self.category_group, self.category)


def _rows(content: bytes) -> list[dict]:
    text = content.decode(detect_encoding(content), errors="replace").lstrip("﻿")
    return list(csv.DictReader(io.StringIO(text)))


def _headers(content: bytes) -> set[str]:
    text = content.decode(detect_encoding(content), errors="replace").lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    return set(next(reader, []))


def looks_like_register(content: bytes) -> bool:
    return set(REGISTER_COLUMNS) <= _headers(content)


def looks_like_plan(content: bytes) -> bool:
    return set(PLAN_COLUMNS) <= _headers(content)


def identify(files: list[tuple[str, bytes]]) -> tuple[bytes, bytes]:
    """
    Work out which upload is the Register and which is the Plan, from their headers.

    The user drops two files; asking them to label which is which is a question the
    files already answer. Filenames are not consulted -- YNAB names them after the
    budget, and a renamed file should still import.
    """
    register = next((content for _, content in files if looks_like_register(content)), None)
    plan = next((content for _, content in files if looks_like_plan(content)), None)

    if register is None:
        raise ParseError("No register file found. Export both CSVs from YNAB and upload them together.")
    if plan is None:
        raise ParseError("No plan file found. Export both CSVs from YNAB and upload them together.")
    if register is plan:
        raise ParseError("Those two files look the same. Upload the Register and the Plan.")

    return register, plan


def detect_date_format(values: list[str]) -> str:
    """
    The format that reads every date in the file.

    `05-01-2024` is January 5th or May 1st depending on the budget's locale, and
    the file never says which. A value whose first component is above 12 settles
    it; when nothing in the file does, day-first wins, because that is what every
    YNAB export outside the US carries.
    """
    candidates = []
    for fmt in DATE_FORMATS:
        if all(_try_date(value, fmt) is not None for value in values if value.strip()):
            candidates.append(fmt)

    if not candidates:
        raise ParseError("Could not read the dates in that file. Is it a YNAB export?")
    if len(candidates) == 1:
        return candidates[0]

    # Prefer a format the data itself proves: a day above 12 cannot be a month.
    for fmt in candidates:
        position = DAY_POSITION[fmt]
        if any(_component_above_12(value, position) for value in values if value.strip()):
            return fmt

    return candidates[0]


def _try_date(value: str, fmt: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), fmt).date()
    except ValueError:
        return None


def _component_above_12(value: str, position: int) -> bool:
    parts = re.split(r"[-/.]", value.strip())
    if position >= len(parts):
        return False
    return parts[position].isdigit() and int(parts[position]) > 12


def _amount(value: str) -> Decimal:
    """
    A blank cell is zero, not a failure.

    `parse_amount` strips the currency symbol wherever it sits, so YNAB's trailing
    form (`134.32$`) parses without a YNAB-specific reader.
    """
    parsed = parse_amount(value or "")
    return parsed if parsed is not None else ZERO


def parse_register(content: bytes) -> list[RegisterRow]:
    raw = _rows(content)
    if not raw:
        raise ParseError("The register file has no rows.")
    _require(raw[0], REGISTER_COLUMNS, "register")

    fmt = detect_date_format([row.get("Date") or "" for row in raw])

    rows = []
    for index, row in enumerate(raw):
        entry_date = _try_date(row.get("Date") or "", fmt)
        if entry_date is None:
            raise ParseError(f"Row {index + 2} of the register has a date we cannot read: {row.get('Date')!r}.")
        rows.append(
            RegisterRow(
                index=index,
                account=(row.get("Account") or "").strip(),
                entry_date=entry_date,
                payee=(row.get("Payee") or "").strip(),
                category_group=(row.get("Category Group") or "").strip(),
                category=(row.get("Category") or "").strip(),
                memo=(row.get("Memo") or "").strip(),
                net=_amount(row.get("Inflow")) - _amount(row.get("Outflow")),
                cleared=(row.get("Cleared") or "").strip(),
            )
        )
    return rows


def parse_plan(content: bytes) -> list[PlanRow]:
    raw = _rows(content)
    if not raw:
        raise ParseError("The plan file has no rows.")
    _require(raw[0], PLAN_COLUMNS, "plan")

    rows = []
    for index, row in enumerate(raw):
        month = _parse_month(row.get("Month") or "")
        if month is None:
            raise ParseError(f"Row {index + 2} of the plan has a month we cannot read: {row.get('Month')!r}.")
        rows.append(
            PlanRow(
                month=month,
                category_group=(row.get("Category Group") or "").strip(),
                category=(row.get("Category") or "").strip(),
                assigned=_amount(row.get("Assigned")),
                activity=_amount(row.get("Activity")),
                available=_amount(row.get("Available")),
            )
        )
    return rows


MONTH_FORMATS = ("%b %Y", "%B %Y", "%Y-%m", "%b, %Y")


def _parse_month(value: str) -> date | None:
    value = value.strip()
    for fmt in MONTH_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().replace(day=1)
        except ValueError:
            continue
    return None


def _require(row: dict, columns: tuple[str, ...], what: str):
    missing = [column for column in columns if column not in row]
    if missing:
        raise ParseError(f"The {what} file is missing the column(s): {', '.join(missing)}.")


def read_upload(upload: BinaryIO) -> bytes:
    """Read an uploaded file whole. Both exports are small enough to hold in memory."""
    upload.seek(0)
    return upload.read()
