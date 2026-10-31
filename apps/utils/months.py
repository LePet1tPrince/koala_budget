"""
Calendar-month arithmetic.

Budgets, reports and the monthly review all work in whole months keyed by the
first of the month. These are the one copy of that arithmetic; `relativedelta`
does the same for a date that is already a first, but these also normalise a
date anywhere in its month.
"""

from datetime import date


def add_months(day: date, n: int) -> date:
    """The first of the month `n` months after `day`'s month (`n` may be negative)."""
    year, month = divmod(day.year * 12 + day.month - 1 + n, 12)
    return date(year, month + 1, 1)


def months_between(start: date, end: date) -> int:
    """Whole months from `start`'s month to `end`'s month: 0 for the same month, negative if `end` is earlier."""
    return (end.year - start.year) * 12 + end.month - start.month
