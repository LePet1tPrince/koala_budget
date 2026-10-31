"""
Moving money into and out of a goal from its card: quick-assign and withdraw.

Both run under the book's budget lock, record the change against the selected
month's allocation (which may go negative -- past months' contributions are never
rewritten), and answer the before/after numbers the goals page animates. A
refusal is a `GoalFundsError` carrying the sentence the page shows; nothing is
written.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from apps.utils.amounts import json_amount

from . import ledger as budget_ledger
from .forms import MAX_BUDGET_AMOUNT
from .goal_cards import goal_card_progress, goal_numbers
from .services import GoalService, NetWorthService


class GoalFundsError(ValueError):
    """An assign or withdraw refused; the message is what the page shows."""


def _positive_amount(raw_amount):
    amount = json_amount(raw_amount, limit=MAX_BUDGET_AMOUNT)
    if amount is None or amount <= 0:
        raise GoalFundsError("Invalid amount.")
    return amount


def assign(book, goal, month, raw_amount=None):
    """
    Add money to `goal` for `month`: `raw_amount`, or with None everything
    Unassigned holds, capped at what the goal still needs. Answers
    `(amount, payload)` -- the payload being the page's JSON.
    """
    if goal.is_archived or goal.is_closed:
        raise GoalFundsError("This goal is no longer active.")
    # A funded goal stops asking for money (no quick-assign), but an explicit
    # amount still goes in -- that's how an overspent goal is covered or paid back.
    if goal.is_complete and raw_amount is None:
        raise GoalFundsError("This goal is already fully funded.")

    with transaction.atomic():
        budget_ledger.lock(book)
        month_amount = budget_ledger.goal_allocation(book, goal, month)
        old_saved, spent, saved_month = goal_numbers(goal, month)
        _, remaining = goal_card_progress(goal, old_saved, saved_month)
        available = NetWorthService(book).get_net_worth_card_data(month)["available"]

        if raw_amount is None:
            if goal.has_target and remaining <= 0:
                raise GoalFundsError("This goal is already fully funded.")
            # An open-ended goal asks for this month's contribution; once that's
            # in, "add all available" means exactly that.
            amount = min(available, remaining) if remaining > 0 else available
            if amount <= 0:
                raise GoalFundsError("No available funds to assign right now.")
        else:
            amount = _positive_amount(raw_amount)

        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        GoalService(book).update_allocation(goal, month, month_amount + amount)

    new_saved = old_saved + amount
    old_pct, _ = goal_card_progress(goal, old_saved, saved_month)
    new_pct, new_remaining = goal_card_progress(goal, new_saved, saved_month + amount)
    return amount, {
        "goal_id": goal.pk,
        "goal_name": goal.name,
        "assigned": float(amount),
        "old_saved": float(old_saved),
        "new_saved": float(new_saved),
        "old_pct": old_pct,
        "new_pct": new_pct,
        "remaining": float(new_remaining),
        "this_month": float(month_amount + amount),
        "new_available": float(available - amount),
        "completed": goal.has_target and new_saved >= goal.target_amount,
        "open_ended": not goal.has_target,
        "spent": float(spent),
        "left": float(new_saved - spent),
    }


def withdraw(book, goal, month, raw_amount=None):
    """
    Take money back out of `goal` in `month`: `raw_amount`, or with None
    everything it has left. Money already spent from the goal can't be
    withdrawn: the cap is left (allocated − spent), not allocated. Funded goals
    stay withdrawable -- that's how a finished goal is cashed out. Answers
    `(amount, payload)`.
    """
    if goal.is_archived:
        raise GoalFundsError("This goal is archived.")
    if goal.is_closed:
        raise GoalFundsError("This goal is closed.")

    with transaction.atomic():
        budget_ledger.lock(book)
        month_amount = budget_ledger.goal_allocation(book, goal, month)
        old_saved, spent, saved_month = goal_numbers(goal, month)
        left = old_saved - spent
        available = NetWorthService(book).get_net_worth_card_data(month)["available"]

        if left <= 0:
            raise GoalFundsError("Nothing left in this goal to withdraw.")

        if raw_amount is None:
            amount = left
        else:
            amount = _positive_amount(raw_amount)
            if amount > left:
                raise GoalFundsError(f"This goal only has ${left:,.2f} left.")

        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        GoalService(book).update_allocation(goal, month, month_amount - amount)

    new_saved = old_saved - amount
    old_pct, _ = goal_card_progress(goal, old_saved, saved_month)
    new_pct, new_remaining = goal_card_progress(goal, new_saved, saved_month - amount)
    return amount, {
        "goal_id": goal.pk,
        "goal_name": goal.name,
        "withdrawn": float(amount),
        "old_saved": float(old_saved),
        "new_saved": float(new_saved),
        "old_pct": old_pct,
        "new_pct": new_pct,
        "remaining": float(new_remaining),
        "this_month": float(month_amount - amount),
        "new_available": float(available + amount),
        "funded": goal.has_target and new_saved >= goal.target_amount,
        "open_ended": not goal.has_target,
        "spent": float(spent),
        "left": float(new_saved - spent),
    }
