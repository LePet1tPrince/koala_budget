"""
Selectors for budgeting app - handles all read operations and complex queries.
Business logic for fetching data should go here.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum

from .models import Account, Budget, Transaction


def get_income_expense_report(team, start_date: date, end_date: date) -> dict:
    """
    Generate income/expense report for a date range.

    Args:
        team: The team to generate report for
        start_date: Start date for the report
        end_date: End date for the report

    Returns:
        Dictionary with income, expenses, and net totals
    """
    transactions = Transaction.for_team.filter(date__gte=start_date, date__lte=end_date).select_related("category")

    # Get income transactions
    income = (
        transactions.filter(category__account_type="income")
        .values("category__name", "category__account_number")
        .annotate(total=Sum("amount"))
        .order_by("category__account_number")
    )

    # Get expense transactions
    expenses = (
        transactions.filter(category__account_type="expense")
        .values("category__name", "category__account_number")
        .annotate(total=Sum("amount"))
        .order_by("category__account_number")
    )

    total_income = sum(item["total"] for item in income) if income else Decimal("0")
    total_expenses = sum(item["total"] for item in expenses) if expenses else Decimal("0")

    return {
        "income": list(income),
        "expenses": list(expenses),
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net": total_income - total_expenses,
        "start_date": start_date,
        "end_date": end_date,
    }


def get_balance_sheet(team) -> dict:
    """
    Generate balance sheet from current account balances.

    Args:
        team: The team to generate balance sheet for

    Returns:
        Dictionary with assets, liabilities, and net worth
    """
    accounts = Account.for_team.all()

    assets = accounts.filter(account_type="asset").values("name", "account_number", "balance").order_by("account_number")

    liabilities = (
        accounts.filter(account_type="liability").values("name", "account_number", "balance").order_by("account_number")
    )

    equity = accounts.filter(Q(account_type="equity") | Q(account_type="opening_balance_equity")).values(
        "name", "account_number", "balance"
    ).order_by("account_number")

    total_assets = sum(a["balance"] for a in assets) if assets else Decimal("0")
    total_liabilities = sum(l["balance"] for l in liabilities) if liabilities else Decimal("0")
    total_equity = sum(e["balance"] for e in equity) if equity else Decimal("0")

    return {
        "assets": list(assets),
        "liabilities": list(liabilities),
        "equity": list(equity),
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "net_worth": total_assets - total_liabilities,
    }


def get_budget_performance(team, month: date) -> dict:
    """
    Get budget vs actual performance for a given month.

    Args:
        team: The team to get budget performance for
        month: The month (should be first day of month)

    Returns:
        Dictionary with budget performance data
    """
    budgets = Budget.for_team.filter(month=month).select_related("category").order_by("category__account_number")

    budget_list = []
    total_budgeted = Decimal("0")
    total_actual = Decimal("0")
    total_available = Decimal("0")

    for budget in budgets:
        budget_list.append(
            {
                "id": budget.id,
                "category_name": budget.category.name,
                "category_type": budget.category.account_type,
                "budgeted_amount": budget.budgeted_amount,
                "actual_amount": budget.actual_amount,
                "available_amount": budget.available_amount,
            }
        )
        total_budgeted += budget.budgeted_amount
        total_actual += budget.actual_amount
        total_available += budget.available_amount

    return {
        "month": month,
        "budgets": budget_list,
        "total_budgeted": total_budgeted,
        "total_actual": total_actual,
        "total_available": total_available,
    }


def get_accounts_by_type(team, account_type: str):
    """
    Get all accounts of a specific type.

    Args:
        team: The team to get accounts for
        account_type: Type of account (asset, liability, income, expense, equity)

    Returns:
        QuerySet of accounts
    """
    return Account.for_team.filter(account_type=account_type).order_by("account_number")


def get_transactions_for_month(team, month: date):
    """
    Get all transactions for a specific month.

    Args:
        team: The team to get transactions for
        month: The month (should be first day of month)

    Returns:
        QuerySet of transactions
    """
    # Calculate month boundaries
    year = month.year
    month_num = month.month

    if month_num == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_num + 1, 1)

    return (
        Transaction.for_team.filter(date__gte=month, date__lt=next_month)
        .select_related("payee", "account", "category")
        .order_by("-date", "-created_at")
    )
