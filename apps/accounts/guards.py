"""
Which accounts may be picked as a transaction's category.

System accounts (the "Reconciliation Adjustments" equity account) are bookkeeping:
opening balances and reconciliation adjustments post to them, a user never does.
Every endpoint that accepts a category calls `assert_category_allowed`, so leaving
them out of the pickers is not the only thing keeping them out.
"""

from django.utils.translation import gettext as _


class SystemCategoryError(ValueError):
    """A system account was sent as a category. A `ValueError`, so the existing 400 paths catch it."""


def assert_category_allowed(account, keep_ids=()):
    """
    Refuse `account` as a category if it is a system account.

    `keep_ids` are account ids the transaction already uses: re-saving an
    existing adjustment untouched must keep working, only newly choosing a system
    account is refused.
    """
    if account is None or not account.is_system or account.pk in set(keep_ids):
        return
    raise SystemCategoryError(
        _("“%(name)s” is a bookkeeping account and can't be used as a category.") % {"name": account.name}
    )
