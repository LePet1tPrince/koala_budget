# apps/budget/services.py

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db.models import Sum

from apps.accounts.models import Account
from apps.budget.models import Budget, Goal, GoalAllocation
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
        For expense accounts: debits - credits (net spending)
        For income accounts: credits - debits (net income)
        """
        start, end = self.month_bounds(month)

        # Determine calculation based on account type
        if category.account_group.account_type == "income":
            # For income: credits - debits
            actual_expression = Sum("cr_amount") - Sum("dr_amount")
        else:
            # For expenses/assets/liabilities: debits - credits
            actual_expression = Sum("dr_amount") - Sum("cr_amount")

        qs = (
            JournalLine.objects
            .filter(
                team=self.team,
                journal_entry__entry_date__gte=start,
                journal_entry__entry_date__lt=end,
                account=category,
            )
            .values("account_id")
            .annotate(actual=actual_expression)
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
        For income accounts: Actual(this month) - Budget(this month) + Available(previous month)
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
            # Calculate based on account type
            budget = self.budgeted(category, month)
            actual = self.actual(category, month)
            if category.account_group.account_type == "income":
                return actual - budget
            else:
                return budget - actual

        # Recursive case: Budget - Actual + Available from previous month (or Actual - Budget for income)
        prev_available = self.available(category, prev_month)
        current_budget = self.budgeted(category, month)
        current_actual = self.actual(category, month)

        if category.account_group.account_type == "income":
            return current_actual - current_budget + prev_available
        else:
            return current_budget - current_actual + prev_available

    def get_actuals_by_category(self, month):
        """
        Get actual amounts for all expense and income categories in a given month.
        Returns a dictionary mapping account_id to actual amount.
        """
        start, end = self.month_bounds(month)

        # Get expense accounts: dr - cr
        expense_qs = (
            JournalLine.objects
            .filter(
                team=self.team,
                journal_entry__entry_date__gte=start,
                journal_entry__entry_date__lt=end,
                account__account_group__account_type="expense",
            )
            .values("account_id")
            .annotate(actual=Sum("dr_amount") - Sum("cr_amount"))
        )

        # Get income accounts: cr - dr
        income_qs = (
            JournalLine.objects
            .filter(
                team=self.team,
                journal_entry__entry_date__gte=start,
                journal_entry__entry_date__lt=end,
                account__account_group__account_type="income",
            )
            .values("account_id")
            .annotate(actual=Sum("cr_amount") - Sum("dr_amount"))
        )

        # Combine results
        result = {}
        for row in expense_qs:
            result[row["account_id"]] = row["actual"] or Decimal("0")
        for row in income_qs:
            result[row["account_id"]] = row["actual"] or Decimal("0")

        return result

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

    def get_first_activity_month(self):
        """
        Get the earliest month with any budget or transaction for the team.
        Returns None if no activity exists.
        """
        first_budget = (
            Budget.objects
            .filter(team=self.team)
            .order_by("month")
            .values_list("month", flat=True)
            .first()
        )

        first_txn_date = (
            JournalLine.objects
            .filter(team=self.team)
            .order_by("journal_entry__entry_date")
            .values_list("journal_entry__entry_date", flat=True)
            .first()
        )

        if first_budget and first_txn_date:
            first_txn_month = self.month_start(first_txn_date)
            return min(first_budget, first_txn_month)
        elif first_budget:
            return first_budget
        elif first_txn_date:
            return self.month_start(first_txn_date)
        return None

    def get_all_budgets_by_month_category(self, start_month, end_month):
        """
        Fetch all budgets from start_month to end_month (inclusive).
        Returns dict: {(month, category_id): budget_amount}
        """
        budgets = Budget.objects.filter(
            team=self.team,
            month__gte=start_month,
            month__lte=end_month,
        ).values("month", "category_id", "budget_amount")

        return {
            (b["month"], b["category_id"]): b["budget_amount"]
            for b in budgets
        }

    def get_all_actuals_by_month_category(self, start_month, end_month):
        """
        Fetch all actuals from start_month to end_month (inclusive).
        Returns dict: {(month, category_id): actual_amount}
        Uses Django's TruncMonth to group by month.
        """
        from django.db.models.functions import TruncMonth

        # Get expense accounts: dr - cr
        expense_qs = (
            JournalLine.objects
            .filter(
                team=self.team,
                journal_entry__entry_date__gte=start_month,
                journal_entry__entry_date__lt=end_month + relativedelta(months=1),
                account__account_group__account_type="expense",
            )
            .annotate(month=TruncMonth("journal_entry__entry_date"))
            .values("month", "account_id")
            .annotate(actual=Sum("dr_amount") - Sum("cr_amount"))
        )

        # Get income accounts: cr - dr
        income_qs = (
            JournalLine.objects
            .filter(
                team=self.team,
                journal_entry__entry_date__gte=start_month,
                journal_entry__entry_date__lt=end_month + relativedelta(months=1),
                account__account_group__account_type="income",
            )
            .annotate(month=TruncMonth("journal_entry__entry_date"))
            .values("month", "account_id")
            .annotate(actual=Sum("cr_amount") - Sum("dr_amount"))
        )

        result = {}
        for row in expense_qs:
            month_date = row["month"].date() if hasattr(row["month"], "date") else row["month"]
            result[(month_date, row["account_id"])] = row["actual"] or Decimal("0")
        for row in income_qs:
            month_date = row["month"].date() if hasattr(row["month"], "date") else row["month"]
            result[(month_date, row["account_id"])] = row["actual"] or Decimal("0")

        return result

    def get_available_by_category(self, month, categories):
        """
        Calculate available amounts for all categories up to a given month.
        Uses bulk queries instead of per-category recursion.
        Returns a dictionary mapping account_id to available amount.
        """
        first_month = self.get_first_activity_month()

        if not first_month:
            # No activity, return zeros
            return {cat.pk: Decimal("0") for cat in categories}

        # If requested month is before first activity, return zeros
        if month < first_month:
            return {cat.pk: Decimal("0") for cat in categories}

        # Build a dict of account_type by category_id for fast lookup
        account_types = {cat.pk: cat.account_group.account_type for cat in categories}

        # Bulk fetch all budgets and actuals for the entire date range
        all_budgets = self.get_all_budgets_by_month_category(first_month, month)
        all_actuals = self.get_all_actuals_by_month_category(first_month, month)

        # Initialize available amounts
        available = {cat.pk: Decimal("0") for cat in categories}

        # Iterate from first_month to the requested month
        current_month = first_month
        while current_month <= month:
            for cat in categories:
                cat_id = cat.pk
                budgeted = all_budgets.get((current_month, cat_id), Decimal("0"))
                actual = all_actuals.get((current_month, cat_id), Decimal("0"))

                if account_types[cat_id] == "income":
                    # For income: Available = Actual - Budget + Previous Available
                    available[cat_id] = actual - budgeted + available[cat_id]
                else:
                    # For expenses: Available = Budget - Actual + Previous Available
                    available[cat_id] = budgeted - actual + available[cat_id]

            # Move to next month
            current_month = current_month + relativedelta(months=1)

        return available

    def build_budget_rows(self, month):
        """
        Build budget rows for API response.
        Returns a list of dictionaries with budget data for each account.
        """
        accounts = (
            Account.objects
            .filter(
                team=self.team,
                account_group__account_type__in=("expense", "income"),
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

            # Calculate available based on account type
            if account.account_group.account_type == "income":
                available = actual - budgeted
            else:
                available = budgeted - actual

            rows.append({
                "category_id": account.pk,
                "category_name": account.name,
                "account_group": account.account_group.name,
                "month": month,
                "budget_id": budget.id if budget else None,
                "budgeted": budgeted,
                "actual": actual,
                "available": available,
            })

        return rows


class GoalService:
    """Service class for goal-related calculations and queries."""

    def __init__(self, team):
        self.team = team

    def get_goals_with_progress(self, month=None, include_archived=False):
        """Get all goals with progress annotations for a given month."""
        qs = Goal.objects.filter(team=self.team)
        if not include_archived:
            qs = qs.filter(is_archived=False)
        return qs.with_progress(month).select_related("account")

    def get_total_saved(self):
        """Get the total amount saved across all active goals."""
        return GoalAllocation.objects.filter(
            team=self.team,
            goal__is_archived=False
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    def get_goal_summary(self, month):
        """Get summary data for the goals section of the budget page."""
        goals = self.get_goals_with_progress(month)
        total_target = goals.aggregate(total=Sum("target_amount"))["total"] or Decimal("0")
        total_saved = goals.aggregate(total=Sum("total_saved"))["total"] or Decimal("0")

        return {
            "goals": goals,
            "total_target": total_target,
            "total_saved": total_saved,
            "goal_count": goals.count(),
        }

    def update_allocation(self, goal, month, amount):
        """Create or update a goal allocation for a specific month."""
        month = month.replace(day=1)
        allocation, created = GoalAllocation.objects.update_or_create(
            team=self.team,
            goal=goal,
            month=month,
            defaults={"amount": amount}
        )
        return allocation


class NetWorthService:
    """Service class for net worth and financial summary calculations."""

    def __init__(self, team):
        self.team = team

    def get_net_worth(self, month):
        """
        Calculate net worth as of the end of a given month.
        Net worth = sum of (dr_amount - cr_amount) for all asset and liability accounts.
        For assets: positive balance means we own it
        For liabilities: positive balance (dr > cr) would reduce net worth, but typically
        liabilities have cr > dr, so the subtraction gives negative, which is correct.
        """
        from dateutil.relativedelta import relativedelta

        # End of month (first day of next month)
        end_date = month.replace(day=1) + relativedelta(months=1)

        result = (
            JournalLine.objects
            .filter(
                team=self.team,
                journal_entry__entry_date__lt=end_date,
                account__account_group__account_type__in=["asset", "liability"],
            )
            .aggregate(
                total_dr=Sum("dr_amount"),
                total_cr=Sum("cr_amount"),
            )
        )

        total_dr = result["total_dr"] or Decimal("0")
        total_cr = result["total_cr"] or Decimal("0")

        # Net worth is assets - liabilities
        # Assets have dr > cr (positive balance)
        # Liabilities have cr > dr (negative when doing dr - cr)
        # So dr - cr gives us: assets - liabilities = net worth
        return total_dr - total_cr

    def get_total_saved_to_goals(self):
        """
        Get the total amount allocated to all active goals.
        This represents money set aside for savings goals.
        """
        return GoalAllocation.objects.filter(
            team=self.team,
            goal__is_archived=False,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    def get_total_available_to_spend(self, month, categories=None):
        """
        Get the sum of all 'available' amounts across budget categories.
        This represents money available to spend from the budget.
        """
        budget_service = BudgetService(self.team)

        if categories is None:
            categories = list(Account.objects.filter(
                team=self.team,
                account_group__account_type__in=("expense", "income"),
            ).select_related("account_group"))

        if not categories:
            return Decimal("0")

        available_map = budget_service.get_available_by_category(month, categories)
        return sum(available_map.values())

    def get_net_worth_card_data(self, month, categories=None):
        """
        Get all data needed for the NetWorthCard component.

        Returns:
            dict with keys:
            - net_worth: Total assets minus liabilities
            - save: Total allocated to goals
            - spend: Total available in budget categories
            - available: net_worth - save - spend (unallocated money)
        """
        net_worth = self.get_net_worth(month)
        save = self.get_total_saved_to_goals()
        spend = self.get_total_available_to_spend(month, categories)
        available = net_worth - save - spend

        return {
            "net_worth": net_worth,
            "save": save,
            "spend": spend,
            "available": available,
        }
