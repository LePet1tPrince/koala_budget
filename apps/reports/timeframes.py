"""
The range a report opens on: the book's `report_timeframe` setting, turned into dates.

Every report with a date or month range reads its default through `default_range`,
so the setting reaches all of them and a report that adds a range gets it for free.
"""

import contextlib
from datetime import date, datetime, timedelta

from apps.books.models import ReportTimeframe
from apps.utils.months import add_months


def timeframe_range(timeframe, today=None):
    """
    `(start, end)` for a `ReportTimeframe`, or None for `REPORT` (and anything unknown).

    "This month"/"This year" run to today; "Last N months" are the N full months
    before this one.
    """
    today = today or date.today()
    this_month = today.replace(day=1)
    last_month_end = this_month - timedelta(days=1)
    full_months = {
        ReportTimeframe.LAST_MONTH: 1,
        ReportTimeframe.LAST_3_MONTHS: 3,
        ReportTimeframe.LAST_6_MONTHS: 6,
        ReportTimeframe.LAST_12_MONTHS: 12,
    }
    if timeframe in full_months:
        return add_months(today, -full_months[timeframe]), last_month_end
    if timeframe == ReportTimeframe.THIS_MONTH:
        return this_month, today
    if timeframe == ReportTimeframe.THIS_YEAR:
        return date(today.year, 1, 1), today
    if timeframe == ReportTimeframe.LAST_YEAR:
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return None


def default_range(book, fallback):
    """The book's default report range, or the report's own `fallback` when the book defers to it."""
    return timeframe_range(book.report_timeframe) or fallback


def _parse_day(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_range_from_request(request, fallback):
    """
    `?start_date`/`?end_date` (yyyy-mm-dd) when both are given and parse, else the
    book's default range. `fallback` is the report's own default.
    """
    with contextlib.suppress(KeyError, ValueError):
        return _parse_day(request.GET["start_date"]), _parse_day(request.GET["end_date"])
    return default_range(request.book, fallback)


def month_range_from_request(request, fallback):
    """
    `?start_month`/`?end_month` (yyyy-mm) as whole months when both are given and
    parse, else the book's default range. `fallback` is the report's own default.
    """
    with contextlib.suppress(KeyError, ValueError):
        start_year, start_month = map(int, request.GET["start_month"].split("-"))
        end_year, end_month = map(int, request.GET["end_month"].split("-"))
        start = date(start_year, start_month, 1)
        end = add_months(date(end_year, end_month, 1), 1) - timedelta(days=1)
        return start, end
    return default_range(request.book, fallback)
