"""
Write every existing book's budget into the ledger: one budget entry per month
with budget amounts or goal allocations (`apps.budget.ledger`). The rows stay the
source of truth; the entries mirror them, and only budget buckets carry lines, so
no balance any report reads moves.

A frozen copy of `ledger.sync_book`, since a migration must not import code that
reads today's models. Reverse deletes the budget entries.
"""

from collections import defaultdict
from decimal import Decimal

from django.db import migrations

BUDGET = "budget"
ZERO = Decimal("0")


def backfill(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    Budget = apps.get_model("budget", "Budget")
    Goal = apps.get_model("budget", "Goal")
    GoalAllocation = apps.get_model("budget", "GoalAllocation")
    JournalEntry = apps.get_model("journal", "JournalEntry")
    JournalLine = apps.get_model("journal", "JournalLine")

    buckets = dict(
        Account.objects.filter(account_group__account_type=BUDGET, paired_account__isnull=False).values_list(
            "paired_account_id", "pk"
        )
    )
    unassigned = dict(
        Account.objects.filter(account_group__account_type=BUDGET, paired_account__isnull=True).values_list(
            "book_id", "pk"
        )
    )
    goal_accounts = dict(Goal.objects.filter(account__isnull=False).values_list("pk", "account_id"))

    claims = defaultdict(lambda: defaultdict(lambda: ZERO))
    for book_id, month, category_id, account_type, amount in Budget.objects.values_list(
        "book_id", "month", "category_id", "category__account_group__account_type", "budget_amount"
    ):
        bucket = buckets.get(category_id)
        if bucket is None or account_type not in ("income", "expense"):
            continue
        claims[(book_id, month.replace(day=1))][bucket] += -amount if account_type == "income" else amount
    for book_id, month, goal_id, amount in GoalAllocation.objects.values_list("book_id", "month", "goal_id", "amount"):
        bucket = buckets.get(goal_accounts.get(goal_id))
        if bucket is not None:
            claims[(book_id, month.replace(day=1))][bucket] += amount

    lines = []
    for (book_id, month), by_bucket in sorted(claims.items()):
        by_bucket = {bucket: amount for bucket, amount in by_bucket.items() if amount}
        if not by_bucket or book_id not in unassigned:
            continue
        net = sum(by_bucket.values(), ZERO)
        if net:
            by_bucket[unassigned[book_id]] = -net
        entry = JournalEntry.objects.create(
            book_id=book_id,
            entry_date=month,
            description=f"Budget for {month:%B %Y}",
            source=BUDGET,
            status="posted",
        )
        for account_id, amount in by_bucket.items():
            dr, cr = (ZERO, amount) if amount > 0 else (-amount, ZERO)
            lines.append(
                JournalLine(book_id=book_id, journal_entry=entry, account_id=account_id, dr_amount=dr, cr_amount=cr)
            )
    JournalLine.objects.bulk_create(lines, batch_size=1000)


def remove(apps, schema_editor):
    JournalEntry = apps.get_model("journal", "JournalEntry")
    JournalLine = apps.get_model("journal", "JournalLine")
    JournalLine.objects.filter(journal_entry__source=BUDGET).delete()
    JournalEntry.objects.filter(source=BUDGET).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0009_budget_buckets_backfill"),
        ("journal", "0007_one_budget_entry_per_month"),
    ]

    operations = [migrations.RunPython(backfill, remove)]
