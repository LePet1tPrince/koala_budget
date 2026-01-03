from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EQUITY, ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_LIABILITY
from apps.journal.models import JournalLine


class ReportService:
    """
    Service class for generating financial reports from journal data.
    """

    def __init__(self, team):
        self.team = team

    def get_income_statement_data(self, start_date, end_date):
        """
        Calculate income statement data (Income vs Expenses) for the given date range.

        Returns:
            dict: {
                'income': [{'account': Account, 'amount': Decimal}, ...],
                'expenses': [{'account': Account, 'amount': Decimal}, ...],
                'total_income': Decimal,
                'total_expenses': Decimal,
                'net_profit': Decimal
            }
        """
        # Get all journal lines for posted entries in date range
        journal_lines = JournalLine.objects.filter(
            team=self.team,
            journal_entry__entry_date__range=(start_date, end_date),
            journal_entry__status='posted'
        ).select_related('account', 'account__account_group')

        income_data = []
        expense_data = []
        total_income = Decimal('0')
        total_expenses = Decimal('0')

        # Group by account and calculate balances
        account_balances = {}

        for line in journal_lines:
            account = line.account
            account_type = account.account_group.account_type

            # Calculate the net impact of this journal line
            # For income: credits increase income
            # For expenses: debits increase expenses
            if account_type == ACCOUNT_TYPE_INCOME:
                amount = line.cr_amount - line.dr_amount
            elif account_type == ACCOUNT_TYPE_EXPENSE:
                amount = line.dr_amount - line.cr_amount
            else:
                continue  # Skip non-income/expense accounts

            if account not in account_balances:
                account_balances[account] = Decimal('0')
            account_balances[account] += amount

        # Sort accounts and build result data
        for account, amount in account_balances.items():
            if amount != 0:  # Only include accounts with activity
                account_type = account.account_group.account_type
                if account_type == ACCOUNT_TYPE_INCOME:
                    income_data.append({'account': account, 'amount': amount})
                    total_income += amount
                elif account_type == ACCOUNT_TYPE_EXPENSE:
                    expense_data.append({'account': account, 'amount': amount})
                    total_expenses += amount

        # Sort by account number
        income_data.sort(key=lambda x: x['account'].account_number)
        expense_data.sort(key=lambda x: x['account'].account_number)

        net_profit = total_income - total_expenses

        return {
            'income': income_data,
            'expenses': expense_data,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'net_profit': net_profit,
        }

    def get_balance_sheet_data(self, as_of_date):
        """
        Calculate balance sheet data (Assets, Liabilities, Equity) as of the given date.

        Returns:
            dict: {
                'assets': [{'account': Account, 'amount': Decimal}, ...],
                'liabilities': [{'account': Account, 'amount': Decimal}, ...],
                'equity': [{'account': Account, 'amount': Decimal}, ...],
                'total_assets': Decimal,
                'total_liabilities': Decimal,
                'total_equity': Decimal,
                'net_worth': Decimal
            }
        """
        # Get all journal lines for posted entries up to as_of_date
        journal_lines = JournalLine.objects.filter(
            team=self.team,
            journal_entry__entry_date__lte=as_of_date,
            journal_entry__status='posted'
        ).select_related('account', 'account__account_group')

        asset_data = []
        liability_data = []
        equity_data = []
        total_assets = Decimal('0')
        total_liabilities = Decimal('0')
        total_equity = Decimal('0')

        # Group by account and calculate balances
        account_balances = {}

        for line in journal_lines:
            account = line.account
            account_type = account.account_group.account_type

            # Calculate account balance: debits - credits
            amount = line.dr_amount - line.cr_amount

            if account not in account_balances:
                account_balances[account] = Decimal('0')
            account_balances[account] += amount

        # Sort accounts and build result data
        for account, amount in account_balances.items():
            if amount != 0:  # Only include accounts with balances
                account_type = account.account_group.account_type
                if account_type == ACCOUNT_TYPE_ASSET:
                    asset_data.append({'account': account, 'amount': amount})
                    total_assets += amount
                elif account_type == ACCOUNT_TYPE_LIABILITY:
                    liability_data.append({'account': account, 'amount': amount})
                    total_liabilities += amount
                elif account_type == ACCOUNT_TYPE_EQUITY:
                    equity_data.append({'account': account, 'amount': amount})
                    total_equity += amount

        # Sort by account number
        asset_data.sort(key=lambda x: x['account'].account_number)
        liability_data.sort(key=lambda x: x['account'].account_number)
        equity_data.sort(key=lambda x: x['account'].account_number)

        net_worth = total_assets - total_liabilities

        return {
            'assets': asset_data,
            'liabilities': liability_data,
            'equity': equity_data,
            'total_assets': total_assets,
            'total_liabilities': total_liabilities,
            'total_equity': total_equity,
            'net_worth': net_worth,
        }

    def get_net_worth_trend_data(self, num_months):
        """
        Calculate net worth trend data for the last num_months.

        Returns:
            list: [{'date': date, 'net_worth': Decimal}, ...]
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=num_months * 30)  # Approximate months

        trend_data = []

        # Calculate net worth for each month end
        current_date = start_date.replace(day=1)
        while current_date <= end_date:
            month_end = (current_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)

            # Don't calculate future months
            if month_end > end_date:
                month_end = end_date

            balance_data = self.get_balance_sheet_data(month_end)
            trend_data.append({
                'date': month_end,
                'net_worth': balance_data['net_worth'],
            })

            # Move to next month
            current_date = (current_date + timedelta(days=32)).replace(day=1)

        return trend_data
