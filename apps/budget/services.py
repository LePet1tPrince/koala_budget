# apps/budget/services.py

from datetime import date
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from django.db.models import Sum, F

from apps.accounts.models import Account
from apps.budget.models import Budget
from apps.journal.models import JournalLine


class BudgetService:
    def __init__(self, team):
        self.team = team

    def month_bounds(self, month: date):
        """Return start and end dates for a given month."""
        start = month.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end

    def month_start(self, date_obj: date):
        """Return the first day of the month for a given date."""
        return date_obj.replace(day=1)

    def actual(self, category, month):
        """
        Calculate actual spending/income for a category in a given month.
        Returns the net amount (debits - credits) for the account in that month.
        """
        start, end = self.month_bounds(month)

        qs = (
            JournalLine.objects
            .filter(
                team=self.team,
                journal_entry__entry_date__gte=start,
                journal_entry__entry_date__lt=end,
                account=category,
            )
            .values("account_id")
            .annotate(
                actual=Sum("dr_amount") - Sum("cr_amount")
            )
            .order_by("account_id")
        )

        result = qs.first()
        return result["actual"] if result else Decimal("0")

    def budgeted(self, category, month):
        """
        Get the budgeted amount for a category in a given month.
        Returns 0 if no budget exists.
        """
        budget = (
            Budget.objects
            .filter(team=self.team, category=category, month=month)
            .first()
        )
        return budget.budget_amount if budget else Decimal("0")

    def available(self, category, month):
        """
        Calculate available amount for a category in a given month.
        Formula: Budget(this month) - Actual(this month) + Available(previous month)
        This creates a recursive calculation where unspent budget rolls forward.
        """
        # Get previous month
        prev_month = month - relativedelta(months=1)

        # Base case: check if there are any budgets or transactions for this category
        first_budget = (
            Budget.objects
            .filter(team=self.team, category=category)
            .order_by("month")
            .first()
        )

        first_txn = (
            JournalLine.objects
            .filter(team=self.team, account=category)
            .order_by("journal_entry__entry_date")
            .first()
        )

        # Determine the earliest month we need to consider
        if first_budget and first_txn:
            first_month = min(
                first_budget.month,
                self.month_start(first_txn.journal_entry.entry_date)
            )
        elif first_budget:
            first_month = first_budget.month
        elif first_txn:
            first_month = self.month_start(first_txn.journal_entry.entry_date)
        else:
            # No budgets or transactions, just return current budget (likely 0)
            return self.budgeted(category, month)

        # If this is the first month with budget/activity, no previous available
        if month <= first_month:
            return self.budgeted(category, month) - self.actual(category, month)

        # Recursive case: Budget - Actual + Available from previous month
        prev_available = self.available(category, prev_month)
        current_budget = self.budgeted(category, month)
        current_actual = self.actual(category, month)

        return current_budget - current_actual + prev_available

    def get_actuals_by_category(self, month):
        """
        Get actual amounts for all expense categories in a given month.
        Returns a dictionary mapping account_id to actual amount.
        """
        start, end = self.month_bounds(month)

        qs = (
            JournalLine.objects
            .filter(
                team=self.team,
                journal_entry__entry_date__gte=start,
                journal_entry__entry_date__lt=end,
                account__account_group__account_type="expense",
            )
            .values("account_id")
            .annotate(
                actual=Sum("dr_amount") - Sum("cr_amount")
            )
        )

        return {
            row["account_id"]: row["actual"] or Decimal("0")
            for row in qs
        }

    def get_budgets_by_category(self, month):
        """
        Get budgets for all categories in a given month.
        Returns a dictionary mapping category_id to Budget instance.
        """
        return {
            b.category_id: b
            for b in Budget.objects.filter(
                team=self.team,
                month=month,
            )
        }

    def build_budget_rows(self, month):
        """
        Build budget rows for API response.
        Returns a list of dictionaries with budget data for each account.
        """
        accounts = (
            Account.objects
            .filter(
                team=self.team,
                account_group__account_type="expense",
            )
            .select_related("account_group")
            .order_by("account_number")
        )

        actuals = self.get_actuals_by_category(month)
        budgets = self.get_budgets_by_category(month)

        rows = []

        for account in accounts:
            budget = budgets.get(account.pk)

            budgeted = (
                budget.budget_amount
                if budget else Decimal("0")
            )

            actual = actuals.get(account.pk, Decimal("0"))

            rows.append({
                "category_id": account.pk,
                "category_name": account.name,
                "account_group": account.account_group.name,
                "month": month,
                "budget_id": budget.id if budget else None,
                "budgeted": budgeted,
                "actual": actual,
                "available": budgeted - actual,
            })

        return rows
