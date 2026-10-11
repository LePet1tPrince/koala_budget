"""
Book every goal's savings in the ledger (docs/goals-ledger-plan.md).

Until now a goal's saving lived outside the journal: `GoalAllocation` rows plus
what linked accounts brought in, derived on every read. From here a goal's fund
is credited by a saving entry per month, written by `apps.budget.goal_ledger`.
This gives every goal its "Saving: X" account and writes those entries.

It runs the live ledger code, because the rules live there and nowhere else. A
database with no goals skips it entirely, so a fresh database never reaches the
live models with an older schema. One deliberate change of number: a month with
both a plan and money moved into a linked account now saves the larger of the
two instead of their sum.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    if not apps.get_model("budget", "Goal").objects.exists():
        return

    from apps.books.models import Book
    from apps.budget import goal_ledger
    from apps.budget.models import Goal

    for book in Book.objects.filter(pk__in=Goal.objects.values("book_id")):
        for goal in Goal.objects.filter(book=book).select_related("book"):
            goal_ledger._saving_account(goal)
        goal_ledger.rebuild_book(book)


def backwards(apps, schema_editor):
    JournalEntry = apps.get_model("journal", "JournalEntry")
    Goal = apps.get_model("budget", "Goal")
    Account = apps.get_model("accounts", "Account")
    AccountGroup = apps.get_model("accounts", "AccountGroup")

    JournalEntry.objects.filter(source="goal").delete()
    Goal.objects.update(saving_account=None)
    Account.objects.filter(account_group__account_type="saving").delete()
    AccountGroup.objects.filter(account_type="saving").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0009_goal_ledger"),
        ("reconciliation", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
