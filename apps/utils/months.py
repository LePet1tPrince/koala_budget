"""
Calendar-month arithmetic.

Budgets, reports and the monthly review all work in whole months keyed by the
first of the month. These are the one copy of that arithmetic; `relativedelta`
does the same for a date that is already a first, but these also normalise a
date anywhere in its month.
"""

import re
from datetime import date

MONTH_RE = re.compile(r"([0-9]{4})-([0-9]{2})")


def add_months(day: date, n: int) -> date:
    """The first of the month `n` months after `day`'s month (`n` may be negative)."""
    year, month = divmod(day.year * 12 + day.month - 1 + n, 12)
    return date(year, month + 1, 1)


def months_between(start: date, end: date) -> int:
    """Whole months from `start`'s month to `end`'s month: 0 for the same month, negative if `end` is earlier."""
    return (end.year - start.year) * 12 + end.month - start.month


def parse_month(value: str | None) -> date | None:
    """
    The first of the month a `YYYY-MM` string names, or None if it names none.

    Strict on purpose: this is the API's month format, so `2026-3`, `2026-03-01`
    and `2026-13` are all None rather than guessed at.
    """
    match = MONTH_RE.fullmatch(value or "")
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12 or year < 1:
        return None
    return date(year, month, 1)


def format_month(day: date) -> str:
    """`day`'s month as `YYYY-MM`, the inverse of `parse_month`."""
    return f"{day.year:04d}-{day.month:02d}"
