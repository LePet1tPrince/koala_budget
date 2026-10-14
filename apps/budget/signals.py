"""
Keep each category's budget bucket in step with it (`apps.budget.buckets`), and
each month's budget entry in step with the month's rows (`apps.budget.ledger`).
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.accounts.models import Account
from apps.budget import ledger
from apps.budget.buckets import sync_bucket
from apps.budget.models import Budget, Goal, GoalAllocation


@receiver(post_save, sender=Account, dispatch_uid="budget_sync_bucket_for_account")
def sync_bucket_for_account(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_bucket(instance)


@receiver(post_save, sender=Goal, dispatch_uid="budget_sync_bucket_for_goal")
def sync_bucket_for_goal(sender, instance, raw=False, **kwargs):
    # `Goal.save()` creates its account before the goal row exists, so the
    # account's own signal can't tell yet that it is a goal's.
    if not raw and instance.account_id:
        sync_bucket(instance.account)


@receiver(post_save, sender=Budget, dispatch_uid="budget_sync_entry_for_budget")
@receiver(post_save, sender=GoalAllocation, dispatch_uid="budget_sync_entry_for_allocation")
def sync_entry_for_row(sender, instance, raw=False, **kwargs):
    if not raw:
        ledger.sync_month(instance.book, instance.month)


@receiver(post_delete, sender=Goal, dispatch_uid="budget_release_goal_bucket")
def release_goal_bucket(sender, instance, **kwargs):
    # The goal's allocations went with it (cascade, deleted first), so its bucket's
    # lines no longer have rows behind them. The bucket itself goes with the goal's
    # account (`GoalService.delete`).
    if instance.account_id:
        buckets = Account.objects.filter(paired_account_id=instance.account_id)
        ledger.resync(ledger.release_bucket_lines(buckets))
