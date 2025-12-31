# apps/budget/services.py

from datetime import date
from decimal import Decimal
from django.db.models import Sum
from django.utils.timezone import make_aware

from apps.accounts.models import Account
from apps.budget.models import Budget
from apps.journal.models import JournalLine


class BudgetService:
    def __init__(self, team):
        self.team = team

    def month_bounds(self, month: date):
        start = month.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end

    def get_actuals_by_category(self, month):
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
        return {
            b.category_id: b
            for b in Budget.objects.filter(
                team=self.team,
                month=month,
            )
        }

    def build_budget_rows(self, month):
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
