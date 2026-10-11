"""
The goal ledger: the journal entries that book what each goal saved
(docs/goals-ledger-plan.md).

A goal's fund (its equity account) is credited once a month by a saving entry,
Dr "Saving: X" / Cr fund, for

    max(plan, moved in) − moved out + adjustment

where `plan` and `adjustment` come from the month's `GoalAllocation` (a legacy
negative plan reads as an adjustment) and the moves from the goal's linked
accounts (`apps.budget.linked`). Moving money into a linked account counts
towards the plan, never on top of it. A linked account that counts the
balance already in it gets one more entry, Dr the system equity offset / Cr
fund, which never reaches the income statement. The fund's balance is then the
goal's `left`.

This module is the only writer of those entries. Everything that moves an input
-- a plan, a linked account's line, a link, the goal's outflow setting -- asks
for a sync through `request_sync`/`request_rebuild`, which `apps.budget.ledger_signals`
does on every ORM write. Paths that skip the ORM's signals (bulk imports) call
`rebuild_book` themselves. Every sync recomputes from scratch, so running one
twice changes nothing.
"""

import threading
from contextlib import contextmanager
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import Goal, GoalAccountLink, GoalAllocation, GoalSaving, create_saving_account, month_after

ZERO = Decimal("0")

_state = threading.local()


def saving_amount(planned, moved_in, moved_out, adjustment=ZERO):
    """A month's saving: the larger of the plan and what arrived, less what left, plus by-hand moves."""
    planned = planned or ZERO
    adjustment = (adjustment or ZERO) + min(planned, ZERO)
    return max(planned, moved_in, ZERO) - moved_out + adjustment


# ---------------------------------------------------------------- requests


def _pending():
    return getattr(_state, "pending", None)


def _suspended():
    return getattr(_state, "suspended", 0) > 0


@contextmanager
def batch():
    """Collect sync requests and run each once, when the outermost `batch()` exits."""
    outermost = _pending() is None
    if outermost:
        _state.pending = {"months": set(), "goals": set()}
    try:
        yield
    finally:
        if outermost:
            pending = _state.pending
            _state.pending = None
            _flush(pending)


@contextmanager
def suspended():
    """Ignore sync requests: for deleting a goal or a book, where there is nothing to keep."""
    _state.suspended = getattr(_state, "suspended", 0) + 1
    try:
        yield
    finally:
        _state.suspended -= 1


def request_sync(goal_id, month):
    """Bring `goal_id`'s saving entries for `month` in line with their inputs."""
    if _suspended() or goal_id is None:
        return
    month = month.replace(day=1)
    pending = _pending()
    if pending is not None:
        pending["months"].add((goal_id, month))
        return
    _flush({"months": {(goal_id, month)}, "goals": set()})


def request_rebuild(goal_id):
    """Bring every saving entry of `goal_id` in line: after a link or outflow change."""
    if _suspended() or goal_id is None:
        return
    pending = _pending()
    if pending is not None:
        pending["goals"].add(goal_id)
        return
    _flush({"months": set(), "goals": {goal_id}})


def _flush(pending):
    goal_ids = {goal_id for goal_id, _ in pending["months"]} | pending["goals"]
    if not goal_ids:
        return
    goals = {goal.pk: goal for goal in Goal.objects.filter(pk__in=goal_ids).select_related("book")}
    with transaction.atomic():
        for goal_id in pending["goals"]:
            if goal_id in goals:
                rebuild_goal(goals[goal_id])
        for goal_id, month in sorted(pending["months"], key=lambda key: (key[0], key[1])):
            if goal_id in goals and goal_id not in pending["goals"]:
                sync_goal_month(goals[goal_id], month)


# ------------------------------------------------------------------ syncing


def _flows(goal, start=None, end=None):
    from .linked import monthly_linked

    return monthly_linked([goal.pk], start, end).get(goal.pk, {})


def sync_goal_month(goal, month):
    """Rewrite `goal`'s saving entry for `month`, and the starting entries of links starting in it."""
    month = month.replace(day=1)
    end = month_after(month)
    plan = GoalAllocation.objects.filter(goal=goal, month=month).aggregate(
        amount=Sum("amount"), adjustment=Sum("adjustment")
    )
    flows = _flows(goal, month, end).get(month, {})
    amount = saving_amount(plan["amount"], flows.get("in", ZERO), flows.get("out", ZERO), plan["adjustment"])
    _write_saving(goal, month, amount)
    _sync_starting(goal, GoalAccountLink.objects.filter(goal=goal, start_date__gte=month, start_date__lt=end))


