"""
The goals page's and the goal page's figures, built once for the two callers that
show them: the server-rendered templates (`apps/budget/views.py`) and the goal API
(`apps/budget/api/goals.py`).

Every number comes from `Goal.objects.with_progress(month)` (allocated, spent,
left, this month's share) and `apps.budget.services.goal_plan` (the plan, its
finish month and status); nothing here writes. The builders return model
instances alongside the numbers (`card["goal"]`) for the templates; the API's
serializers read ids and fields off them.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Q

from . import goal_links
from .models import Goal, GoalAccountLink
from .services import GoalService, goal_plan
from .unassigned import compute_unassigned

ZERO = Decimal("0")


def card_progress(goal, saved, this_month):
    """
    (pct, remaining) for a goal card: what its bar shows and what it still asks for.

    A goal with a target measures `saved` against the target. An open-ended goal
    (no target) measures this month's contribution against its monthly plan, so
    the bar fills each month and empties the next.
    """
    if goal.has_target:
        pct = max(min(float(saved / goal.target_amount * 100), 100), 0)
        return pct, max(goal.target_amount - saved, ZERO)
    rate = goal.monthly_contribution or ZERO
    if rate <= 0:
        return 0, ZERO
    return max(min(float(this_month / rate * 100), 100), 0), max(rate - this_month, ZERO)


def goal_with_progress(book, pk, month, **filters):
    """The book's goal `pk` annotated for `month`, or `Goal.DoesNotExist`."""
    return Goal.objects.filter(book=book, **filters).with_progress(month).select_related("account").get(pk=pk)


def goal_numbers(goal, month):
    """(allocated, spent, saved in `month`) for `goal` as of the end of `month`."""
    numbers = (
        Goal.objects.filter(pk=goal.pk).with_progress(month).values("allocated", "spent", "saved_this_month").get()
    )
    return numbers["allocated"], numbers["spent"], numbers["saved_this_month"] or ZERO


def goal_card(goal, month, links=None):
    """
    One goal's card for `month`, from a goal annotated by `with_progress(month)`:
    its numbers, its bar (`pct`, and `spent_pct`, the spent part drawn hatched),
    what it still asks for, and its plan.

    `links` is the open linked accounts (`GoalAccountLink`s, account selected);
    None looks them up.
    """
    saved = goal.allocated or ZERO
    this_month = goal.saved_this_month or ZERO
    if goal.has_target:
        remaining, pct = goal.to_fund, goal.progress_percentage
    else:
        pct, remaining = card_progress(goal, saved, this_month)
    # The spent part of the fill: spending doesn't slide the bar back.
    spent_pct = min(max(float(goal.spent / goal.target_amount * 100), 0), pct) if goal.has_target else 0

    # The plan: a monthly contribution, or the pace to hit the target date. One
    # projection (`goal_plan`) gives the finish month and the status, so the card
    # can't show two dates that disagree.
    plan = goal_plan(goal, month)
    needed_per_month = None
    if plan and plan["rate"] > 0 and (remaining > 0 or not goal.has_target):
        needed_per_month = plan["rate"]

    if links is None:
        links = list(GoalAccountLink.objects.open().filter(goal=goal).select_related("account"))
    return {
        "goal": goal,
        "month": month,
        "saved": saved,
        "remaining": remaining,
        "pct": pct,
        "this_month": this_month,
        "has_target": goal.has_target,
        "plan": plan,
        "needed_per_month": needed_per_month,
        "plan_finish": plan["finish"] if plan else None,
        "plan_late": bool(plan and plan["late"]),
        "rate_for_date": plan["rate_for_date"] if plan else None,
        "plan_status": plan["status"] if plan else None,
        "plan_status_label": plan["status_label"] if plan else None,
        "linked_accounts": [link.account for link in links],
        "links": [link.account.name for link in links],
        "behind_pace": bool(plan and plan["status"] == "behind"),
        "funded": goal.is_funded,
        "spent": goal.spent,
        "spent_this_month": goal.spent_this_month,
        "left": goal.left,
        "cover_amount": max(-goal.left, ZERO),
        "spent_pct": spent_pct,
        "state": goal.state,
        "state_label": goal.state_label,
        "closed": goal.is_closed,
    }


def goal_card_for(book, goal, month):
    """`goal`'s card for `month`, read fresh (after a write)."""
    return goal_card(goal_with_progress(book, goal.pk, month), month)


def goals_page(book, month, closed=False):
    """
    The goals page for `month`: the open goals' cards (with `closed`, the closed and
    archived ones'), their totals, how many are on pace or funded, how many goals are
    closed, and Unassigned.
    """
    summary = GoalService(book).get_goal_summary(month, closed=closed)
    goals = summary["goals"]
    links_by_goal = defaultdict(list)
    for link in GoalAccountLink.objects.open().filter(goal__in=goals).select_related("account"):
        links_by_goal[link.goal_id].append(link)
    cards = [goal_card(goal, month, links_by_goal.get(goal.pk, [])) for goal in goals]
    closed_count = Goal.objects.filter(book=book).filter(Q(closed_at__isnull=False) | Q(is_archived=True)).count()
    return {
        "month": month,
        "closed": closed,
        "cards": cards,
        "summary": {
            "total_target": summary["total_target"],
            "total_saved": summary["total_saved"],
            "total_spent": summary["total_spent"],
            "total_left": summary["total_left"],
            "goal_count": summary["goal_count"],
            "on_track_count": sum(1 for card in cards if card["funded"] or not card["behind_pace"]),
        },
        "closed_count": closed_count,
        "unassigned": compute_unassigned(book, month),
    }


def goal_detail(book, goal, month):
    """
    The goal page for `month`, from a goal annotated by `with_progress(month)`: its
    card, its linked accounts (open and past), whether its past contributions can be
    changed, why it can't be deleted (if it can't), its spending, and how far it is
    from what its accounts hold.
    """
    links = list(goal.account_links.select_related("account").order_by("end_date", "start_date"))
    open_links = [link for link in links if link.is_open]
    service = GoalService(book)
    return {
        **goal_card(goal, month, open_links),
        # The detail page's bar measures against the plan the same way as the card's,
        # but never reads `to_fund` (a funded goal still shows its own progress).
        "progress_pct": card_progress(goal, goal.allocated or ZERO, goal.saved_this_month or ZERO)[0],
        "open_links": open_links,
        "past_links": [link for link in links if not link.is_open],
        # A closed goal's history includes its own release; it stays as written.
        "can_edit_contributions": not goal.is_closed and not goal.is_archived,
        "delete_blocked": service.delete_blocked_reason(goal),
        "spending": service.spending_lines(goal, limit=50),
        "drift": goal_links.link_drift(goal, goal.left),
    }
