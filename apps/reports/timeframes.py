"""
The range a report opens on: the dates in its address, else the report's own default.
"""

import contextlib
from datetime import date, datetime, timedelta

from apps.utils.months import add_months


def _parse_day(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_range_from_request(request, fallback):
    """
    `?start_date`/`?end_date` (yyyy-mm-dd) when both are given and parse, else
    `fallback`, the report's own default.
    """
    with contextlib.suppress(KeyError, ValueError):
        return _parse_day(request.GET["start_date"]), _parse_day(request.GET["end_date"])
    return fallback


def month_range_from_request(request, fallback):
    """
    `?start_month`/`?end_month` (yyyy-mm) as whole months when both are given and
    parse, else `fallback`, the report's own default.
    """
    with contextlib.suppress(KeyError, ValueError):
        start_year, start_month = map(int, request.GET["start_month"].split("-"))
        end_year, end_month = map(int, request.GET["end_month"].split("-"))
        start = date(start_year, start_month, 1)
        end = add_months(date(end_year, end_month, 1), 1) - timedelta(days=1)
        return start, end
    return fallback
