"""
The chart of accounts' validation rules, shared by the Django forms (the CBV pages)
and the DRF serializers (the API), so the two cannot drift.

Each check returns the error message, or None when the value is fine; the caller
raises it as its own framework's `ValidationError`.
"""

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from .models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_CHOICES,
    ACCOUNT_TYPE_LIABILITY,
    Account,
)

# Account types that are held at an institution and get a bank feed by default.
FEED_ACCOUNT_TYPES = (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)

ACCOUNT_TYPE_LABELS = dict(ACCOUNT_TYPE_CHOICES)


def unique_name_error(model, book, name, instance=None):
    """
    The model's `unique_together = ["book", "name"]`, as a message.

    `book` is not a form or serializer field, so neither framework's own unique
    check sees the constraint, and a duplicate reached the database as an
    IntegrityError.
    """
    taken = model.objects.filter(book=book, name=name)
    if instance is not None and instance.pk:
        taken = taken.exclude(pk=instance.pk)
    if taken.exists():
        return _("“%(name)s” already exists.") % {"name": name}
    return None


def account_name_error(book, name, account_type, instance=None):
    """An account's name is unique within its account type (not within the book)."""
    taken = Account.objects.filter(book=book, name=name, account_group__account_type=account_type)
    if instance is not None and instance.pk:
        taken = taken.exclude(pk=instance.pk)
    if taken.exists():
        return _("An account named '%(name)s' already exists for account type '%(type)s'.") % {
            "name": name,
            "type": ACCOUNT_TYPE_LABELS.get(account_type, account_type),
        }
    return None


def account_group_type_error(account_group, account_type):
    """The chosen group must be of the chosen account type."""
    if account_type and account_group and account_group.account_type != account_type:
        return _("The selected account group '%(group)s' does not match the selected account type '%(type)s'.") % {
            "group": account_group.name,
            "type": ACCOUNT_TYPE_LABELS.get(account_type, account_type),
        }
    return None


def holds_institution(account_type):
    """Only assets and liabilities are held at an institution."""
    return account_type in FEED_ACCOUNT_TYPES


def default_has_feed(account_type):
    """A new asset or liability account gets a bank feed; nothing else does."""
    return account_type in FEED_ACCOUNT_TYPES


def group_type_locked(group):
    """
    A group's type is its accounts' type: changing it would silently turn, say,
    expense accounts into assets. Locked once the group holds any (and always for
    a system group).
    """
    return bool(group is not None and group.pk and (group.is_system or group.accounts.exists()))


GROUP_TYPE_LOCKED_MESSAGE = gettext_lazy("Fixed while the group has accounts in it.")
