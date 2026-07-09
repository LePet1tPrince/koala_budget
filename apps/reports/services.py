from datetime import date, timedelta
from decimal import Decimal

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
)
from apps.journal.models import JournalEntry, JournalLine


class ReportService:
    """
    Service class for generating financial reports from journal data.
    """

    def __init__(self, team):
        self.team = team

    def get_income_statement_data(self, start_date, end_date, by_month=False):
        """
        Calculate income statement data (Income vs Expenses) for the given date range.

        When by_month is True, every item/group/total also carries a per-month breakdown
        aligned with the returned 'months' list (first day of each month in the range).

        Returns:
            dict: {
                'income': [{'account': Account, 'amount': Decimal[, 'monthly': [Decimal, ...]]}, ...],
                'expenses': [{'account': Account, 'amount': Decimal[, 'monthly': [...]]}, ...],
                'income_groups': [{'group': AccountGroup, 'accounts': [...], 'subtotal': Decimal
                                   [, 'monthly': [...]]}, ...],
                'expense_groups': [...same shape...],
                'months': [date, ...] (empty unless by_month),
                'total_income': Decimal,
                'total_expenses': Decimal,
                'net_profit': Decimal,
                'total_income_monthly': [Decimal, ...] (empty unless by_month),
                'total_expenses_monthly': [...],
                'net_profit_monthly': [...],
            }
        """
        # Get all journal lines in the date range (voided entries don't count)
        journal_lines = (
            JournalLine.objects.filter(
                team=self.team,
                journal_entry__entry_date__range=(start_date, end_date),
            )
            .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
            .select_related("account", "account__account_group", "journal_entry")
        )

        months = self._month_range(start_date, end_date) if by_month else []

        income_data = []
        expense_data = []
        total_income = Decimal("0")
        total_expenses = Decimal("0")

        # Group by account and calculate balances
        account_balances = {}
        account_monthly = {}  # account -> {month: Decimal}

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
                account_balances[account] = Decimal("0")
            account_balances[account] += amount

            if by_month:
                month = line.journal_entry.entry_date.replace(day=1)
                per_month = account_monthly.setdefault(account, {})
                per_month[month] = per_month.get(month, Decimal("0")) + amount

        # Sort accounts and build result data
        for account, amount in account_balances.items():
            if amount != 0:  # Only include accounts with activity
                item = {"account": account, "amount": amount}
                if by_month:
                    per_month = account_monthly.get(account, {})
                    item["monthly"] = [per_month.get(month, Decimal("0")) for month in months]
                account_type = account.account_group.account_type
                if account_type == ACCOUNT_TYPE_INCOME:
                    income_data.append(item)
                    total_income += amount
                elif account_type == ACCOUNT_TYPE_EXPENSE:
                    expense_data.append(item)
                    total_expenses += amount

        # Sort by account name
        income_data.sort(key=lambda x: x["account"].name)
        expense_data.sort(key=lambda x: x["account"].name)

        net_profit = total_income - total_expenses

        total_income_monthly = self._sum_monthly(income_data, len(months)) if by_month else []
        total_expenses_monthly = self._sum_monthly(expense_data, len(months)) if by_month else []
        net_profit_monthly = [inc - exp for inc, exp in zip(total_income_monthly, total_expenses_monthly, strict=True)]

        return {
            "income": income_data,
            "expenses": expense_data,
            "income_groups": self._group_by_account_group(income_data, len(months) if by_month else None),
            "expense_groups": self._group_by_account_group(expense_data, len(months) if by_month else None),
            "months": months,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
            "total_income_monthly": total_income_monthly,
            "total_expenses_monthly": total_expenses_monthly,
            "net_profit_monthly": net_profit_monthly,
        }

    @staticmethod
    def _month_range(start_date, end_date):
        """Return the first day of each month between start_date and end_date, inclusive."""
        months = []
        current = start_date.replace(day=1)
        while current <= end_date:
            months.append(current)
            current = (current + timedelta(days=32)).replace(day=1)
        return months

    @staticmethod
    def _sum_monthly(items, num_months):
        """Element-wise sum of the 'monthly' lists across items."""
        totals = [Decimal("0")] * num_months
        for item in items:
            for i, amount in enumerate(item["monthly"]):
                totals[i] += amount
        return totals

    @classmethod
    def _group_by_account_group(cls, items, num_months=None):
        """
        Group [{'account': Account, 'amount': Decimal}, ...] by the account's group.

        Returns:
            list: [{'group': AccountGroup, 'accounts': [items...], 'subtotal': Decimal}, ...]
            sorted by group name (items keep their incoming order within each group).
            When num_months is given, each group also gets a 'monthly' element-wise
            subtotal of its accounts' 'monthly' lists.
        """
        groups = {}
        for item in items:
            group = item["account"].account_group
            if group.pk not in groups:
                groups[group.pk] = {"group": group, "accounts": [], "subtotal": Decimal("0")}
            groups[group.pk]["accounts"].append(item)
            groups[group.pk]["subtotal"] += item["amount"]
        result = sorted(groups.values(), key=lambda g: g["group"].name)
        if num_months is not None:
            for group_data in result:
                group_data["monthly"] = cls._sum_monthly(group_data["accounts"], num_months)
        return result

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
        # Get all journal lines up to as_of_date (voided entries don't count)
        journal_lines = (
            JournalLine.objects.filter(
                team=self.team,
                journal_entry__entry_date__lte=as_of_date,
            )
            .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
            .select_related("account", "account__account_group")
        )

        asset_data = []
        liability_data = []
        equity_data = []
        total_assets = Decimal("0")
        total_liabilities = Decimal("0")
        total_equity = Decimal("0")

        # Group by account and calculate balances
        account_balances = {}

        for line in journal_lines:
            account = line.account
            account_type = account.account_group.account_type

            # Calculate account balance based on account type
            # Assets: debit balances are positive (dr - cr)
            # Liabilities/Equity: credit balances are positive (cr - dr)
            if account_type in [ACCOUNT_TYPE_ASSET]:
                amount = line.dr_amount - line.cr_amount
            elif account_type in [ACCOUNT_TYPE_LIABILITY, ACCOUNT_TYPE_EQUITY]:
                amount = line.cr_amount - line.dr_amount
            else:
                continue  # Skip other account types

            if account not in account_balances:
                account_balances[account] = Decimal("0")
            account_balances[account] += amount

        # Sort accounts and build result data
        for account, amount in account_balances.items():
            if amount != 0:  # Only include accounts with balances
                account_type = account.account_group.account_type
                if account_type == ACCOUNT_TYPE_ASSET:
                    asset_data.append({"account": account, "amount": amount})
                    total_assets += amount
                elif account_type == ACCOUNT_TYPE_LIABILITY:
                    liability_data.append({"account": account, "amount": amount})
                    total_liabilities += amount
                elif account_type == ACCOUNT_TYPE_EQUITY:
                    equity_data.append({"account": account, "amount": amount})
                    total_equity += amount

        # Sort by account number
        asset_data.sort(key=lambda x: x["account"].name)
        liability_data.sort(key=lambda x: x["account"].name)
        equity_data.sort(key=lambda x: x["account"].name)

        net_worth = total_assets - total_liabilities

        return {
            "assets": asset_data,
            "liabilities": liability_data,
            "equity": equity_data,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "net_worth": net_worth,
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
            trend_data.append(
                {
                    "date": month_end,
                    "net_worth": balance_data["net_worth"],
                }
            )

            # Move to next month
            current_date = (current_date + timedelta(days=32)).replace(day=1)

        return trend_data

    def get_account_activity(self, account, start_date=None, end_date=None):
        """
        Get detailed activity for a specific account within a date range.

        Returns:
            dict: {
                'account': Account,
                'transactions': [{'date': date, 'payee': str, 'memo': str, 'amount': Decimal}, ...],
                'total': Decimal
            }
        """
        from django.db.models import F

        # Build the queryset (voided entries don't count)
        queryset = (
            JournalLine.objects.filter(
                team=self.team,
                account=account,
            )
            .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
            .select_related("journal_entry", "journal_entry__payee")
        )

        # Apply date filter if provided
        if start_date and end_date:
            queryset = queryset.filter(journal_entry__entry_date__range=(start_date, end_date))

        # Determine account type for sign logic
        account_type = account.account_group.account_type

        # Annotate signed amount based on account type
        if account_type == ACCOUNT_TYPE_INCOME:
            # Income: credits increase income
            signed_amount = F("cr_amount") - F("dr_amount")
        elif account_type == ACCOUNT_TYPE_EXPENSE:
            # Expenses: debits increase expenses
            signed_amount = F("dr_amount") - F("cr_amount")
        else:
            # For other account types, use debit - credit (asset/liability/equity logic)
            signed_amount = F("dr_amount") - F("cr_amount")

        transactions = queryset.annotate(signed_amount=signed_amount).order_by("journal_entry__entry_date")

        # Build transaction list
        transaction_list = []
        total = Decimal("0")

        for line in transactions:
            transaction_list.append(
                {
                    "date": line.journal_entry.entry_date,
                    "payee": line.journal_entry.payee.name if line.journal_entry.payee else "",
                    "memo": line.journal_entry.description,
                    "amount": line.signed_amount,
                }
            )
            total += line.signed_amount

        return {
            "account": account,
            "transactions": transaction_list,
            "total": total,
        }

    def get_net_worth_trend_data_by_date_range(self, start_date, end_date):
        """
        Calculate net worth trend data for the given date range, showing monthly data.

        Returns:
            list: [{'date': date, 'net_worth': Decimal}, ...]
        """
        trend_data = []

        # Calculate net worth for each month end within the date range
        current_date = start_date.replace(day=1)
        while current_date <= end_date:
            month_end = (current_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)

            # Don't calculate months beyond the end date
            if month_end > end_date:
                month_end = end_date

            balance_data = self.get_balance_sheet_data(month_end)
            trend_data.append(
                {
                    "date": month_end,
                    "net_worth": balance_data["net_worth"],
                }
            )

            # Move to next month
            current_date = (current_date + timedelta(days=32)).replace(day=1)

            # Prevent infinite loop if we somehow go beyond end_date
            if current_date > end_date and month_end >= end_date:
                break

        return trend_data
