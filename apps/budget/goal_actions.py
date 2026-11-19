"""
What the goals page, the goal page and the goal API do to a goal, once for each:
assign and withdraw funds, save a goal with its linked accounts, archive it, find a
past contribution, and the audit events these write.

Every allocation goes through `GoalService` / `apps.budget.ledger` (CLAUDE.md
single-writer rule); every link change through `apps.budget.goal_links.set_links`.
A refusal is a `GoalFundsError` (or the service's own `GoalCloseError`,
`GoalAllocationError`, `GoalDeleteError`, `LinkError`) whose message is shown as is.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.web.templatetags.currency_tags import currency

from . import goal_links
from . import ledger as budget_ledger
from .goal_figures import card_progress, goal_numbers
from .models import Goal
from .services import GoalService
from .unassigned import compute_unassigned

CENT = Decimal("0.01")


class GoalFundsError(ValueError):
    """Funds can't be assigned to (or withdrawn from) a goal as asked; the message says why."""


def assign_funds(book, goal, month, amount=None):
    """
    Add `amount` to `goal`'s allocation for `month` (positive; added to what the month
    has). Without an amount, assign everything Unassigned has, capped at what the goal
    still asks for -- an open-ended goal asks for this month's contribution, and once
    that is in, "everything" means exactly that.

    A funded goal stops asking (no quick-assign), but an explicit amount still goes in:
    that is how an overspent goal is covered or paid back.

    Returns {"amount", "before": {"allocated", "pct"}, "quick"}.
    """
    if goal.is_archived or goal.is_closed:
        raise GoalFundsError(_("This goal is no longer active."))
    if goal.is_complete and amount is None:
        raise GoalFundsError(_("This goal is already fully funded."))

    with transaction.atomic():
        budget_ledger.lock(book)
        month_amount = budget_ledger.goal_allocation(book, goal, month)
        old_saved, _spent, saved_month = goal_numbers(goal, month)
        old_pct, remaining = card_progress(goal, old_saved, saved_month)
        quick = amount is None
        if quick:
            if goal.has_target and remaining <= 0:
                raise GoalFundsError(_("This goal is already fully funded."))
            available = compute_unassigned(book, month).amount
            amount = min(available, remaining) if remaining > 0 else available
            if amount <= 0:
                raise GoalFundsError(_("No available funds to assign right now."))
        amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        GoalService(book).update_allocation(goal, month, month_amount + amount)
    return {"amount": amount, "before": {"allocated": old_saved, "pct": old_pct}, "quick": quick}


def withdraw_funds(book, goal, month, amount=None):
    """
    Take `amount` back out of `goal` (positive), recorded against `month`'s allocation
    (which may go negative), so past months' contribution history is never rewritten.
    Without an amount, withdraw everything the goal has left. Money already spent from
    the goal can't be withdrawn: the cap is left (allocated − spent), not allocated.
    A funded goal stays withdrawable -- that is how a finished goal is cashed out.

    Returns {"amount", "before": {"allocated", "pct"}, "quick"}.
    """
    if goal.is_archived:
        raise GoalFundsError(_("This goal is archived."))
    if goal.is_closed:
        raise GoalFundsError(_("This goal is closed."))

    with transaction.atomic():
        budget_ledger.lock(book)
        month_amount = budget_ledger.goal_allocation(book, goal, month)
        old_saved, spent, saved_month = goal_numbers(goal, month)
        old_pct, _remaining = card_progress(goal, old_saved, saved_month)
        left = old_saved - spent
        if left <= 0:
            raise GoalFundsError(_("Nothing left in this goal to withdraw."))
        quick = amount is None
        if quick:
            amount = left
        elif amount > left:
            raise GoalFundsError(_("This goal only has %(left)s left.") % {"left": currency(left)})
        amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        GoalService(book).update_allocation(goal, month, month_amount - amount)
    return {"amount": amount, "before": {"allocated": old_saved, "pct": old_pct}, "quick": quick}


def log_funds(request, goal, month, result, *, withdrawn=False):
    """The audit event for an `assign_funds` / `withdraw_funds` result."""
    log_event(
        AuditEvent.GOAL_FUNDS_WITHDRAWN if withdrawn else AuditEvent.GOAL_FUNDS_ASSIGNED,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "month": month.isoformat(),
            "amount": str(result["amount"]),
            ("withdraw_all" if withdrawn else "quick_assign"): result["quick"],
        },
    )


