"""
What a goal card shows: its bar, what it still asks for, its streak and pace.

`goal_items` builds every card on the goals page in one pass (a query for the
month-by-month amounts, one for linked accounts); `goal_card_progress` is the one
place a card's percentage and "still needed" come from, so the page and the
assign/withdraw responses that animate it agree.
"""

import math
from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta
from django.urls import reverse

from apps.utils.months import months_between

from .models import Goal, GoalAccountLink
from .services import goal_monthly, goal_plan


def goal_streak(saved_months, month):
    """Consecutive months with a positive allocation, counting backwards from the
    selected month (a not-yet-funded selected month doesn't break the streak)."""
    cursor = month
    if cursor not in saved_months:
        cursor -= relativedelta(months=1)
    streak = 0
    while cursor in saved_months:
        streak += 1
        cursor -= relativedelta(months=1)
    return streak


def goal_card_progress(goal, saved, this_month):
    """
    (pct, remaining) for a goal card: what its bar shows and what it still asks for.

    A goal with a target measures `saved` against the target. An open-ended goal
    (no target) measures this month's contribution against its monthly plan, so
    the bar fills each month and empties the next.
    """
    zero = Decimal("0")
    if goal.has_target:
        pct = max(min(float(saved / goal.target_amount * 100), 100), 0)
        return pct, max(goal.target_amount - saved, zero)
    rate = goal.monthly_contribution or zero
    if rate <= 0:
        return 0, zero
    return max(min(float(this_month / rate * 100), 100), 0), max(rate - this_month, zero)


def goal_spending_url(goal, book):
    """The Transactions page filtered to the goal's account (its spending)."""
    if not goal.account_id:
        return None
    base = reverse("journal:transactions_home", args=book.url_args)
    return f"{base}?{urlencode({'f_debit_account': f'a:{goal.account_id}'})}"


def goal_numbers(goal, month):
    """(allocated, spent, saved in `month`) for `goal` as of the end of `month`."""
    numbers = (
        Goal.objects.filter(pk=goal.pk).with_progress(month).values("allocated", "spent", "saved_this_month").get()
    )
    return numbers["allocated"], numbers["spent"], numbers["saved_this_month"] or Decimal("0")


def goal_items(book, goals, month):
    """One dict per goal card for `month`: progress, plan, streak, projection and state."""
    # What each goal was given per month (assigned + from linked accounts);
    # used for streaks and pace.
    amounts_by_goal = {
        goal_id: {m: values["saved"] for m, values in months.items()}
        for goal_id, months in goal_monthly(book, goals).items()
    }

    links_by_goal = defaultdict(list)
    for link in GoalAccountLink.objects.open().filter(goal__in=goals).select_related("account"):
        links_by_goal[link.goal_id].append(link.account.name)

    items = []
    for goal in goals:
        amounts = amounts_by_goal.get(goal.pk, {})
        saved = goal.allocated
        this_month = goal.saved_this_month or Decimal("0")
        if goal.has_target:
            remaining, pct = goal.to_fund, goal.progress_percentage
        else:
            pct, remaining = goal_card_progress(goal, saved, this_month)
        # The spent part of the fill, drawn hatched: spending doesn't slide the bar back.
        spent_pct = min(max(float(goal.spent / goal.target_amount * 100), 0), pct) if goal.has_target else 0

        saved_months = {m for m, amt in amounts.items() if amt > 0}
        streak = goal_streak(saved_months, month)

        # The plan: a monthly contribution, or the pace to hit the target date.
        plan = goal_plan(goal, month)
        months_left = None
        needed_per_month = None
        if plan and plan["rate"] > 0 and (remaining > 0 or not goal.has_target):
            needed_per_month = plan["rate"]
            if plan["finish"]:
                finish = plan["finish"]
                months_left = max(months_between(month, finish), 1)

        # Projection from the recent saving rate (average of the last 3 months)
        recent = [amounts.get(month - relativedelta(months=i), Decimal("0")) for i in range(3)]
        recent_avg = sum(recent) / 3
        projected_date = None
        if goal.has_target and remaining > 0 and recent_avg > 0:
            projected_date = month + relativedelta(months=math.ceil(remaining / recent_avg))
        behind_pace = bool(plan and plan["status"] == "behind")

        items.append(
            {
                "goal": goal,
                "saved": saved,
                "remaining": remaining,
                "pct": pct,
                "this_month": this_month,
                "has_target": goal.has_target,
                "streak": streak,
                "months_left": months_left,
                "needed_per_month": needed_per_month,
                "plan_finish": plan["finish"] if plan else None,
                "plan_status": plan["status"] if plan else None,
                "plan_status_label": plan["status_label"] if plan else None,
                "links": links_by_goal.get(goal.pk, []),
                "projected_date": projected_date,
                "behind_pace": behind_pace,
                "funded": goal.is_funded,
                "spent": goal.spent,
                "spent_this_month": goal.spent_this_month,
                "left": goal.left,
                "cover_amount": max(-goal.left, Decimal("0")),
                "spent_pct": spent_pct,
                "state": goal.state,
                "state_label": goal.state_label,
                "closed": goal.is_closed,
                "spending_url": goal_spending_url(goal, book),
            }
        )
    return items
