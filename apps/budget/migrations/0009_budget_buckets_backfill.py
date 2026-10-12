"""
Give every existing book its budget buckets: an Unassigned account plus one
bucket per income account, expense account and goal account
(`apps.budget.buckets`). Nothing posts to a bucket yet, so this moves no balance.

A frozen copy of `buckets.sync_book`, since a migration must not import code
that reads today's models. Reverse deletes the buckets and their group.
"""

from django.db import migrations
from django.db.models import Q

BUDGET = "budget"
PAIRED_TYPES = ("income", "expense")
GROUP_NAME = "Budget"


def _group(AccountGroup, book_id):
    group = AccountGroup.objects.filter(book_id=book_id, account_type=BUDGET, is_system=True).first()
    if group is not None:
        return group
    name, suffix = GROUP_NAME, 1
    while AccountGroup.objects.filter(book_id=book_id, name=name).exists():
        suffix += 1
        name = f"{GROUP_NAME} ({suffix})"
    return AccountGroup.objects.create(
        book_id=book_id,
        name=name,
        account_type=BUDGET,
        is_system=True,
        description="Budget buckets: what your money is for",
    )


def backfill(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    AccountGroup = apps.get_model("accounts", "AccountGroup")
    Goal = apps.get_model("budget", "Goal")

    goal_archived = dict(Goal.objects.filter(account__isnull=False).values_list("account_id", "is_archived"))
    categories = (
        Account.objects.exclude(account_group__account_type=BUDGET)
        .filter(Q(account_group__account_type__in=PAIRED_TYPES) | Q(pk__in=goal_archived.keys()))
        .order_by("book_id", "pk")
    )
    paired = set(Account.objects.filter(paired_account__isnull=False).values_list("paired_account_id", flat=True))

    by_book = {}
    for account in categories:
        by_book.setdefault(account.book_id, []).append(account)

    for book_id, accounts in by_book.items():
        group = _group(AccountGroup, book_id)
        if not Account.objects.filter(
            book_id=book_id, account_group__account_type=BUDGET, paired_account__isnull=True
        ).exists():
            Account.objects.create(book_id=book_id, name="Unassigned", account_group=group, is_system=True)
        Account.objects.bulk_create(
            [
                Account(
                    book_id=book_id,
                    name=account.name,
                    account_group=group,
                    is_system=True,
                    paired_account=account,
                    is_archived=goal_archived.get(account.pk, account.is_archived),
                )
                for account in accounts
                if account.pk not in paired
            ]
        )


def remove(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    AccountGroup = apps.get_model("accounts", "AccountGroup")
    Account.objects.filter(account_group__account_type=BUDGET).delete()
    AccountGroup.objects.filter(account_type=BUDGET).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0013_budget_buckets"),
        ("budget", "0008_goal_target_optional"),
    ]

    operations = [migrations.RunPython(backfill, remove)]
