"""
One sync per Plaid item at a time.

A webhook, the hourly catch-up and the Refresh button can all ask for a sync of
the same item. Two running together would read the same cursor, fetch the same
pages and race to apply them -- the per-transaction dedupe catches most of it,
but a settling pending transaction can be claimed twice, and the loser's cursor
can overwrite the winner's.

The lock is a timestamp on the item (`sync_lock_until`) claimed with one
conditional UPDATE, so it needs nothing but the database and works across every
worker. It expires, so a worker killed mid-sync can't hold an item forever.

A sync asked for while one runs is not dropped: it sets `sync_requested`, and
the running sync goes round again when it finishes. That matters for webhooks --
SYNC_UPDATES_AVAILABLE arriving mid-sync means there is data the running sync
may already have read past. Release clears the lock only while no rerun is
requested, in the same UPDATE, so a request can't slip between the check and
the release.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import PlaidItem

#: Comfortably longer than a sync takes; a sync refreshes it each time it goes round.
LOCK_TTL = timedelta(minutes=15)


def claim(item_id) -> bool:
    """Take the item's lock; False when another sync holds it (or the item is gone)."""
    now = timezone.now()
    return (
        PlaidItem.objects.filter(pk=item_id)
        .filter(Q(sync_lock_until__isnull=True) | Q(sync_lock_until__lt=now))
        .update(sync_lock_until=now + LOCK_TTL, sync_requested=False)
        == 1
    )


def request_rerun(item_id) -> bool:
    """Ask the sync holding the lock to go again; False when no sync holds it."""
    return PlaidItem.objects.filter(pk=item_id, sync_lock_until__gte=timezone.now()).update(sync_requested=True) == 1


def release(item_id) -> bool:
    """
    Let go of the lock -- unless a rerun was asked for, in which case the lock is
    kept (refreshed), the request is consumed and this returns False: go again.
    """
    if PlaidItem.objects.filter(pk=item_id, sync_requested=False).update(sync_lock_until=None) == 1:
        return True
    PlaidItem.objects.filter(pk=item_id).update(sync_requested=False, sync_lock_until=timezone.now() + LOCK_TTL)
    return False


def force_release(item_id):
    """Drop the lock whatever is pending (after a failed sync: the next one starts fresh)."""
    PlaidItem.objects.filter(pk=item_id).update(sync_lock_until=None, sync_requested=False)
