"""
Recurring manual transactions: the schedule arithmetic and writing what is due.

A `RecurringTransaction` holds a template and a schedule. `materialize` writes
every occurrence due by today as an ordinary manual feed row (through
`create_manual_transaction`, the same path the Add Transaction modal takes) and
moves `next_date` on. It runs from the nightly task, when the bank feed page
opens, and right after a schedule is created -- so a schedule started in the
past catches up at once. Each pass locks the schedule row and re-reads
`next_date` under the lock, so overlapping runs never write an occurrence twice.

Schedule semantics (see the model's docstring): occurrences are counted from
`start_date`'s day / week / month / year, and only dates strictly after
`start_date` are occurrences -- the start date is the transaction the user
entered by hand.
"""

import calendar
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.dateformat import format as format_date
from django.utils.dates import WEEKDAYS
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.guards import SystemCategoryError, assert_category_allowed
from apps.books.context import current_book

from ..models import RecurringTransaction
from .manual import create_manual_transaction
from .splits import SplitError, check_legs_total, parse_legs

logger = logging.getLogger(__name__)

#: Occurrences one pass writes for one schedule. A daily schedule started a year
#: back is 365; anything left over is written by the next pass.
MAX_PER_PASS = 400


def _month_date(year: int, month: int, day: int) -> date:
    """`day` of the month, `-1` for its last day; a day the month lacks falls on its last day."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, last if day == RecurringTransaction.LAST_DAY_OF_MONTH else min(day, last))


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def _occurrence(rule, k: int) -> date:
    """The k-th date of the schedule's grid (k >= 0); the caller drops those on or before the start."""
    start, n = rule.start_date, rule.interval
    if rule.frequency == RecurringTransaction.FREQUENCY_DAILY:
        return start + timedelta(days=k * n)
    if rule.frequency == RecurringTransaction.FREQUENCY_WEEKLY:
        week_start = start - timedelta(days=start.weekday())
        return week_start + timedelta(weeks=k * n, days=rule.weekday)
    if rule.frequency == RecurringTransaction.FREQUENCY_MONTHLY:
        year, month = _add_months(start.year, start.month, k * n)
        return _month_date(year, month, rule.day_of_month)
    if rule.frequency == RecurringTransaction.FREQUENCY_YEARLY:
        return _month_date(start.year + k * n, start.month, start.day)
    raise ValueError(f"Unknown frequency {rule.frequency!r}")


