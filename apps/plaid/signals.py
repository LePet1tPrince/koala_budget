"""
Removing an item at Plaid whenever it is deleted here.

A PlaidItem is deleted by more than the Disconnect button: wiping a book before
an import replaces it (`portability.services.wipe.wipe_book`), deleting a set of
books, and deleting a user account all cascade through it. Each used to leave
the item alive at Plaid -- still billed, still sending webhooks for an item this
app no longer knows. Hooking the delete itself covers every path, present and
future.

The call happens after the deleting transaction commits: a rolled-back delete
must not have disconnected the bank.
"""

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import PlaidItem


@receiver(post_delete, sender=PlaidItem)
def remove_deleted_item_at_plaid(sender, instance, **kwargs):
    from .linking import remove_at_plaid

    access_token = instance.access_token
    transaction.on_commit(lambda: remove_at_plaid(access_token))
