from datetime import date, timedelta
from decimal import Decimal

from django.utils.formats import date_format

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

    def get_income_statement_data(self, start_date, end_date, period=None):
        """
        Calculate income statement data (Income vs Expenses) for the given date range.

        When period is "month", "quarter", or "year", every item/group/total also carries
        a per-period breakdown aligned with the returned 'periods' list (first day of each
        period in the range), with matching human-readable 'period_labels'.

        Returns:
            dict: {
                'income': [{'account': Account, 'amount': Decimal[, 'per_period': [Decimal, ...]]}, ...],
                'expenses': [{'account': Account, 'amount': Decimal[, 'per_period': [...]]}, ...],
                'income_groups': [{'group': AccountGroup, 'accounts': [...], 'subtotal': Decimal
                                   [, 'per_period': [...]]}, ...],
                'expense_groups': [...same shape...],
                'periods': [date, ...] (empty unless period given),
                'period_labels': [str, ...] (empty unless period given),
                'total_income': Decimal,
                'total_expenses': Decimal,
                'net_profit': Decimal,
                'total_income_per_period': [Decimal, ...] (empty unless period given),
                'total_expenses_per_period': [...],
                'net_profit_per_period': [...],
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

        periods = self._period_range(start_date, end_date, period) if period else []

        income_data = []
        expense_data = []
        total_income = Decimal("0")
        total_expenses = Decimal("0")

        # Group by account and calculate balances
        account_balances = {}
        account_periodic = {}  # account -> {period start date: Decimal}

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

            if period:
                bucket = self._period_start(line.journal_entry.entry_date, period)
                per_period = account_periodic.setdefault(account, {})
                per_period[bucket] = per_period.get(bucket, Decimal("0")) + amount

        # Sort accounts and build result data
        for account, amount in account_balances.items():
            if amount != 0:  # Only include accounts with activity
                item = {"account": account, "amount": amount}
                if period:
                    per_period = account_periodic.get(account, {})
                    item["per_period"] = [per_period.get(bucket, Decimal("0")) for bucket in periods]
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

        total_income_per_period = self._sum_periods(income_data, len(periods)) if period else []
        total_expenses_per_period = self._sum_periods(expense_data, len(periods)) if period else []
        net_profit_per_period = [
            inc - exp for inc, exp in zip(total_income_per_period, total_expenses_per_period, strict=True)
        ]

        return {
            "income": income_data,
            "expenses": expense_data,
            "income_groups": self._group_by_account_group(income_data, len(periods) if period else None),
            "expense_groups": self._group_by_account_group(expense_data, len(periods) if period else None),
            "periods": periods,
            "period_labels": [self._period_label(bucket, period) for bucket in periods],
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
            "total_income_per_period": total_income_per_period,
            "total_expenses_per_period": total_expenses_per_period,
            "net_profit_per_period": net_profit_per_period,
        }

    @staticmethod
    def _period_start(day, period):
        """First day of the month/quarter/year containing the given date."""
        if period == "year":
            return date(day.year, 1, 1)
        if period == "quarter":
            return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
        return day.replace(day=1)

    @classmethod
    def _period_range(cls, start_date, end_date, period):
        """Return the first day of each month/quarter/year between the dates, inclusive."""
        step_months = {"month": 1, "quarter": 3, "year": 12}[period]
        periods = []
        current = cls._period_start(start_date, period)
        while current <= end_date:
            periods.append(current)
            month = current.month + step_months
            year = current.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            current = date(year, month, 1)
        return periods

    @staticmethod
    def _period_label(bucket, period):
        """Human-readable column label for a period start date."""
        if period == "year":
            return str(bucket.year)
        if period == "quarter":
            return f"Q{(bucket.month - 1) // 3 + 1} {bucket.year}"
        return date_format(bucket, "M Y")

    @staticmethod
    def _sum_periods(items, num_periods):
        """Element-wise sum of the 'per_period' lists across items."""
        totals = [Decimal("0")] * num_periods
        for item in items:
            for i, amount in enumerate(item["per_period"]):
                totals[i] += amount
        return totals

    @classmethod
    def _group_by_account_group(cls, items, num_periods=None):
        """
        Group [{'account': Account, 'amount': Decimal}, ...] by the account's group.

        Returns:
            list: [{'group': AccountGroup, 'accounts': [items...], 'subtotal': Decimal}, ...]
            sorted by group name (items keep their incoming order within each group).
            When num_periods is given, each group also gets a 'per_period' element-wise
            subtotal of its accounts' 'per_period' lists.
        """
        groups = {}
        for item in items:
            group = item["account"].account_group
            if group.pk not in groups:
                groups[group.pk] = {"group": group, "accounts": [], "subtotal": Decimal("0")}
            groups[group.pk]["accounts"].append(item)
            groups[group.pk]["subtotal"] += item["amount"]
        result = sorted(groups.values(), key=lambda g: g["group"].name)
        if num_periods is not None:
            for group_data in result:
                group_data["per_period"] = cls._sum_periods(group_data["accounts"], num_periods)
        return result

    def get_balance_sheet_data(self, as_of_date):
        """
        Calculate balance sheet data (Assets, Liabilities, Equity) as of the given date.

        Returns:
            dict: {
                'assets': [{'account': Account, 'amount': Decimal}, ...],
                'liabilities': [{'account': Account, 'amount': Decimal}, ...],
                'equity': [{'account': Account, 'amount': Decimal}, ...],
                'asset_groups': [{'group': AccountGroup, 'accounts': [...], 'subtotal': Decimal}, ...],
                'liability_groups': [...same shape...],
                'equity_groups': [...same shape...],
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
            "asset_groups": self._group_by_account_group(asset_data),
            "liability_groups": self._group_by_account_group(liability_data),
            "equity_groups": self._group_by_account_group(equity_data),
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "net_worth": net_worth,
        }

    def get_balance_composition_data(self, start_date, end_date):
        """
        Month-end running balances per account group for asset and liability accounts,
        chart-ready (floats), for a stacked-area composition view.

        Returns:
            dict: {
                'labels': ['YYYY-MM-DD' month-end isoformat, ...],
                'asset_groups': [{'name': str, 'values': [float, ...]}, ...],
                'liability_groups': [{'name': str, 'values': [float, ...]}, ...],
            }
            Groups are sorted by final balance (largest first); groups with no
            balance in any month are dropped.
        """
        from django.db.models import F, Sum
        from django.db.models.functions import TruncMonth

        monthly_deltas = (
            JournalLine.objects.filter(
                team=self.team,
                journal_entry__entry_date__lte=end_date,
                account__account_group__account_type__in=[ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY],
            )
            .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
            .annotate(month=TruncMonth("journal_entry__entry_date"))
            .values(
                "month",
                "account__account_group_id",
                "account__account_group__name",
                "account__account_group__account_type",
            )
            .annotate(delta=Sum(F("dr_amount") - F("cr_amount")))
        )

        groups = {}  # group id -> {'name', 'type', 'deltas': {month: Decimal}}
        for row in monthly_deltas:
            month = row["month"].date() if hasattr(row["month"], "date") else row["month"]
            group = groups.setdefault(
                row["account__account_group_id"],
                {
                    "name": row["account__account_group__name"],
                    "type": row["account__account_group__account_type"],
                    "deltas": {},
                },
            )
            # Assets carry debit balances (dr - cr); liabilities credit balances (cr - dr)
            sign = 1 if group["type"] == ACCOUNT_TYPE_ASSET else -1
            group["deltas"][month] = group["deltas"].get(month, Decimal("0")) + sign * row["delta"]

        # Month axis
        months = []
        current = start_date.replace(day=1)
        while current <= end_date:
            month_end = (current + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            months.append((current, min(month_end, end_date)))
            current = (current + timedelta(days=32)).replace(day=1)

        first_month = start_date.replace(day=1)
        asset_series = []
        liability_series = []
        for group in groups.values():
            running = sum((amount for month, amount in group["deltas"].items() if month < first_month), Decimal("0"))
            values = []
            for month_start, _month_end in months:
                running += group["deltas"].get(month_start, Decimal("0"))
                values.append(float(running))
            if not any(values):
                continue
            target = asset_series if group["type"] == ACCOUNT_TYPE_ASSET else liability_series
            target.append({"name": group["name"], "values": values})

        for series in (asset_series, liability_series):
            series.sort(key=lambda s: s["values"][-1], reverse=True)

        return {
            "labels": [month_end.isoformat() for _start, month_end in months],
            "asset_groups": asset_series,
            "liability_groups": liability_series,
        }

    def get_account_activity(self, account, start_date=None, end_date=None):
        """
        Get detailed activity for a specific account within a date range.

        Returns:
            dict: {
                'account': Account,
                'transactions': [{
                    'date': date, 'payee': str, 'memo': str, 'amount': Decimal,
                    'source': str, 'is_reconciled': bool, 'is_cleared': bool,
                    'contra_accounts': [{'name': str, 'url': str}, ...],
                }, ...],
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
            .prefetch_related("journal_entry__lines__account__account_group")
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
            contra_accounts = [
                {"name": contra.account.name, "url": contra.account.get_absolute_url()}
                for contra in line.journal_entry.lines.all()
                if contra.pk != line.pk
            ]
            transaction_list.append(
                {
                    "date": line.journal_entry.entry_date,
                    "payee": line.journal_entry.payee.name if line.journal_entry.payee else "",
                    "memo": line.journal_entry.description,
                    "amount": line.signed_amount,
                    "source": line.journal_entry.get_source_display(),
                    "is_reconciled": line.is_reconciled,
                    "is_cleared": line.is_cleared,
                    "contra_accounts": contra_accounts,
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
        Calculate month-end net worth for each month in the given date range, with the
        assets/liabilities breakdown behind each point.

        A single aggregated query buckets asset/liability movement by month; running
        totals then produce each month-end balance (instead of one full balance-sheet
        query per month).

        Returns:
            list: [{'date': date, 'net_worth': Decimal, 'assets': Decimal, 'liabilities': Decimal}, ...]
        """
        from django.db.models import F, Sum
        from django.db.models.functions import TruncMonth

        monthly_deltas = (
            JournalLine.objects.filter(
                team=self.team,
                journal_entry__entry_date__lte=end_date,
                account__account_group__account_type__in=[ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY],
            )
            .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
            .annotate(month=TruncMonth("journal_entry__entry_date"))
            .values("month", "account__account_group__account_type")
            .annotate(delta=Sum(F("dr_amount") - F("cr_amount")))
        )

        asset_deltas = {}
        liability_deltas = {}
        for row in monthly_deltas:
            month = row["month"].date() if hasattr(row["month"], "date") else row["month"]
            if row["account__account_group__account_type"] == ACCOUNT_TYPE_ASSET:
                asset_deltas[month] = row["delta"]  # debit balance: dr - cr
            else:
                liability_deltas[month] = -row["delta"]  # credit balance: cr - dr

        # Opening balances from all activity before the first month in range
        first_month = start_date.replace(day=1)
        assets = sum((amount for month, amount in asset_deltas.items() if month < first_month), Decimal("0"))
        liabilities = sum((amount for month, amount in liability_deltas.items() if month < first_month), Decimal("0"))

        trend_data = []
        current = first_month
        while current <= end_date:
            assets += asset_deltas.get(current, Decimal("0"))
            liabilities += liability_deltas.get(current, Decimal("0"))
            month_end = (current + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            trend_data.append(
                {
                    "date": min(month_end, end_date),
                    "net_worth": assets - liabilities,
                    "assets": assets,
                    "liabilities": liabilities,
                }
            )
            current = (current + timedelta(days=32)).replace(day=1)

        return trend_data
