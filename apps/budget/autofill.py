"""
Auto-Assign: the budget sidebar's one-click fills for a month.

Each action sets the month's budget for a set of categories from something the
book already knows -- last month's budget, last month's activity, zero, or
whatever makes every Available land on zero -- and writes them in one go
through `ledger.set_budgets`.
"""

from decimal import Decimal

from dateutil.relativedelta import relativedelta

from apps.accounts.models import Account

from . import ledger as budget_ledger
from .services import BudgetService, budgeted_account_types

ASSIGNED_LAST_MONTH = "assigned_last_month"
SPENT_LAST_MONTH = "spent_last_month"
ASSIGN_ZERO = "assign_zero"
RESET_AVAILABLE_ZERO = "reset_available_zero"
ACTIONS = (ASSIGNED_LAST_MONTH, SPENT_LAST_MONTH, ASSIGN_ZERO, RESET_AVAILABLE_ZERO)


def autofill_categories(book, section=None, selected_ids=None):
    """
    The categories a fill applies to, in a stable order.

    One tab's categories when `section` names a type the book budgets: each tab
    carries its own Auto-Assign buttons, and a fill must not reach rows on a tab
    that isn't on screen. Otherwise every budgeted type. Hidden categories are
    left alone -- a bulk fill is aimed at what is on screen. `selected_ids` (the
    row checkboxes, as strings) narrows it further; None means no selection was
    made, as on the no-JS form, so everything applies.
    """
    types = budgeted_account_types(book)
    if section in types:
        types = (section,)
    categories = list(
        Account.objects.filter(book=book, account_group__account_type__in=types, hidden_from_budget=False)
        .select_related("account_group")
        .order_by("account_group__name", "name")
    )
    if selected_ids is not None:
        categories = [category for category in categories if str(category.pk) in selected_ids]
    return categories


def autofill(book, action, month, categories):
    """
    Apply `action` (one of `ACTIONS`) to `categories` for `month` and write it.
    Answers `{category_id: amount}` as written; an unknown action writes nothing.
    """
    prev_month = month - relativedelta(months=1)
    service = BudgetService(book)

    amounts = {}
    if action == ASSIGNED_LAST_MONTH:
        prev_budgets = budget_ledger.budgeted_in_month(book, prev_month)
        amounts = {cat.pk: prev_budgets.get(cat.pk, Decimal("0")) for cat in categories}

    elif action == SPENT_LAST_MONTH:
        prev_actuals = service.get_actuals_by_category(prev_month)
        amounts = {cat.pk: max(prev_actuals.get(cat.pk, Decimal("0")), Decimal("0")) for cat in categories}

    elif action == ASSIGN_ZERO:
        amounts = {cat.pk: Decimal("0") for cat in categories}

    elif action == RESET_AVAILABLE_ZERO:
        prev_available = service.get_available_by_category(prev_month, categories)
        current_actuals = service.get_actuals_by_category(month)
        for cat in categories:
            actual = current_actuals.get(cat.pk, Decimal("0"))
            prev_avail = prev_available.get(cat.pk, Decimal("0"))
            if cat.account_group.account_type == "income":
                # Available = Actual - Budget + prev_avail = 0, so Budget = Actual + prev_avail
                amounts[cat.pk] = actual + prev_avail
            else:
                # Available = Budget - Actual + prev_avail = 0, so Budget = Actual - prev_avail
                amounts[cat.pk] = actual - prev_avail

    budget_ledger.set_budgets(book, {(category_id, month): amount for category_id, amount in amounts.items()})
    return amounts
