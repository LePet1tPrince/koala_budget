"""
Budget buckets: the equity accounts that say what money is for.

Every book has one **Unassigned** bucket (money with no job), and every income
account, expense account and goal account has one paired bucket of its own: an
expense's envelope, an income's expected income, a goal's saved money. A bucket's
role is never stored; it follows from what it is paired with
(`Account.paired_account`), and Unassigned is the one paired with nothing.

This module is the only writer of buckets. A bucket is derived from its category:
it is created with it, renamed with it, archived with it and deleted with it
(`paired_account` cascades). Buckets are `is_system`, so every picker and the
category guard already keep them out of transactions; the ledger guard
(`apps.accounts.guards.assert_budget_entry_rules`) keeps them out of real entries
whatever path writes the line.

Wired up by signals (`apps.budget.signals`) for single saves; the paths that
`bulk_create` accounts (YNAB import, portability) call `sync_book` themselves.
"""

from django.db import transaction
from django.db.models import Q

from apps.accounts.models import (
    ACCOUNT_TYPE_BUDGET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    Account,
    AccountGroup,
)

BUDGET_GROUP_NAME = "Budget"
UNASSIGNED_NAME = "Unassigned"

# Accounts of these types get a bucket, as does any goal's account.
PAIRED_TYPES = (ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_EXPENSE)


def budget_group(book):
    """The book's system group of budget buckets, created if missing."""
    group = AccountGroup.objects.filter(book=book, account_type=ACCOUNT_TYPE_BUDGET, is_system=True).first()
    if group is not None:
        return group
    # Group names are unique per book whatever their type, so a user's own
    # "Budget" group pushes ours to another name.
    name = BUDGET_GROUP_NAME
    suffix = 1
    while AccountGroup.objects.filter(book=book, name=name).exists():
        suffix += 1
        name = f"{BUDGET_GROUP_NAME} ({suffix})"
    return AccountGroup.objects.create(
        book=book,
        name=name,
        account_type=ACCOUNT_TYPE_BUDGET,
        is_system=True,
        description="Budget buckets: what your money is for",
    )


def unassigned_account(book):
    """The book's Unassigned bucket, or None if it hasn't been created."""
    return Account.objects.filter(
        book=book, account_group__account_type=ACCOUNT_TYPE_BUDGET, paired_account__isnull=True
    ).first()


def ensure_unassigned(book):
    """The book's Unassigned bucket, created if missing."""
    account = unassigned_account(book)
    if account is not None:
        return account
    return Account.objects.create(book=book, name=UNASSIGNED_NAME, account_group=budget_group(book), is_system=True)


def _goal_of(account):
    from apps.budget.models import Goal

    return Goal.objects.filter(account=account).only("is_archived").first()


def _wants_bucket(account, goal):
    """Whether `account` is a category that gets a bucket: income, expense, or a goal's account."""
    return goal is not None or account.account_group.account_type in PAIRED_TYPES


def bucket_name(account):
    """
    A bucket is named after its category, but never *as* it: lookups by name
    ("the Groceries account") must keep finding the category alone.
    """
    return f"{account.name} (budget)"


def _bucket_fields(account, goal):
    """What a bucket copies from its category. A goal's bucket is archived with the goal."""
    return {
        "name": bucket_name(account),
        "is_archived": goal.is_archived if goal is not None else account.is_archived,
    }


@transaction.atomic
def sync_bucket(account):
    """
    Bring `account`'s bucket in line with it: create it if missing, copy its name
    and archived state, or delete it if the account no longer takes one (moved to
    an asset group, say). A bucket itself has nothing to sync.
    """
    if account.pk is None or account.account_group.account_type == ACCOUNT_TYPE_BUDGET:
        return
    goal = _goal_of(account)
    bucket = Account.objects.filter(paired_account=account).first()
    if not _wants_bucket(account, goal):
        if bucket is not None:
            bucket.delete()
        return

    fields = _bucket_fields(account, goal)
    if bucket is None:
        ensure_unassigned(account.book)
        Account.objects.create(
            book=account.book,
            account_group=budget_group(account.book),
            is_system=True,
            paired_account=account,
            **fields,
        )
        return
    changed = [name for name, value in fields.items() if getattr(bucket, name) != value]
    if changed:
        for name in changed:
            setattr(bucket, name, fields[name])
        bucket.save(update_fields=changed)


@transaction.atomic
def sync_book(book):
    """
    `sync_bucket` for every account in `book`, in a handful of queries. Idempotent.

    For the paths that `bulk_create` accounts, which send no signals.
    """
    from apps.budget.models import Goal

    ensure_unassigned(book)
    group = budget_group(book)
    goals = {goal.account_id: goal for goal in Goal.objects.filter(book=book, account__isnull=False)}
    categories = (
        Account.objects.filter(book=book)
        .exclude(account_group__account_type=ACCOUNT_TYPE_BUDGET)
        .filter(Q(account_group__account_type__in=PAIRED_TYPES) | Q(pk__in=goals.keys()))
    )
    buckets = {
        bucket.paired_account_id: bucket
        for bucket in Account.objects.filter(book=book, paired_account__isnull=False).budget_buckets()
    }

    to_create, to_update = [], []
    for account in categories:
        fields = _bucket_fields(account, goals.get(account.pk))
        bucket = buckets.pop(account.pk, None)
        if bucket is None:
            to_create.append(Account(book=book, account_group=group, is_system=True, paired_account=account, **fields))
        elif any(getattr(bucket, name) != value for name, value in fields.items()):
            for name, value in fields.items():
                setattr(bucket, name, value)
            to_update.append(bucket)

    Account.objects.bulk_create(to_create)
    Account.objects.bulk_update(to_update, ["name", "is_archived"])
    # What is left paired with an account that no longer takes a bucket. One at a
    # time: `Account.delete()` releases a bucket's budget lines first.
    for bucket in buckets.values():
        bucket.delete()
