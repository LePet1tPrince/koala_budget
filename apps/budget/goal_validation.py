"""
The rules a goal's own fields follow, in one place for the two callers that
enforce them: `GoalForm` (the server-rendered goal form) and the goal API's
serializer (`apps/budget/api/goal_serializers.py`).

Each check raises Django's `ValidationError` (a form turns it into a field error;
DRF's `validate_<field>` does the same), or, for the checks that span fields,
returns `(field, message, code)` triples -- `field` None for an error about the
goal as a whole -- for the caller to attach in its own way.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from .models import Goal

NO_PLAN = "no_plan"
DATE_NEEDS_TARGET = "date_needs_target"


class GoalNameClash(ValidationError):
    """The name is taken in the book; `goal` is the goal that has it, so a page can link to it
    (deleting that goal is the other way to free the name)."""

    def __init__(self, message, goal):
        super().__init__(message, code="name_clash")
        self.goal = goal


def clean_goal_name(book, name, *, exclude_pk=None):
    """A goal's name, stripped: unique within its book, archived and closed goals included."""
    name = (name or "").strip()
    if book is None:
        return name
    taken = Goal.objects.filter(book=book, name=name).exclude(pk=exclude_pk).first()
    if taken is None:
        return name
    if taken.is_archived:
        message = _("You have an archived goal named “%(name)s”. Pick another name, or delete that goal.")
    elif taken.is_closed:
        message = _("You have a closed goal named “%(name)s”. Pick another name, or delete that goal.")
    else:
        message = _("You already have a goal named “%(name)s”. Pick another name.")
    raise GoalNameClash(message % {"name": name}, taken)


def clean_target_amount(value):
    """Blank is 0: an open-ended goal, planned by its monthly contribution alone."""
    return value or Decimal("0")


def clean_outflow(value, instance=None):
    """Only meaningful with a linked account; without a choice the goal keeps what it has."""
    return value or (instance.outflow if instance is not None else None) or Goal.OUTFLOW_WITHDRAW


def goal_plan_errors(target_amount, monthly_contribution, target_date):
    """
    What is wrong with a goal's plan, as `(field, message, code)` triples:

    - no target and no monthly contribution: nothing to plan by (the goal as a whole);
    - a target date without a target amount: there is nothing to reach by it.
    """
    errors = []
    if not target_amount and not monthly_contribution:
        errors.append((None, _("Set a target amount, a monthly contribution, or both."), NO_PLAN))
    if not target_amount and target_date:
        errors.append(("target_date", _("A target date needs a target amount."), DATE_NEEDS_TARGET))
    return errors