def _first_k(rule, after: date) -> int:
    """A grid index at or before the first occurrence after `after`, so `following` loops a step or two."""
    start, n = rule.start_date, rule.interval
    if after <= start:
        return 0
    if rule.frequency == RecurringTransaction.FREQUENCY_DAILY:
        return (after - start).days // n
    if rule.frequency == RecurringTransaction.FREQUENCY_WEEKLY:
        return (after - start).days // (7 * n)
    if rule.frequency == RecurringTransaction.FREQUENCY_MONTHLY:
        return max(0, ((after.year - start.year) * 12 + after.month - start.month) // n - 1)
    return max(0, (after.year - start.year) // n - 1)


def following(rule, after: date) -> date | None:
    """The first occurrence strictly after `after` (and after the start), or None past `end_date`."""
    floor = max(after, rule.start_date)
    k = _first_k(rule, floor)
    candidate = _occurrence(rule, k)
    while candidate <= floor:
        k += 1
        candidate = _occurrence(rule, k)
    if rule.end_date is not None and candidate > rule.end_date:
        return None
    return candidate


def describe(rule) -> str:
    """The schedule in words: "Every 2 weeks on Wednesday", "Every month on day 17"."""
    n = rule.interval
    if rule.frequency == RecurringTransaction.FREQUENCY_DAILY:
        return ngettext("Every day", "Every %(n)d days", n) % {"n": n}
    if rule.frequency == RecurringTransaction.FREQUENCY_WEEKLY:
        every = ngettext("Every week", "Every %(n)d weeks", n) % {"n": n}
        return _("%(every)s on %(weekday)s") % {"every": every, "weekday": WEEKDAYS[rule.weekday]}
    if rule.frequency == RecurringTransaction.FREQUENCY_MONTHLY:
        every = ngettext("Every month", "Every %(n)d months", n) % {"n": n}
        if rule.day_of_month == RecurringTransaction.LAST_DAY_OF_MONTH:
            return _("%(every)s on the last day") % {"every": every}
        return _("%(every)s on day %(day)d") % {"every": every, "day": rule.day_of_month}
    every = ngettext("Every year", "Every %(n)d years", n) % {"n": n}
    return _("%(every)s on %(date)s") % {"every": every, "date": format_date(rule.start_date, "F j")}


def _serialize_legs(legs):
    return [{"category": account.id, "amount": str(amount)} for account, amount in legs]


def create_rule(
    *,
    book,
    account,
    amount: Decimal,
    payee_name: str,
    description: str,
    category,
    legs,
    start_date: date,
    frequency: str,
    interval: int = 1,
    weekday: int | None = None,
    day_of_month: int | None = None,
    end_date: date | None = None,
) -> RecurringTransaction:
    """
    Save a schedule whose first transaction (on `start_date`) the caller writes itself.

    Only the field its frequency reads is kept; a weekly or monthly schedule with
    none given repeats on `start_date`'s weekday or day of the month.
    """
    if frequency == RecurringTransaction.FREQUENCY_WEEKLY:
        weekday = start_date.weekday() if weekday is None else weekday
    else:
        weekday = None
    if frequency == RecurringTransaction.FREQUENCY_MONTHLY:
        day_of_month = start_date.day if day_of_month is None else day_of_month
    else:
        day_of_month = None

    rule = RecurringTransaction(
        book=book,
        account=account,
        amount=amount,
        payee_name=payee_name,
        description=description,
        category=category,
        splits=_serialize_legs(legs) if legs is not None else None,
        frequency=frequency,
        interval=interval,
        weekday=weekday,
        day_of_month=day_of_month,
        start_date=start_date,
        end_date=end_date,
    )
    rule.next_date = following(rule, start_date)
    rule.save()
    return rule


def _template_legs(rule):
    """
    The legs each occurrence is written with, or None for an uncategorized row.

    Re-checked every time: a category deleted or turned into a budget bucket
    since the schedule was made leaves the occurrence uncategorized for the user
    to fix, rather than stopping the schedule or writing a refused category.
    Must run with `rule.book` current (`parse_legs` reads the book-scoped manager).
    """
    if rule.splits:
        try:
            legs = parse_legs(rule.splits)
            check_legs_total(legs, total=rule.amount)
            return legs
        except SplitError:
            logger.warning("Recurring transaction %s: split no longer valid; writing it uncategorized", rule.pk)
            return None
    category = rule.category
    if category is None or category.book_id != rule.book_id:
        return None
    try:
        assert_category_allowed(category)
    except SystemCategoryError:
        return None
    return [(category, rule.amount)]


def materialize(rule, today: date | None = None, limit: int = MAX_PER_PASS) -> int:
    """Write every occurrence of `rule` due by `today`. Returns how many were written."""
    today = today or timezone.localdate()
    written = 0
    with current_book(rule.book), transaction.atomic():
        locked = (
            RecurringTransaction.objects.select_for_update(of=("self",))
            .select_related("book", "account", "category")
            .filter(pk=rule.pk)
            .first()
        )
        if locked is None:
            return 0
        legs = _template_legs(locked)
        while locked.next_date is not None and locked.next_date <= today and written < limit:
            create_manual_transaction(
                book=locked.book,
                account=locked.account,
                date=locked.next_date,
                amount=locked.amount,
                payee_name=locked.payee_name,
                description=locked.description,
                legs=legs,
                recurring=locked,
            )
            written += 1
            locked.next_date = following(locked, locked.next_date)
        if written:
            locked.save(update_fields=["next_date", "updated_at"])
    rule.next_date = locked.next_date
    return written


def materialize_due(today: date | None = None, book=None) -> int:
    """Write what is due for every schedule (in `book`, when given). One failing schedule never stops the rest."""
    today = today or timezone.localdate()
    due = RecurringTransaction.objects.filter(next_date__lte=today)
    if book is not None:
        due = due.filter(book=book)
    total = 0
    for rule in due.select_related("book"):
        try:
            total += materialize(rule, today=today)
        except Exception:
            logger.exception("Recurring transaction %s failed to materialize", rule.pk)
    return total
