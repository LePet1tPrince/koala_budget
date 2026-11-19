"""
Every figure the budget page shows for one month, built in one place.

`month_figures` is the single builder: the budget page template renders it
(`views._budget_swap_context` adds the row forms), and the budget API
(`apps.budget.api`) serializes it for the page's script and for any other client.
A figure therefore cannot read one way on the page and another way in the API.

The structure, for a month:

* `sections` -- one per tab, in tab order (`budget_tab_keys`): income first when
  the book budgets income, then expenses. Each carries its totals, its sidebar
  summary, its overspent count, its Auto-Assign actions and its `groups`;
* a section's `groups` -- consecutive runs of one account group, in board order,
  then the collapsed "Hidden" group (`hidden: True`) last when any category of the
  section is hidden;
* a group's `rows` -- one per category: budgeted, actual, available and the meter.

Hidden categories are a display choice, not an accounting one: their figures keep
counting in every total, the sidebar and Unassigned.
"""

from decimal import Decimal

from django.db.models import Case, IntegerField, Value, When
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account

from . import ledger as budget_ledger
from .services import BudgetService, GoalService, NetWorthService, budgeted_account_types
from .unassigned import compute_unassigned

FIGURE_FIELDS = ("budgeted", "actual", "available")

AUTOFILL_ASSIGNED_LAST_MONTH = "assigned_last_month"
AUTOFILL_SPENT_LAST_MONTH = "spent_last_month"
AUTOFILL_ASSIGN_ZERO = "assign_zero"
AUTOFILL_RESET_AVAILABLE_ZERO = "reset_available_zero"
AUTOFILL_ACTIONS = (
    AUTOFILL_ASSIGNED_LAST_MONTH,
    AUTOFILL_SPENT_LAST_MONTH,
    AUTOFILL_ASSIGN_ZERO,
    AUTOFILL_RESET_AVAILABLE_ZERO,
)


