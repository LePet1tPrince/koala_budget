"""
The multi-month budget grid: one row per category, one column per month.

`grid_data` builds what the grid editor shows; the budget API
(`apps.budget.api`) serializes it, and validates a batch of edits before
`ledger.set_budgets` writes them, all or nothing.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from django.utils.translation import gettext_lazy as _

from apps.utils.months import months_between

from . import ledger as budget_ledger
from .figures import budgeted_categories
from .forms import MAX_BUDGET_AMOUNT
from .services import BudgetService

GRID_MAX_MONTHS = 24
GRID_DEFAULT_MONTHS = 12
GRID_MAX_AMOUNT = MAX_BUDGET_AMOUNT
GRID_MAX_CHANGES = 10000

# Reference figures shown beside the grid's month columns. Each mode is a window of
# whole months measured from today (not from the grid's range), so planning next
# year reads against this year's and last year's real spending.
GRID_ACTUAL_MODES = ("avg_this_year", "avg_last_year", "last_month")
CENTS = Decimal("0.01")


def default_grid_start(today=None):
    """January of the current year, so the grid lines up with a Jan–Dec spreadsheet."""
    return (today or date.today()).replace(month=1, day=1)


def _grid_actual_windows(today):
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
    """Per-category actuals for every mode in `GRID_ACTUAL_MODES`.

    Returns `(modes, actuals)`: `modes` is `[{key, label, detail}]` for the picker,
    `actuals` is `{category_id: {mode: Decimal | None}}` — None only when the mode's
    window holds no complete month. Averages divide by every month in the window, so
    a month with no spending counts as $0. One query covers all three windows."""
    windows = _grid_actual_windows(today)
    firsts = [w[0] for w in windows.values() if w[0]]
    lasts = [w[1] for w in windows.values() if w[1]]
    by_month = BudgetService(book).get_all_actuals_by_month_category(min(firsts), max(lasts))

    actuals = {}
    for category in categories:
        row = {}
        for mode in GRID_ACTUAL_MODES:
            first, last = windows[mode][0], windows[mode][1]
            if first is None:
                row[mode] = None
                continue
            months = months_between(first, last) + 1
            total = sum(
                (by_month.get((first + relativedelta(months=i), category.pk), Decimal("0")) for i in range(months)),
                Decimal("0"),
            )
            row[mode] = (total / months).quantize(CENTS, rounding=ROUND_HALF_UP)
        actuals[category.pk] = row

    modes = [{"key": mode, "label": windows[mode][2], "detail": windows[mode][3]} for mode in GRID_ACTUAL_MODES]
    return modes, actuals


def grid_data(book, start, num_months, today=None):
    """What the grid editor shows for `num_months` months from `start`.

    `{start, num_months, prev_start, next_start, months: [date], actual_modes,
    groups: [{name, type, rows: [{id, name, amounts: {date: Decimal}, actuals}]}]}`.
    A month budgeted at zero has no budget line, so it has no amount (a blank cell).
    Hidden categories stay off the grid as they stay collapsed on the month page.
    """
    start = start.replace(day=1)
    months = [start + relativedelta(months=i) for i in range(num_months)]
    categories = list(budgeted_categories(book).filter(hidden_from_budget=False))
    actual_modes, actuals = grid_actuals(book, categories, today or date.today())

    amounts = {}
    for (month, category_id), amount in budget_ledger.budgeted_by_month_category(book, months[0], months[-1]).items():
        amounts.setdefault(category_id, {})[month] = amount

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

    return {
        "start": start,
        "num_months": num_months,
        "prev_start": start - relativedelta(months=num_months),
        "next_start": start + relativedelta(months=num_months),
        "months": months,
        "actual_modes": actual_modes,
        "groups": groups,
    }
