"""
The multi-month budget grid: one row per category, one column per month.

`grid_groups` builds the rows the React grid renders -- amounts from the budget
entries and, beside them, a column of real actuals to plan against.
`parse_changes` validates what a save posts, all or nothing, so the view only
has to write the result (`ledger.set_budgets`).
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

from apps.utils.amounts import CENT, json_amount
from apps.utils.months import months_between

from . import ledger as budget_ledger
from .figures import budget_categories
from .forms import MAX_BUDGET_AMOUNT
from .services import BudgetService


class GridError(ValueError):
    """A grid save refused as a whole; the message is what the page shows."""


MAX_MONTHS = 24
DEFAULT_MONTHS = 12
#: More changes than one save may carry.
MAX_CHANGES = 10000


# Reference figures shown beside the grid's month columns. Each mode is a window of
# whole months measured from today (not from the grid's range), so planning next
# year reads against this year's and last year's real spending.
ACTUAL_MODES = ("avg_this_year", "avg_last_year", "last_month")


def actual_windows(today):
    """`{mode: (first_month, last_month, label, detail)}` for each actuals mode, or a
    `None` window when the mode has no complete month yet (January's "this year").

    Only complete months count: the running month would drag an average down."""
    this_month = today.replace(day=1)
    last_month = this_month - relativedelta(months=1)
    year_start = this_month.replace(month=1)
    last_year_start = year_start.replace(year=year_start.year - 1)
    last_year_end = year_start - relativedelta(months=1)

    def span(first, last):
        if first == last:
            return first.strftime("%b %Y")
        return f"{first.strftime('%b')}–{last.strftime('%b %Y')}"

    this_year = (year_start, last_month) if last_month >= year_start else None
    return {
        "avg_this_year": (
            *(this_year or (None, None)),
            _("Average this year"),
            _("Monthly average, %(span)s") % {"span": span(*this_year)} if this_year else _("No complete month yet"),
        ),
        "avg_last_year": (
            last_year_start,
            last_year_end,
            _("Average last year"),
            _("Monthly average, %(span)s") % {"span": span(last_year_start, last_year_end)},
        ),
        "last_month": (last_month, last_month, _("Last month"), last_month.strftime("%b %Y")),
    }


def grid_actuals(book, categories, today):
    """Per-category actuals for every mode in `ACTUAL_MODES`.

    Returns `(modes, actuals)`: `modes` is `[{key, label, detail}]` for the picker,
    `actuals` is `{category_id: {mode: "123.45" | None}}` — None only when the mode's
    window holds no complete month. Averages divide by every month in the window, so
    a month with no spending counts as $0. One query covers all three windows."""
    windows = actual_windows(today)
    firsts = [w[0] for w in windows.values() if w[0]]
    lasts = [w[1] for w in windows.values() if w[1]]
    by_month = BudgetService(book).get_all_actuals_by_month_category(min(firsts), max(lasts))

    actuals = {}
    for category in categories:
        row = {}
        for mode in ACTUAL_MODES:
            first, last = windows[mode][0], windows[mode][1]
            if first is None:
                row[mode] = None
                continue
            months = months_between(first, last) + 1
            total = sum(
                (by_month.get((first + relativedelta(months=i), category.pk), Decimal("0")) for i in range(months)),
                Decimal("0"),
            )
            row[mode] = str((total / months).quantize(CENT, rounding=ROUND_HALF_UP))
        actuals[category.pk] = row

    modes = [{"key": mode, "label": str(windows[mode][2]), "detail": str(windows[mode][3])} for mode in ACTUAL_MODES]
    return modes, actuals


def grid_months(start, num_months):
    """The grid's month columns: `num_months` (clamped to 1..`MAX_MONTHS`) firsts from `start`."""
    num_months = max(1, min(num_months, MAX_MONTHS))
    return [start + relativedelta(months=i) for i in range(num_months)]


def grid_groups(book, months, today=None):
    """
    The grid's rows, grouped by account group: `(groups, actual_modes)`.

    `groups` is `[{name, type, rows: [{id, name, amounts, actuals}]}]` in
    budget-table order; `amounts` maps a month's ISO date to its budget, from the
    budget entries -- a month budgeted at zero has no line, so it shows blank.
    Hidden categories stay off the grid as they stay collapsed on the month page.
    """
    categories = list(budget_categories(book).filter(hidden_from_budget=False))
    actual_modes, actuals = grid_actuals(book, categories, today or date.today())

    amounts = {}
    for (month, category_id), amount in budget_ledger.budgeted_by_month_category(book, months[0], months[-1]).items():
        amounts.setdefault(category_id, {})[month.isoformat()] = str(amount)

    groups = []
    for category in categories:
        group_name = category.account_group.name
        if not groups or groups[-1]["name"] != group_name:
            groups.append({"name": group_name, "type": category.account_group.account_type, "rows": []})
        groups[-1]["rows"].append(
            {
                "id": category.pk,
                "name": category.name,
                "amounts": amounts.get(category.pk, {}),
                "actuals": actuals[category.pk],
            }
        )
    return groups, actual_modes


def parse_changes(book, changes):
    """
    A grid save's `changes` (`[{category_id, month, amount}]`) as
    `{(category_id, first of month): Decimal}`, ready for `ledger.set_budgets`.

    All or nothing: any malformed change, unknown category, bad month or bad
    amount raises `GridError` for the whole batch. Last write wins if the same
    cell appears twice.
    """
    if not isinstance(changes, list):
        raise GridError("Invalid request body.")
    if len(changes) > MAX_CHANGES:
        raise GridError("Too many changes in one request.")

    category_ids = {c.get("category_id") for c in changes if isinstance(c, dict)}
    valid_category_ids = set(budget_categories(book).filter(pk__in=category_ids).values_list("pk", flat=True))

    merged = {}
    for change in changes:
        if not isinstance(change, dict):
            raise GridError("Invalid request body.")

        category_id = change.get("category_id")
        if category_id not in valid_category_ids:
            raise GridError("Unknown budget category.")

        month = parse_date(str(change.get("month") or ""))
        if month is None:
            raise GridError("Invalid month.")

        amount = json_amount(change.get("amount"), limit=MAX_BUDGET_AMOUNT)
        if amount is None:
            raise GridError("Invalid amount.")

        merged[(category_id, month.replace(day=1))] = amount
    return merged