def save_goal(goal, rows=None):
    """
    Save `goal` (new or not; its `book` set) and, unless `rows` is None, make its open
    links exactly `rows` (`goal_links.LinkRow`s) -- one transaction: a refused link
    saves nothing. Returns the `LinkChanges` (empty without `rows`).

    A new goal's pk is cleared again when a link is refused, so the caller can
    re-render it as unsaved.
    """
    is_new = goal.pk is None
    try:
        with transaction.atomic():
            goal.save()
            if rows is None:
                return goal_links.LinkChanges(linked=[], updated=[], unlinked=[])
            return goal_links.set_links(goal, rows)
    except goal_links.LinkError:
        if is_new:
            # The rolled-back save left a pk (and a backing account) on the instance.
            goal.pk = None
            goal.account = None
        raise


def mark_funded(goal):
    """Mark a goal funded: it stops asking for money but keeps its claim."""
    if not goal.is_complete:
        goal.is_complete = True
        goal.save(update_fields=["is_complete", "updated_at"])


def archive_goal(book, goal, month):
    """
    Archive a goal: it leaves every list. An open goal is closed first, which releases
    anything left in it -- a hidden goal must not keep holding money. Returns the close
    result ({"released", "covered"}), or None for a goal that was already closed.
    Raises `GoalCloseError` (nothing archived) when it can't close.
    """
    result = None
    with transaction.atomic():
        if not goal.is_closed:
            result = GoalService(book).close(goal, month)
            goal.refresh_from_db()
        goal.is_archived = True
        goal.save()
    return result


def contribution_line(book, line_pk):
    """
    A past manual contribution, named by its line on the month's budget entry (the goal
    bucket's), and its goal: (line, goal). Money from linked accounts has no such line,
    so it can't be reached here. Another book's line (or not a contribution) is a 404.
    """
    from apps.journal.models import JournalEntry, JournalLine

    line = get_object_or_404(
        JournalLine.objects.filter(
            book=book,
            journal_entry__source=JournalEntry.SOURCE_BUDGET,
            account__paired_account__goal__isnull=False,
        ).select_related("journal_entry", "account"),
        pk=line_pk,
    )
    goal = get_object_or_404(Goal.objects.filter(book=book), account_id=line.account.paired_account_id)
    return line, goal


def log_contribution_edit(request, goal, month, old, amount):
    log_event(
        AuditEvent.GOAL_CONTRIBUTION_EDITED,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "month": month.isoformat(),
            "from": str(old),
            "to": str(amount),
            "undo": amount == 0,
        },
    )


def log_link_changes(request, goal, changes, outflow_before=None):
    """Audit what saving a goal did to its linked accounts and outflow setting."""
    for link in changes.linked:
        log_event(
            AuditEvent.GOAL_ACCOUNT_LINKED,
            request=request,
            metadata={
                "goal_id": goal.pk,
                "goal_name": goal.name,
                "account_id": link.account_id,
                "account_name": link.account.name,
                "start_date": link.start_date.isoformat(),
                "include_starting_balance": link.include_starting_balance,
            },
        )
    for link in changes.updated:
        log_event(
            AuditEvent.GOAL_ACCOUNT_LINKED,
            request=request,
            metadata={
                "goal_id": goal.pk,
                "goal_name": goal.name,
                "account_id": link.account_id,
                "account_name": link.account.name,
                "start_date": link.start_date.isoformat(),
                "include_starting_balance": link.include_starting_balance,
                "updated": True,
            },
        )
    for link in changes.unlinked:
        log_unlinked(request, goal, link)
    if outflow_before is not None and outflow_before != goal.outflow:
        log_event(
            AuditEvent.GOAL_OUTFLOW_CHANGED,
            request=request,
            metadata={"goal_id": goal.pk, "goal_name": goal.name, "from": outflow_before, "to": goal.outflow},
        )


def log_unlinked(request, goal, link):
    log_event(
        AuditEvent.GOAL_ACCOUNT_UNLINKED,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "account_id": link.account_id,
            "account_name": link.account.name,
            "end_date": link.end_date.isoformat() if link.end_date else None,
        },
    )


def unlink_account(request, link):
    """Stop an account feeding its goal (what it already brought in stays), and audit it.
    Raises `LinkError` for a link that already ended."""
    goal = link.goal
    goal_links.unlink(link)
    if link.pk:
        link.refresh_from_db()
    log_unlinked(request, goal, link)


def log_goal_closed(request, goal, result, via):
    log_event(
        AuditEvent.GOAL_CLOSED,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "released": str(result["released"]),
            "covered": str(result["covered"]),
            "via": via,
        },
    )
