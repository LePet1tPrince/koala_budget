"""
Keep each category's budget bucket in step with it (`apps.budget.buckets`), and
its budget lines (`apps.budget.ledger`) on the side its type calls for.
"""

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account
from apps.budget import ledger
from apps.budget.buckets import sync_bucket
from apps.budget.models import Goal

PAIRED_TYPES = {ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_EXPENSE}


@receiver(pre_save, sender=Account, dispatch_uid="budget_remember_account_type")
def remember_account_type(sender, instance, raw=False, **kwargs):
    # A category moved between income and expense must have its budget lines
    # flipped (`sync_bucket_for_account`); the type it had is only known before saving.
    instance._type_before_save = None
    if not raw and instance.pk is not None:
        instance._type_before_save = (
            Account.objects.filter(pk=instance.pk).values_list("account_group__account_type", flat=True).first()
        )


@receiver(post_save, sender=Account, dispatch_uid="budget_sync_bucket_for_account")
def sync_bucket_for_account(sender, instance, raw=False, **kwargs):
    if raw:
        return
    sync_bucket(instance)
    before = getattr(instance, "_type_before_save", None)
    after = instance.account_group.account_type
    if before != after and {before, after} == PAIRED_TYPES:
        ledger.flip_bucket(instance)


@receiver(post_save, sender=Goal, dispatch_uid="budget_sync_bucket_for_goal")
def sync_bucket_for_goal(sender, instance, raw=False, **kwargs):
    # `Goal.save()` creates its account before the goal row exists, so the
    # account's own signal can't tell yet that it is a goal's.
    if not raw and instance.account_id:
        sync_bucket(instance.account)


@receiver(post_delete, sender=Goal, dispatch_uid="budget_release_goal_bucket")
def release_goal_bucket(sender, instance, **kwargs):
    # What the goal was given goes with it: its bucket's budget lines are released
    # and each month rebalanced. The bucket itself goes with the goal's account
    # (`GoalService.delete`).
    if instance.account_id:
        buckets = Account.objects.filter(paired_account_id=instance.account_id)
        ledger.rebalance(ledger.release_bucket_lines(buckets))