def rebuild_goal(goal):
    """Rewrite every saving entry of `goal` from its plan and its linked accounts."""
    flows = _flows(goal)
    planned = {
        row["month"]: row
        for row in GoalAllocation.objects.filter(goal=goal)
        .values("month")
        .annotate(amount=Sum("amount"), adjustment=Sum("adjustment"))
    }
    existing = set(GoalSaving.objects.filter(goal=goal, kind=GoalSaving.KIND_SAVING).values_list("month", flat=True))
    for month in sorted(set(planned) | set(flows) | existing):
        cell = flows.get(month, {})
        plan = planned.get(month, {})
        _write_saving(
            goal,
            month,
            saving_amount(plan.get("amount"), cell.get("in", ZERO), cell.get("out", ZERO), plan.get("adjustment")),
        )
    _sync_starting(goal, GoalAccountLink.objects.filter(goal=goal))
    # Starting entries whose link is gone.
    _delete_entries(GoalSaving.objects.filter(goal=goal, kind=GoalSaving.KIND_STARTING, link__isnull=True))


def rebuild_book(book):
    """Rewrite every goal's saving entries in `book`: after an import that bypassed the ORM's signals."""
    with transaction.atomic():
        for goal in Goal.objects.filter(book=book).select_related("book"):
            rebuild_goal(goal)


def delete_goal_entries(goal):
    """Remove every entry the ledger wrote for `goal`, before the goal itself is deleted."""
    _delete_entries(GoalSaving.objects.filter(goal=goal))


# ------------------------------------------------------------------ writing


def _delete_entries(savings):
    from apps.journal.models import JournalEntry

    entry_ids = list(savings.values_list("entry_id", flat=True))
    if entry_ids:
        JournalEntry.objects.filter(pk__in=entry_ids).delete()


def _sync_starting(goal, links):
    from .linked import starting_balances

    links = list(links)
    if not links:
        return
    amounts = {link.pk: link.amount for link in starting_balances().filter(pk__in=[link.pk for link in links])}
    for link in links:
        amount = amounts.get(link.pk, ZERO) if link.include_starting_balance else ZERO
        _write_starting(goal, link, amount)


def _saving_account(goal):
    if goal.saving_account_id is None:
        goal.saving_account = create_saving_account(goal)
        Goal.objects.filter(pk=goal.pk).update(saving_account=goal.saving_account)
    return goal.saving_account


def _write_saving(goal, month, amount):
    row = GoalSaving.objects.filter(goal=goal, kind=GoalSaving.KIND_SAVING, month=month).select_related("entry")
    _write(
        goal,
        row.first(),
        amount,
        month=month,
        debit_account=_saving_account(goal) if amount else None,
        description=f"Saving for {goal.name}",
        kind=GoalSaving.KIND_SAVING,
    )


def _write_starting(goal, link, amount):
    from apps.reconciliation.services.adjustment import offset_account

    month = link.start_date.replace(day=1)
    row = GoalSaving.objects.filter(kind=GoalSaving.KIND_STARTING, link=link).select_related("entry").first()
    _write(
        goal,
        row,
        amount,
        month=month,
        debit_account=offset_account(goal.book) if amount else None,
        description=f"{goal.name}: balance already in {link.account.name}",
        kind=GoalSaving.KIND_STARTING,
        link=link,
    )


def _write(goal, row, amount, *, month, debit_account, description, kind, link=None):
    """
    Make `row`'s entry book `amount` into `goal`'s fund, against `debit_account`.

    Zero removes the entry. Lines are changed in place, so the audit trail reads
    as an amount change rather than a delete and a create.
    """
    from apps.journal.models import JournalEntry, JournalLine

    if not amount:
        if row is not None:
            row.entry.delete()
        return

    fund_dr, fund_cr = (ZERO, amount) if amount > 0 else (-amount, ZERO)
    wanted = {goal.account_id: (fund_dr, fund_cr), debit_account.pk: (fund_cr, fund_dr)}

    if row is None:
        entry = JournalEntry.objects.create(
            book=goal.book,
            entry_date=month,
            description=description,
            source=JournalEntry.SOURCE_GOAL,
            status=JournalEntry.STATUS_POSTED,
        )
        for account_id, (dr, cr) in wanted.items():
            JournalLine.objects.create(
                book=goal.book, journal_entry=entry, account_id=account_id, dr_amount=dr, cr_amount=cr
            )
        GoalSaving.objects.create(book=goal.book, goal=goal, month=month, kind=kind, link=link, entry=entry)
        return

    entry = row.entry
    if (entry.entry_date, entry.description, entry.status) != (month, description, JournalEntry.STATUS_POSTED):
        entry.entry_date = month
        entry.description = description
        entry.status = JournalEntry.STATUS_POSTED
        entry.save()
    if row.month != month:
        row.month = month
        row.save(update_fields=["month", "updated_at"])

    lines = {line.account_id: line for line in entry.lines.all()}
    for account_id, line in lines.items():
        if account_id not in wanted:
            line.delete()
    for account_id, (dr, cr) in wanted.items():
        line = lines.get(account_id)
        if line is None:
            JournalLine.objects.create(
                book=goal.book, journal_entry=entry, account_id=account_id, dr_amount=dr, cr_amount=cr
            )
        elif (line.dr_amount, line.cr_amount) != (dr, cr):
            line.dr_amount, line.cr_amount = dr, cr
            line.save()
