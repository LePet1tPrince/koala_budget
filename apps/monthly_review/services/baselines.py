"""
The comparison-window machinery for the guided monthly review.

Pure arithmetic over an already-assembled monthly matrix -- no database access,
so this is fully unit-testable without a team, ledger, or fixtures. `review.py`
does the querying and hands this module one dict; this module slices it five
ways (or fewer, if the team's history is short) and never looks at the database
itself.

Non-negotiable rules (see docs/monthly-review-plan.md §3):
- A baseline never includes the month under review.
- A baseline is clamped to the team's first month of activity -- never averaged
  over months that predate any data.
- 1m is literally last month, not an average of one thing pretending to be one.
- A team with zero prior months gets no baselines at all.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.utils.formats import date_format

METRICS = ("income", "spend", "net", "saved")

# The "all time" baseline: every month from the team's first activity up to the
# month before the one under review.
ALL_TIME = "all"

BASELINE_META = {
    1: {"id": "1m", "label": "Last month", "short": "1-mo", "against": "last month"},
    3: {"id": "3m", "label": "3-month average", "short": "3-mo", "against": "the 3-month average"},
    6: {"id": "6m", "label": "6-month average", "short": "6-mo", "against": "the 6-month average"},
    12: {"id": "12m", "label": "12-month average", "short": "12-mo", "against": "the 12-month average"},
    ALL_TIME: {"id": "all", "label": "All-time average", "short": "All time", "against": "the all-time average"},
}

DEFAULT_BASELINE_MONTHS = (1, 3, 6, 12, ALL_TIME)
DEFAULT_BASELINE_ID = "3m"


@dataclass
class MonthlyMatrix:
    """
    Per-month figures for one team, spanning the reviewed month and however
    many months of history precede it (up to 12).

    All month-keyed dicts use `date` objects normalized to the first of the
    month. A month with no activity is expected to be present with zero
    values, not absent -- `first_month` is what tells baselines.py where the
    team's real history starts.
    """

    months: list  # ascending, oldest first, including the reviewed month
    income: dict
    spend: dict
    net: dict
    saved: dict
    savings_rate: dict
    categories: dict = field(default_factory=dict)  # id -> {"by_month": {date: Decimal}, ...extra}
    streams: dict = field(default_factory=dict)  # key -> {"label": str, "by_month": {date: Decimal}}
    goals: dict = field(default_factory=dict)  # id -> {"goal": obj, "by_month": {date: Decimal}}
    first_month: date | None = None


def _prev_month(month: date) -> date:
    if month.month == 1:
        return date(month.year - 1, 12, 1)
    return date(month.year, month.month - 1, 1)


def _month_span_label(window: list) -> str:
    if not window:
        return ""
    if len(window) == 1:
        return date_format(window[0], "M Y")
    return f"{date_format(window[0], 'M')} – {date_format(window[-1], 'M Y')}"


def clamp_window(month: date, months, first_month: date | None) -> list:
    """
    Up to `months` calendar months strictly before `month`, oldest first,
    never reaching earlier than `first_month`. `months=ALL_TIME` means no limit.

    Returns [] when there is no room at all -- either no history exists, or
    the month under review is the team's first month (or earlier).
    """
    if first_month is None:
        return []
    window = []
    cursor = _prev_month(month)
    while months == ALL_TIME or len(window) < months:
        if cursor < first_month:
            break
        window.append(cursor)
        cursor = _prev_month(cursor)
    window.reverse()
    return window


def _avg(by_month: dict, window: list):
    if not window:
        return Decimal("0")
    total = sum((by_month.get(d, Decimal("0")) for d in window), Decimal("0"))
    return total / len(window)


def _avg_float(by_month: dict, window: list) -> float:
    if not window:
        return 0.0
    values = [float(by_month.get(d, 0.0)) for d in window]
    return sum(values) / len(values)


def _stream_rows(streams: dict, window: list, month: date) -> list:
    rows = []
    for entry in streams.values():
        by_month = entry["by_month"]
        current = by_month.get(month, Decimal("0"))
        avg = _avg(by_month, window)
        if not current and not avg:
            continue
        had_history = any(by_month.get(d, Decimal("0")) for d in window)
        rows.append(
            {
                "payee": entry["label"],
                "amount": current,
                "avg": avg,
                "vs_avg": current - avg,
                "new": bool(current) and not had_history,
            }
        )
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows


def _goal_rows(goals: dict, window: list, month: date) -> list:
    prev_month = _prev_month(month)
    rows = []
    for entry in goals.values():
        by_month = entry["by_month"]
        rows.append(
            {
                "goal": entry["goal"],
                "amount": by_month.get(month, Decimal("0")),
                "prev": by_month.get(prev_month, Decimal("0")),
                "avg": _avg(by_month, window),
                "vs_avg": by_month.get(month, Decimal("0")) - _avg(by_month, window),
            }
        )
    return rows


def build_baselines(matrix: MonthlyMatrix, month: date, baseline_months=DEFAULT_BASELINE_MONTHS):
    """
    Slice `matrix` into the requested baseline windows.

    Returns (baselines: dict, baseline_order: list[str], default_baseline: str | None).
    A window that would be empty (no qualifying months) is left out of the
    result entirely, per the "zero prior months" rule.
    """
    baselines = {}
    order = []

    for months in baseline_months:
        meta = BASELINE_META[months]
        window = clamp_window(month, months, matrix.first_month)
        if not window:
            continue

        avgs = {metric: _avg(getattr(matrix, metric), window) for metric in METRICS}
        avgs["savings_rate"] = _avg_float(matrix.savings_rate, window)

        baselines[meta["id"]] = {
            "id": meta["id"],
            "label": meta["label"],
            "short": meta["short"],
            "against": meta["against"],
            "span": _month_span_label(window),
            "months": len(window),
            "clamped": months != ALL_TIME and len(window) < months,
            "keys": [d.isoformat() for d in window],
            "avgs": avgs,
            "streams": _stream_rows(matrix.streams, window, month),
            "cat_avg": {cat_id: _avg(cat["by_month"], window) for cat_id, cat in matrix.categories.items()},
            "saving_rows": _goal_rows(matrix.goals, window, month),
        }
        order.append(meta["id"])

    default = DEFAULT_BASELINE_ID if DEFAULT_BASELINE_ID in baselines else (order[0] if order else None)
    return baselines, order, default
