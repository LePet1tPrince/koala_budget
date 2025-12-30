from django.db import transaction
from apps.accounts.models import AccountGroup, Account, Payee
from apps.budget.models import Budget
from apps.journal.models import JournalEntry, JournalLine

from datetime import date
from decimal import Decimal

def _create_account_groups(team):
    account_groups = {}

    group_definitions = [
        # Assets
        ("Bank Accounts", "asset", "Cash and bank-held funds"),
        ("Investment Accounts", "asset", "Long-term investments"),

        # Liabilities
        ("Credit Cards", "liability", "Credit card balances"),
        ("Loans & Mortgages", "liability", "Loans and mortgages"),
        ("Other Debt", "liability", "Other outstanding debt"),

        # Income
        ("Income", "income", "All income sources"),

        # Expenses
        ("Living Expenses", "expense", "Fixed living costs"),
        ("Regular Expenses", "expense", "Recurring monthly expenses"),
        ("Variable Expenses", "expense", "Flexible spending"),
        ("Other Expenses", "expense", "Miscellaneous expenses"),
    ]

    for name, account_type, description in group_definitions:
        group, _ = AccountGroup.objects.get_or_create(
            team=team,
            name=name,
            defaults={
                "account_type": account_type,
                "description": description,
            },
        )
        account_groups[name] = group

    return account_groups

def _create_accounts(team, account_groups):

    account_definitions = [
        # Assets (1000s)
        ("Chequing Account", 1000, "Bank Accounts"),
        ("Savings Account", 1100, "Bank Accounts"),
        ("Investment Account", 1200, "Investment Accounts"),

        # Liabilities (2000s)
        ("Credit Card", 2000, "Credit Cards"),
        ("Line of Credit", 2100, "Other Debt"),
        ("Mortgage", 2200, "Loans & Mortgages"),

        # Income (4000s)
        ("Salary Income", 4000, "Income"),
        ("Other Income", 4100, "Income"),

        # Expenses (5000s)
        ("Rent / Mortgage", 5000, "Living Expenses"),
        ("Utilities", 5100, "Regular Expenses"),
        ("Groceries", 5200, "Regular Expenses"),
        ("Transportation", 5300, "Regular Expenses"),
        ("Dining Out", 5400, "Variable Expenses"),
        ("Entertainment", 5500, "Variable Expenses"),
        ("Miscellaneous", 5900, "Other Expenses"),
    ]

    for name, number, group_name in account_definitions:
        Account.objects.get_or_create(
            team=team,
            account_number=number,
            defaults={
                "name": name,
                "account_group": account_groups[group_name],
            },
        )


def _create_payees(team):
    payee_names = [
        "Employer",
        "Grocery Store",
        "Rent / Mortgage",
        "Utility Company",
        "Credit Card Company",
        "Investment Provider",
    ]

    for name in payee_names:
        Payee.objects.get_or_create(
            team=team,
            name=name,
        )


def _create_journal_entries(team):
    today = date.today()
    month_start = today.replace(day=1)

    # Fetch accounts (safe lookups)
    chequing = Account.objects.get(team=team, account_number=1000)
    credit_card = Account.objects.get(team=team, account_number=2000)

    salary_income = Account.objects.get(team=team, account_number=4000)
    rent_expense = Account.objects.get(team=team, account_number=5000)
    groceries_expense = Account.objects.get(team=team, account_number=5200)

    # Fetch payees
    employer = Payee.objects.get(team=team, name="Employer")
    rent_payee = Payee.objects.get(team=team, name="Rent / Mortgage")
    grocery_store = Payee.objects.get(team=team, name="Grocery Store")

    # ------------------------
    # Journal Entry 1: Paycheque
    # ------------------------

    paycheque_entry, created = JournalEntry.objects.get_or_create(
        team=team,
        entry_date=month_start,
        description="Paycheque",
        defaults={
            "payee": employer,
            "status": JournalEntry.STATUS_POSTED,
            "source": JournalEntry.SOURCE_MANUAL,
        },
    )

    if created:
        JournalLine.objects.bulk_create([
            JournalLine(
                team=team,
                journal_entry=paycheque_entry,
                account=chequing,
                dr_amount=Decimal("3000.00"),
            ),
            JournalLine(
                team=team,
                journal_entry=paycheque_entry,
                account=salary_income,
                cr_amount=Decimal("3000.00"),
            ),
        ])

    # ------------------------
    # Journal Entry 2: Rent Payment
    # ------------------------

    rent_entry, created = JournalEntry.objects.get_or_create(
        team=team,
        entry_date=month_start,
        description="Monthly Rent",
        defaults={
            "payee": rent_payee,
            "status": JournalEntry.STATUS_POSTED,
            "source": JournalEntry.SOURCE_MANUAL,
        },
    )

    if created:
        JournalLine.objects.bulk_create([
            JournalLine(
                team=team,
                journal_entry=rent_entry,
                account=rent_expense,
                dr_amount=Decimal("1500.00"),
            ),
            JournalLine(
                team=team,
                journal_entry=rent_entry,
                account=chequing,
                cr_amount=Decimal("1500.00"),
            ),
        ])

    # ------------------------
    # Journal Entry 3: Groceries on Credit Card
    # ------------------------

    grocery_entry, created = JournalEntry.objects.get_or_create(
        team=team,
        entry_date=month_start,
        description="Groceries",
        defaults={
            "payee": grocery_store,
            "status": JournalEntry.STATUS_POSTED,
            "source": JournalEntry.SOURCE_MANUAL,
        },
    )

    if created:
        JournalLine.objects.bulk_create([
            JournalLine(
                team=team,
                journal_entry=grocery_entry,
                account=groceries_expense,
                dr_amount=Decimal("250.00"),
            ),
            JournalLine(
                team=team,
                journal_entry=grocery_entry,
                account=credit_card,
                cr_amount=Decimal("250.00"),
            ),
        ])


def bootstrap_team(team):
    """
    Create starter account groups, accounts, and payees for a new team.
    Must be idempotent.
    """
    account_groups = _create_account_groups(team)

    _create_accounts(team, account_groups)

    _create_payees(team)

    _create_journal_entries(team)
