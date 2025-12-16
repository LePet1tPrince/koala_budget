"""
Services for budgeting app - handles all write operations and business logic.
Business logic for creating, updating, and deleting data should go here.
"""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import Account, Budget, Transaction


def update_account_balance(account_id: int) -> None:
    """
    Recalculate and update account balance from all transactions.

    Args:
        account_id: ID of the account to update
    """
    account = Account.objects.get(id=account_id)

    # Sum transactions where this is the account (debits)
    account_total = Transaction.objects.filter(account=account).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # Sum transactions where this is the category (credits)
    category_total = Transaction.objects.filter(category=account).aggregate(total=Sum("amount"))["total"] or Decimal(
        "0"
    )

    # Balance = debits - credits
    account.balance = account_total - category_total
    account.save(update_fields=["balance"])


def update_budget_actuals(budget_id: int) -> None:
    """
    Update budget actual_amount and available_amount from transactions.

    Args:
        budget_id: ID of the budget to update
    """
    budget = Budget.objects.select_related("category").get(id=budget_id)

    # Calculate month boundaries
    month_start = budget.month
    year = month_start.year
    month_num = month_start.month

    month_end = date(year + 1, 1, 1) if month_num == 12 else date(year, month_num + 1, 1)

    # Get all transactions for this category in this month
    actual = Transaction.objects.filter(category=budget.category, date__gte=month_start, date__lt=month_end).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    budget.actual_amount = actual
    budget.available_amount = budget.budgeted_amount - actual
    budget.save(update_fields=["actual_amount", "available_amount"])


def update_all_budgets_for_month(team, month: date) -> None:
    """
    Update all budgets for a given month.

    Args:
        team: The team
        month: The month to update budgets for
    """
    budgets = Budget.objects.filter(team=team, month=month)
    for budget in budgets:
        update_budget_actuals(budget.id)


@transaction.atomic
def create_transaction(team, data: dict) -> Transaction:
    """
    Create transaction and update related balances/budgets.

    Args:
        team: The team the transaction belongs to
        data: Dictionary with transaction data

    Returns:
        Created transaction instance
    """
    trans = Transaction.objects.create(team=team, **data)

    # Update account balances
    update_account_balance(trans.account_id)
    update_account_balance(trans.category_id)

    # Update budget if exists for this category and month
    month_start = trans.date.replace(day=1)
    try:
        budget = Budget.objects.get(team=team, month=month_start, category=trans.category)
        update_budget_actuals(budget.id)
    except Budget.DoesNotExist:
        pass

    return trans


@transaction.atomic
def update_transaction(transaction_id: int, data: dict) -> Transaction:
    """
    Update transaction and recalculate balances/budgets.

    Args:
        transaction_id: ID of transaction to update
        data: Dictionary with updated transaction data

    Returns:
        Updated transaction instance
    """
    trans = Transaction.objects.get(id=transaction_id)

    # Store old values for cleanup
    old_account_id = trans.account_id
    old_category_id = trans.category_id
    old_month = trans.date.replace(day=1)
    old_category = trans.category
    team = trans.team

    # Update transaction
    for key, value in data.items():
        setattr(trans, key, value)
    trans.save()

    # Update balances for all affected accounts
    affected_accounts = {old_account_id, old_category_id, trans.account_id, trans.category_id}
    for account_id in affected_accounts:
        update_account_balance(account_id)

    # Update budgets for affected months/categories
    new_month = trans.date.replace(day=1)
    affected_budgets = []

    # Old month/category combination
    try:
        budget = Budget.objects.get(team=team, month=old_month, category=old_category)
        affected_budgets.append(budget.id)
    except Budget.DoesNotExist:
        pass

    # New month/category combination (if different)
    if new_month != old_month or trans.category_id != old_category_id:
        try:
            budget = Budget.objects.get(team=team, month=new_month, category=trans.category)
            affected_budgets.append(budget.id)
        except Budget.DoesNotExist:
            pass

    for budget_id in affected_budgets:
        update_budget_actuals(budget_id)

    return trans


@transaction.atomic
def delete_transaction(transaction_id: int) -> None:
    """
    Delete transaction and update balances/budgets.

    Args:
        transaction_id: ID of transaction to delete
    """
    trans = Transaction.objects.get(id=transaction_id)
    account_id = trans.account_id
    category_id = trans.category_id
    month = trans.date.replace(day=1)
    category = trans.category
    team = trans.team

    trans.delete()

    # Update balances
    update_account_balance(account_id)
    update_account_balance(category_id)

    # Update budget if exists
    try:
        budget = Budget.objects.get(team=team, month=month, category=category)
        update_budget_actuals(budget.id)
    except Budget.DoesNotExist:
        pass


def create_budget(team, data: dict) -> Budget:
    """
    Create budget with calculated fields.

    Args:
        team: The team the budget belongs to
        data: Dictionary with budget data

    Returns:
        Created budget instance
    """
    budget = Budget.objects.create(team=team, **data)

    # Calculate actuals
    update_budget_actuals(budget.id)

    return budget


def update_budget(budget_id: int, data: dict) -> Budget:
    """
    Update budget and recalculate fields.

    Args:
        budget_id: ID of budget to update
        data: Dictionary with updated budget data

    Returns:
        Updated budget instance
    """
    budget = Budget.objects.get(id=budget_id)

    for key, value in data.items():
        setattr(budget, key, value)
    budget.save()

    # Recalculate actuals in case month or category changed
    update_budget_actuals(budget.id)

    return budget


def bulk_create_budgets(team, month: date, budget_data: list) -> list:
    """
    Create multiple budgets for a month at once.

    Args:
        team: The team
        month: The month for budgets
        budget_data: List of dictionaries with budget data

    Returns:
        List of created budget instances
    """
    budgets = []
    for data in budget_data:
        budget = Budget(team=team, month=month, **data)
        budgets.append(budget)

    Budget.objects.bulk_create(budgets)

    # Update actuals for all created budgets
    created_budgets = Budget.objects.filter(team=team, month=month)
    for budget in created_budgets:
        update_budget_actuals(budget.id)

    return list(created_budgets)
