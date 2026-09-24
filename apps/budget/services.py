# apps/budget/services.py

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import Account
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.journal.models import JournalLine, counted_entries


def _active_lines():
    """Journal lines that count toward budgets/net worth (voided entries don't)."""
    return JournalLine.objects.filter(counted_entries("journal_entry__"))


class BudgetService:
    def __init__(self, team):
        self.team = team

    def month_bounds(self, month: date):
        """Return start and end dates for a given month."""
        start = month.replace(day=1)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
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
            _active_lines()
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
        budget = Budget.objects.filter(team=self.team, category=category, month=month).first()
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
        first_budget = Budget.objects.filter(team=self.team, category=category).order_by("month").first()

        first_txn = (
            JournalLine.objects.filter(team=self.team, account=category).order_by("journal_entry__entry_date").first()
        )

        # Determine the earliest month we need to consider
        if first_budget and first_txn:
            first_month = min(first_budget.month, self.month_start(first_txn.journal_entry.entry_date))
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
            _active_lines()
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
            _active_lines()
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
        first_budget = Budget.objects.filter(team=self.team).order_by("month").values_list("month", flat=True).first()

        first_txn_date = (
            JournalLine.objects.filter(team=self.team)
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

        return {(b["month"], b["category_id"]): b["budget_amount"] for b in budgets}

    def get_all_actuals_by_month_category(self, start_month, end_month):
        """
        Fetch all actuals from start_month to end_month (inclusive).
        Returns dict: {(month, category_id): actual_amount}
        Uses Django's TruncMonth to group by month.
        """
        from django.db.models.functions import TruncMonth

        # Get expense accounts: dr - cr
        expense_qs = (
            _active_lines()
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
            _active_lines()
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
        return self.get_available_with_previous(month, categories)[0]

    def get_available_with_previous(self, month, categories):
        """
        Available per category at the end of `month` and at the end of the month
        before it, from the one pass `get_available_by_category` makes anyway.

        The previous month's figure is what rolled over into `month`; the
        Unassigned metric splits envelopes into "rolled over" and "this month" by it.
        """
        zeros = {cat.pk: Decimal("0") for cat in categories}
        first_month = self.get_first_activity_month()

        # No activity yet, or none by the requested month
        if not first_month or month < first_month:
            return zeros, dict(zeros)

        # Build a dict of account_type by category_id for fast lookup
        account_types = {cat.pk: cat.account_group.account_type for cat in categories}

        # Bulk fetch all budgets and actuals for the entire date range
        all_budgets = self.get_all_budgets_by_month_category(first_month, month)
        all_actuals = self.get_all_actuals_by_month_category(first_month, month)

        # Initialize available amounts
        available = dict(zeros)
        previous = dict(zeros)

        # Iterate from first_month to the requested month
        current_month = first_month
        while current_month <= month:
            if current_month == month:
                previous = dict(available)
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

        return available, previous

    def build_budget_rows(self, month):
        """
        Build budget rows for API response.
        Returns a list of dictionaries with budget data for each account.
        """
        accounts = (
            Account.objects.filter(
                team=self.team,
                account_group__account_type__in=("expense", "income"),
            )
            .select_related("account_group")
            .order_by("name")
        )

        actuals = self.get_actuals_by_category(month)
        budgets = self.get_budgets_by_category(month)

        rows = []

        for account in accounts:
            budget = budgets.get(account.pk)

            budgeted = budget.budget_amount if budget else Decimal("0")

            actual = actuals.get(account.pk, Decimal("0"))

            # Calculate available based on account type
            available = actual - budgeted if account.account_group.account_type == "income" else budgeted - actual

            rows.append(
                {
                    "category_id": account.pk,
                    "category_name": account.name,
                    "account_group": account.account_group.name,
                    "month": month,
                    "budget_id": budget.id if budget else None,
                    "budgeted": budgeted,
                    "actual": actual,
                    "available": available,
                }
            )

        return rows


class GoalCloseError(ValueError):
    """A goal can't be closed as asked; the message says why and what to do."""


class GoalService:
    """Service class for goal-related calculations and queries."""

    def __init__(self, team):
        self.team = team

    def get_goals_with_progress(self, month=None, include_archived=False, closed=False):
        """
        Goals with their allocated/spent/left annotations as of `month`.

        `closed`: False (default) for open goals only, True for closed ones only,
        None for both.
        """
        qs = Goal.objects.filter(team=self.team)
        if not include_archived:
            qs = qs.filter(is_archived=False)
        if closed is not None:
            qs = qs.filter(closed_at__isnull=not closed)
        return qs.with_progress(month).select_related("account")

    def get_total_saved(self):
        """Get the total amount allocated across all active goals."""
        return GoalAllocation.objects.filter(team=self.team, goal__is_archived=False).aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0")

    def get_goal_summary(self, month, closed=False):
        """Get summary data for the goals page: the goals plus their totals."""
        goals = list(self.get_goals_with_progress(month, closed=closed))
        zero = Decimal("0")
        return {
            "goals": goals,
            "total_target": sum((g.target_amount for g in goals), zero),
            "total_saved": sum((g.allocated for g in goals), zero),
            "total_spent": sum((g.spent for g in goals), zero),
            "total_left": sum((g.left for g in goals), zero),
            "goal_count": len(goals),
        }

    def update_allocation(self, goal, month, amount):
        """Create or update a goal allocation for a specific month."""
        month = month.replace(day=1)
        allocation, created = GoalAllocation.objects.update_or_create(
            team=self.team, goal=goal, month=month, defaults={"amount": amount}
        )
        return allocation

    def add_to_allocation(self, goal, month, amount):
        """Add `amount` (negative to take money out) to the month's allocation. Call inside a transaction."""
        month = month.replace(day=1)
        allocation = GoalAllocation.objects.select_for_update().filter(team=self.team, goal=goal, month=month).first()
        current = allocation.amount if allocation else Decimal("0")
        return self.update_allocation(goal, month, current + amount)

    def left(self, goal, month):
        return Goal.objects.filter(pk=goal.pk).with_progress(month).values_list("left", flat=True).get()

    def month_rows(self, month):
        """
        Pay yourself first: one row per open goal for `month`, for Budget vs Actual.

        - needed: the pace to hit the target date, (target − allocated before
          this month) / months left including this one -- measured from the start
          of the month so assigning doesn't shrink the bar you're filling. None
          with no target date or once funded (`note` says which).
        - assigned: this month's net allocation (the row's "actual").
        - spent: spent from the goal this month, so a month you bought the car
          reads as planned spending rather than a gap.
        """
        zero = Decimal("0")
        month = month.replace(day=1)
        rows = []
        for goal in self.get_goals_with_progress(month):
            before = goal.saved_previous
            needed = None
            note = ""
            if goal.is_complete or (goal.target_amount > 0 and before >= goal.target_amount):
                note = "funded"
            elif not goal.target_date:
                note = "no_target_date"
            else:
                target_month = goal.target_date.replace(day=1)
                months_left = max((target_month.year - month.year) * 12 + target_month.month - month.month + 1, 1)
                needed = ((goal.target_amount - before) / months_left).quantize(Decimal("0.01"))
            assigned = goal.saved_this_month
            pct = None
            if needed:
                pct = float(assigned / needed * 100)
            rows.append(
                {
                    "goal": goal,
                    "needed": needed,
                    "note": note,
                    "assigned": assigned,
                    "spent": goal.spent_this_month,
                    "left": goal.left,
                    "pct": pct,
                    "pct_capped": max(min(pct or (100 if note == "funded" else 0), 100), 0),
                }
            )
        totals = {
            "needed": sum((r["needed"] or zero for r in rows), zero),
            "assigned": sum((r["assigned"] for r in rows), zero),
            "spent": sum((r["spent"] for r in rows), zero),
        }
        return rows, totals

    def spending_lines(self, goal, limit=None):
        """
        The goal account's counted journal lines, newest first: what was spent from
        the goal (a refund is a negative amount). Each: date, payee, memo, counter
        (the other side's account names), amount (dr − cr), entry_id.
        """
        if not goal.account_id:
            return []
        lines = (
            _active_lines()
            .filter(team=self.team, account_id=goal.account_id)
            .select_related("journal_entry", "journal_entry__payee")
            .prefetch_related("journal_entry__lines__account")
            .order_by("-journal_entry__entry_date", "-journal_entry_id", "-pk")
        )
        if limit:
            lines = lines[:limit]
        return [
            {
                "date": line.journal_entry.entry_date,
                "payee": line.journal_entry.payee.name if line.journal_entry.payee else "",
                "memo": line.journal_entry.description,
                "counter": ", ".join(
                    other.account.name for other in line.journal_entry.lines.all() if other.pk != line.pk
                ),
                "amount": line.dr_amount - line.cr_amount,
                "entry_id": line.journal_entry_id,
            }
            for line in lines
        ]

    @transaction.atomic
    def close(self, goal, month, cover=False):
        """
        Close a goal (docs/goals-envelopes-plan.md §4.3).

        Anything left is released back to Unassigned as a negative allocation this
        month. A goal can't close negative: with `cover` the shortfall is covered
        from Unassigned (a positive allocation) first; without it the close is
        refused, since leaving it open (e.g. paying back a loan) is the other choice.

        Returns {"released": Decimal, "covered": Decimal}.
        """
        goal = Goal.objects.select_for_update().get(pk=goal.pk)
        if goal.closed_at is not None:
            raise GoalCloseError(_("This goal is already closed."))
        left = self.left(goal, month)
        released = covered = Decimal("0")
        if left < 0:
            if not cover:
                raise GoalCloseError(
                    _(
                        "%(name)s is %(amount)s. Cover it from your unassigned money to close it, "
                        "or keep it open and keep paying it back."
                    )
                    % {"name": goal.name, "amount": f"−${-left:,.2f}"}
                )
            covered = -left
            self.add_to_allocation(goal, month, covered)
        elif left > 0:
            released = left
            self.add_to_allocation(goal, month, -released)
        goal.closed_at = timezone.now()
        goal.save(update_fields=["closed_at", "updated_at"])
        return {"released": released, "covered": covered}

    @transaction.atomic
    def cover_from_goal(self, goal, category, month, amount):
        """
        Cover an overspent budget row from a goal: take `amount` out of the goal
        (a negative allocation this month) and raise the category's budget for the
        month by the same amount. Unassigned is unchanged -- the money just moves
        from one job to another. This is how buffer goals (emergency fund) get used.
        """
        month = month.replace(day=1)
        self.add_to_allocation(goal, month, -amount)
        budget, _created = Budget.objects.select_for_update().get_or_create(
            team=self.team, category=category, month=month, defaults={"budget_amount": Decimal("0")}
        )
        budget.budget_amount += amount
        budget.save(update_fields=["budget_amount", "updated_at"])
        return budget


def goal_left_by_account(team, month=None):
    """{goal account id: left} for every goal of the team (archived ones included)."""
    return {
        goal.account_id: goal.left
        for goal in Goal.objects.filter(team=team, account__isnull=False).with_progress(month).only("account_id")
    }


def picker_accounts_data(team, month=None):
    """
    Accounts for a category picker, serialized: every account except system ones
    (bookkeeping, never a category), with goal accounts marked and their balance
    ("Car · $600 left").
    """
    from apps.accounts.serializers import PickerAccountSerializer

    accounts = (
        Account.objects.filter(team=team, is_system=False)
        .select_related("account_group", "institution")
        .order_by("name")
    )
    return PickerAccountSerializer(accounts, many=True, context={"goal_left": goal_left_by_account(team, month)}).data


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
            _active_lines()
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

    def get_net_worth_card_data(self, month, categories=None):
        """
        Get all data needed for the NetWorthCard component: the terms of the
        Unassigned sum (see `apps.budget.unassigned`) for `month`.

        Returns:
            dict with keys:
            - net_worth: Total assets minus liabilities
            - income_due: Income budgeted this month and not yet received
            - spend: Money in expense envelopes (unspent budget, rollover included)
            - save: Total allocated to goals
            - available: net_worth + income_due - spend - save (Unassigned)
            - state / label: the Unassigned state and the words for it
        """
        from .unassigned import compute_unassigned

        return self.card_data(compute_unassigned(self.team, month, categories))

    @staticmethod
    def card_data(unassigned):
        """The card dict for an already-computed `Unassigned`."""
        return {
            "net_worth": unassigned.net_worth,
            "income_due": unassigned.income_due,
            "spend": unassigned.envelopes,
            "save": unassigned.goals,
            "available": unassigned.amount,
            "state": unassigned.state,
            "label": unassigned.label,
        }