def budgeted_categories(book):
    """The categories a book budgets (see `budgeted_account_types`), in budget-table
    display order: income sections first, then expenses, each in board order."""
    return (
        Account.objects.filter(book=book, account_group__account_type__in=budgeted_account_types(book))
        .select_related("account_group")
        .annotate(
            type_order=Case(
                When(account_group__account_type=ACCOUNT_TYPE_INCOME, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("type_order", "account_group__sort_order", "account_group__name", "sort_order", "name")
    )


def budget_tab_keys(book):
    """The budget page's tabs, in order: a section per category type the book budgets."""
    return ["income", "expense"] if ACCOUNT_TYPE_INCOME in budgeted_account_types(book) else ["expense"]


def autofill_actions(section_key):
    """A tab's Auto-Assign buttons: `[{action, label, css}]` (`css` is the page's)."""
    return [
        {"action": AUTOFILL_ASSIGNED_LAST_MONTH, "label": _("Assigned Last Month"), "css": "btn-soft btn-primary"},
        {
            "action": AUTOFILL_SPENT_LAST_MONTH,
            "label": _("Received Last Month") if section_key == "income" else _("Spent Last Month"),
            "css": "btn-soft btn-secondary",
        },
        {"action": AUTOFILL_ASSIGN_ZERO, "label": _("Assign Zero"), "css": "btn-soft"},
        {"action": AUTOFILL_RESET_AVAILABLE_ZERO, "label": _("Reset Available to Zero"), "css": "btn-soft"},
    ]


def meter(account_type, budgeted, actual, available):
    """The progress bar beside a budget row.

    Expense: spent against what there was to spend this month -- the budget plus
    whatever rolled in (the previous Available, which is `available − budgeted +
    actual`), so a full bar and a zero Available are the same thing. Red once
    Available is negative. Income: received against expected.
    """
    if account_type == ACCOUNT_TYPE_INCOME:
        whole = budgeted
        over = False
    else:
        rolled_in = available - budgeted + actual
        whole = budgeted + max(rolled_in, Decimal("0"))
        over = available < 0
    pct = float(actual / whole * 100) if whole > 0 else None
    # No budget to measure against: a full bar if anything was spent, else empty.
    width = (100 if actual > 0 else 0) if pct is None else max(min(round(pct), 100), 0)
    return {
        "pct": pct,
        "width": width,
        "over": over,
        "income": account_type == ACCOUNT_TYPE_INCOME,
        "label": f"{round(pct)}%" if pct is not None else "—",
    }


def _zero_totals():
    return {field: Decimal("0") for field in FIGURE_FIELDS}


def _group(name, hidden=False):
    return {"name": name, "hidden": hidden, "rows": [], "subtotals": _zero_totals(), "overspent": 0}


def cover_goals(book, month):
    """Goals an overspent category can be covered from (an emergency fund, ...), with what each has left."""
    return [
        {"id": goal.pk, "name": goal.name, "left": goal.left}
        for goal in GoalService(book).get_goals_with_progress(month)
    ]


def month_figures(book, month):
    """Every number the budget page shows for `month` (the first of a month).

    Returns `{month, categories, sections, has_categories, grand_totals,
    sidebar_summary, unassigned, net_worth_card, cover_goals}`; see the module
    docstring for the shape of `sections`. Rows carry the category instance
    (`row["category"]`) for the template.
    """
    month = month.replace(day=1)
    service = BudgetService(book)
    categories = list(budgeted_categories(book))

    budgeted_map = budget_ledger.budgeted_in_month(book, month)
    actuals_map = service.get_actuals_by_category(month)
    # This month's balances and last month's (what rolled in) from one walk of
    # the budget history.
    available_map, prev_available_map = service.get_available_with_previous(month, categories)

    # Income section first, then expenses; groups within a section keep the
    # category ordering (board sort order, then group/account name).
    sections = {
        key: {
            "key": key,
            "label": _("Income") if key == "income" else _("Expenses"),
            "income": key == "income",
            "groups": [],
            "totals": _zero_totals(),
            "hidden_count": 0,
        }
        for key in ("income", "expense")
    }

    # A hidden category leaves its account group for a collapsed "Hidden" group at
    # the end of its section.
    hidden_groups = {}

    for category in categories:
        budgeted = budgeted_map.get(category.pk, Decimal("0"))
        actual = actuals_map.get(category.pk, Decimal("0"))
        available = available_map.get(category.pk, Decimal("0"))

        section_key = "income" if category.account_group.account_type == ACCOUNT_TYPE_INCOME else "expense"
        section = sections[section_key]
        if category.hidden_from_budget:
            group = hidden_groups.setdefault(section_key, _group(_("Hidden"), hidden=True))
        else:
            group_name = category.account_group.name
            if not section["groups"] or section["groups"][-1]["name"] != group_name:
                section["groups"].append(_group(group_name))
            group = section["groups"][-1]

        group["rows"].append(
            {
                "category": category,
                "budgeted": budgeted,
                "actual": actual,
                "available": available,
                "meter": meter(category.account_group.account_type, budgeted, actual, available),
            }
        )
        if available < 0:
            group["overspent"] += 1

        for field, amount in (("budgeted", budgeted), ("actual", actual), ("available", available)):
            group["subtotals"][field] += amount
            section["totals"][field] += amount

    for section_key, group in hidden_groups.items():
        sections[section_key]["groups"].append(group)
        sections[section_key]["hidden_count"] = len(group["rows"])

    # One tab per section the book budgets (no Income tab with future income off).
    section_list = [sections[key] for key in budget_tab_keys(book)]

    grand_totals = {
        field: sum((section["totals"][field] for section in section_list), Decimal("0")) for field in FIGURE_FIELDS
    }

    # The sidebar summarises the tab on screen, so each section carries its own. A
    # section's key is its categories' account type.
    type_of = {category.pk: category.account_group.account_type for category in categories}
    sidebar_summary = {}
    for section in section_list:
        key = section["key"]
        rows = [row for group in section["groups"] for row in group["rows"]]
        section["overspent"] = sum(1 for row in rows if row["available"] < 0) if key == ACCOUNT_TYPE_EXPENSE else 0
        section["autofill"] = autofill_actions(key)
        section["summary"] = sidebar_summary[key] = {
            "leftover_last_month": sum(
                (amount for pk, amount in prev_available_map.items() if type_of.get(pk) == key), Decimal("0")
            ),
            "assigned_this_month": section["totals"]["budgeted"],
            "activity_this_month": section["totals"]["actual"],
            "available": section["totals"]["available"],
        }

    unassigned = compute_unassigned(book, month, categories)
    return {
        "month": month,
        "categories": categories,
        "sections": section_list,
        "has_categories": bool(categories),
        "grand_totals": grand_totals,
        "sidebar_summary": sidebar_summary,
        "unassigned": unassigned,
        "net_worth_card": NetWorthService.card_data(unassigned),
        "cover_goals": cover_goals(book, month),
    }
