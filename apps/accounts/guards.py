"""
Which accounts may be picked as a transaction's category.

Budget buckets (envelopes, expected income, goal buckets, Unassigned) are never a
category: they only appear in budget entries. Every endpoint that accepts a category
calls `assert_category_allowed`, so leaving them out of the pickers is not the only
thing keeping them out.

The system equity account "Reconciliation Adjustments" *is* a category: it is where
an opening balance or a one-off equity adjustment is posted, by hand as well as by
the opening-balance dialog and reconciliation.
"""

from django.utils.translation import gettext as _


class BudgetAccountError(ValueError):
    """A budget bucket in a real transaction, or a category in a budget entry. A `ValueError` for the 400 paths."""


def assert_budget_entry_rules(is_budget_entry, accounts):
    """
    Keep the budget ledger and the real ledger apart.

    A budget bucket (`apps.budget.buckets`) may only appear in a budget entry
    (`JournalEntry.SOURCE_BUDGET`), and a budget entry may only move money between
    buckets. So `Dr Bank / Cr Envelope` is refused whatever writes it, and a budget
    move can never touch a balance that counts in net worth. Goals follow the same
    rule as expenses: a goal's account is a category, its bucket is budget-only.

    `accounts` are `Account`s with `account_group` loaded (or loadable).
    """
    from apps.accounts.models import ACCOUNT_TYPE_BUDGET

    for account in accounts:
        is_bucket = account.account_group.account_type == ACCOUNT_TYPE_BUDGET
        if is_bucket and not is_budget_entry:
            raise BudgetAccountError(
                _("“%(name)s” is a budget account and can't be used in a transaction.") % {"name": account.name}
            )
        if is_budget_entry and not is_bucket:
            raise BudgetAccountError(
                _("“%(name)s” isn't a budget account, so it can't be part of a budget entry.") % {"name": account.name}
            )


class SystemCategoryError(ValueError):
    """A budget bucket was sent as a category. A `ValueError`, so the existing 400 paths catch it."""


def assert_category_allowed(account, keep_ids=()):
    """
    Refuse `account` as a category if it is a budget bucket.

    `keep_ids` are account ids the transaction already uses: re-saving a
    transaction untouched must keep working, only newly choosing one is refused.
    """
    if account is None or not account.is_budget_bucket or account.pk in set(keep_ids):
        return
    raise SystemCategoryError(
        _("“%(name)s” is a budget account and can't be used as a category.") % {"name": account.name}
    )
