"""Keep every category's budget bucket in step with it (`apps.budget.buckets`)."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import Account
from apps.budget.buckets import sync_bucket
from apps.budget.models import Goal


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
