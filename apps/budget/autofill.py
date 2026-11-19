"""
Auto-Assign: set a whole tab's budgets for a month in one go.

Shared by the no-JS form post (`views.budget_autofill_view`) and the budget API
(`apps.budget.api`). Writes go through `ledger.set_budgets`, the one budget write path.
"""

from decimal import Decimal

from dateutil.relativedelta import relativedelta

from apps.accounts.models import ACCOUNT_TYPE_INCOME, Account

from . import ledger as budget_ledger
from .figures import (
    AUTOFILL_ASSIGN_ZERO,
    AUTOFILL_ASSIGNED_LAST_MONTH,
    AUTOFILL_RESET_AVAILABLE_ZERO,
    AUTOFILL_SPENT_LAST_MONTH,
)
from .services import BudgetService, budgeted_account_types


def autofill_categories(book, section=None, category_ids=None):
    """
    The categories an Auto-Assign action reaches: one tab's (`section`, a type the
    book budgets; anything else means every budgeted type), never a hidden one (a
    bulk fill is aimed at what is on screen), and -- when `category_ids` is not None
    -- only those ids. An empty `category_ids` is an explicit empty selection.
    """
    types = budgeted_account_types(book)
    if section in types:
        types = (section,)
    categories = list(
        Account.objects.filter(book=book, account_group__account_type__in=types, hidden_from_budget=False)
        .select_related("account_group")
        .order_by("account_group__name", "name")
    )
    if category_ids is not None:
        selected = {int(pk) for pk in category_ids}
        categories = [category for category in categories if category.pk in selected]
    return categories


def autofill_amounts(book, month, action, categories) -> dict:
    """`{category_id: amount}` that `action` sets for `month` (the first of a month)."""
    prev_month = month - relativedelta(months=1)
    service = BudgetService(book)

    if action == AUTOFILL_ASSIGNED_LAST_MONTH:
        prev_budgets = budget_ledger.budgeted_in_month(book, prev_month)
        return {cat.pk: prev_budgets.get(cat.pk, Decimal("0")) for cat in categories}

    if action == AUTOFILL_SPENT_LAST_MONTH:
        prev_actuals = service.get_actuals_by_category(prev_month)
        return {cat.pk: max(prev_actuals.get(cat.pk, Decimal("0")), Decimal("0")) for cat in categories}

    if action == AUTOFILL_ASSIGN_ZERO:
        return {cat.pk: Decimal("0") for cat in categories}

    if action == AUTOFILL_RESET_AVAILABLE_ZERO:
        prev_available = service.get_available_by_category(prev_month, categories)
        current_actuals = service.get_actuals_by_category(month)
        amounts = {}
        for cat in categories:
            actual = current_actuals.get(cat.pk, Decimal("0"))
            prev_avail = prev_available.get(cat.pk, Decimal("0"))
            if cat.account_group.account_type == ACCOUNT_TYPE_INCOME:
                # Available = Actual - Budget + prev_avail = 0, so Budget = Actual + prev_avail
                amounts[cat.pk] = actual + prev_avail
            else:
                # Available = Budget - Actual + prev_avail = 0, so Budget = Actual - prev_avail
                amounts[cat.pk] = actual - prev_avail
        return amounts

    return {}


def apply_autofill(book, month, action, section=None, category_ids=None) -> int:
    """Run `action` for `month` over the categories it reaches; the number of budgets set."""
    month = month.replace(day=1)
    amounts = autofill_amounts(book, month, action, autofill_categories(book, section, category_ids))
    budget_ledger.set_budgets(book, {(category_id, month): amount for category_id, amount in amounts.items()})
    return len(amounts)
