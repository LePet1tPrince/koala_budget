"""
Keep the goal ledger in step (docs/goals-ledger-plan.md).

A saving entry is computed from the month's plan, the lines on the goal's linked
accounts, its links and its outflow setting. Each handler here turns a write to
one of those into a `goal_ledger.request_sync`/`request_rebuild`, so every ORM
write path -- the bank feed, the Transactions page, the journal API, statement
adjustments, onboarding -- keeps goals right with no call of its own. Paths that
skip signals (`bulk_create`, `QuerySet.update`) call `goal_ledger.rebuild_book`.

A line on a linked account matters in two ways: inside a link's range it moves
money into or out of the goal that month, and before a link's start date it is
part of the starting balance that link counts. How much moves depends on the
other lines of its entry, so a write to any line touches every account on the
entry.
"""

from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from apps.journal.models import JournalEntry, JournalLine

from . import goal_ledger
from .models import Goal, GoalAccountLink, GoalAllocation


def _entry_accounts(entry_id):
    return set(JournalLine.objects.filter(journal_entry_id=entry_id).values_list("account_id", flat=True))


def _touch(points):
    """Request a sync for every goal-month that (account id, date) `points` feed."""
    points = {(account_id, day) for account_id, day in points if account_id and day}
    if not points:
        return
    links = list(GoalAccountLink.objects.filter(account_id__in={account_id for account_id, _ in points}))
    for link in links:
        for account_id, day in points:
            if account_id != link.account_id:
                continue
            if link.start_date <= day and (link.end_date is None or day <= link.end_date):
                goal_ledger.request_sync(link.goal_id, day)
            if link.include_starting_balance and day < link.start_date:
                goal_ledger.request_sync(link.goal_id, link.start_date)


# ------------------------------------------------------------------ lines


@receiver(pre_save, sender=JournalLine)
def _line_pre_save(sender, instance, raw=False, **kwargs):
    instance._goal_ledger_before = None
    if raw or instance.pk is None:
        return
    before = JournalLine.objects.filter(pk=instance.pk).values_list("account_id", "journal_entry__entry_date").first()
    instance._goal_ledger_before = before


@receiver(post_save, sender=JournalLine)
def _line_post_save(sender, instance, raw=False, **kwargs):
    if raw:
        return
    entry = instance.journal_entry
    if entry.source == JournalEntry.SOURCE_GOAL:
        return
    points = [(account_id, entry.entry_date) for account_id in _entry_accounts(entry.pk) | {instance.account_id}]
    before = getattr(instance, "_goal_ledger_before", None)
    if before:
        points.append(before)
    _touch(points)


@receiver(pre_delete, sender=JournalLine)
def _line_pre_delete(sender, instance, **kwargs):
    entry = JournalEntry.objects.filter(pk=instance.journal_entry_id).values_list("entry_date", "source").first()
    instance._goal_ledger_before = entry


@receiver(post_delete, sender=JournalLine)
def _line_post_delete(sender, instance, **kwargs):
    before = getattr(instance, "_goal_ledger_before", None)
    if not before or before[1] == JournalEntry.SOURCE_GOAL:
        return
    accounts = _entry_accounts(instance.journal_entry_id) | {instance.account_id}
    _touch([(account_id, before[0]) for account_id in accounts])


# ---------------------------------------------------------------- entries


@receiver(pre_save, sender=JournalEntry)
def _entry_pre_save(sender, instance, raw=False, **kwargs):
    instance._goal_ledger_before = None
    if raw or instance.pk is None or instance.source == JournalEntry.SOURCE_GOAL:
        return
    instance._goal_ledger_before = (
        JournalEntry.objects.filter(pk=instance.pk).values_list("entry_date", "status").first()
    )


@receiver(post_save, sender=JournalEntry)
def _entry_post_save(sender, instance, created=False, raw=False, **kwargs):
    """A re-dated, voided or restored entry moves every linked line on it."""
    before = getattr(instance, "_goal_ledger_before", None)
    if raw or created or not before:
        return
    old_date, old_status = before
    if old_date == instance.entry_date and old_status == instance.status:
        return
    account_ids = set(instance.lines.values_list("account_id", flat=True))
    _touch([(account_id, day) for account_id in account_ids for day in {old_date, instance.entry_date}])


# ------------------------------------------------------------------ plans


@receiver(post_save, sender=GoalAllocation)
def _allocation_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        goal_ledger.request_sync(instance.goal_id, instance.month)


@receiver(post_delete, sender=GoalAllocation)
def _allocation_deleted(sender, instance, **kwargs):
    goal_ledger.request_sync(instance.goal_id, instance.month)


# ------------------------------------------------------------------ links


@receiver(post_save, sender=GoalAccountLink)
def _link_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        goal_ledger.request_rebuild(instance.goal_id)


@receiver(post_delete, sender=GoalAccountLink)
def _link_deleted(sender, instance, **kwargs):
    goal_ledger.request_rebuild(instance.goal_id)


# ------------------------------------------------------------------- goals


@receiver(pre_save, sender=Goal)
def _goal_pre_save(sender, instance, raw=False, **kwargs):
    instance._goal_ledger_before = None
    if raw or instance.pk is None:
        return
    instance._goal_ledger_before = Goal.objects.filter(pk=instance.pk).values_list("outflow", "name").first()


@receiver(post_save, sender=Goal)
def _goal_saved(sender, instance, created=False, raw=False, **kwargs):
    before = getattr(instance, "_goal_ledger_before", None)
    if raw or created or not before:
        return
    old_outflow, old_name = before
    if old_outflow != instance.outflow or old_name != instance.name:
        goal_ledger.request_rebuild(instance.pk)
