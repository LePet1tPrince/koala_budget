"""
The budget entries become the budget (phase 3b of docs/double-entry-budget-plan.md).

Forward: rebuild every budget entry from the `Budget` and `GoalAllocation` rows one
last time, so the ledger holds exactly what the rows said at the cut-over; the rows
and `JournalLine.budget` are then dropped (journal 0008, budget 0012). Refused if any
goal allocation carries notes, which the ledger has nowhere to keep: no screen ever
wrote them, so a note can only have come from a hand-edited import, and dropping it
silently would lose it.

Reverse: rebuild the rows from the entries (expense budget = an envelope's credit,
income budget = an expected-income bucket's debit, goal allocation = a goal bucket's
credit), then relink each line to its category's budget for its month.
"""

from importlib import import_module

from django.db import migrations

BUDGET = "budget"
INCOME = "income"
EXPENSE = "expense"


def forward(apps, schema_editor):
    GoalAllocation = apps.get_model("budget", "GoalAllocation")
    JournalEntry = apps.get_model("journal", "JournalEntry")
    JournalLine = apps.get_model("journal", "JournalLine")

    with_notes = GoalAllocation.objects.exclude(notes="").count()
    if with_notes:
        raise RuntimeError(
            f"{with_notes} goal allocation(s) carry notes, which the budget ledger cannot keep. "
            "Clear GoalAllocation.notes (or export them) before migrating."
        )
    JournalLine.objects.filter(journal_entry__source=BUDGET).delete()
    JournalEntry.objects.filter(source=BUDGET).delete()
    import_module("apps.budget.migrations.0010_budget_entries_backfill").backfill(apps, schema_editor)


def reverse(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    Budget = apps.get_model("budget", "Budget")
    Goal = apps.get_model("budget", "Goal")
    GoalAllocation = apps.get_model("budget", "GoalAllocation")
    JournalLine = apps.get_model("journal", "JournalLine")

    goal_of_account = dict(Goal.objects.filter(account__isnull=False).values_list("account_id", "pk"))
    types = dict(Account.objects.values_list("pk", "account_group__account_type"))
    budgets, allocations = [], []
    for book_id, month, paired_id, dr, cr in JournalLine.objects.filter(
        journal_entry__source=BUDGET, account__paired_account__isnull=False
    ).values_list("book_id", "journal_entry__entry_date", "account__paired_account_id", "dr_amount", "cr_amount"):
        if paired_id in goal_of_account:
            allocations.append(
                GoalAllocation(book_id=book_id, goal_id=goal_of_account[paired_id], month=month, amount=cr - dr)
            )
        elif types.get(paired_id) == INCOME:
            budgets.append(Budget(book_id=book_id, category_id=paired_id, month=month, budget_amount=dr - cr))
        elif types.get(paired_id) == EXPENSE:
            budgets.append(Budget(book_id=book_id, category_id=paired_id, month=month, budget_amount=cr - dr))
    Budget.objects.bulk_create(budgets, batch_size=1000)
    GoalAllocation.objects.bulk_create(allocations, batch_size=1000)

    # The line -> budget link the old JournalLine.save() kept: same category, same month.
    for budget in Budget.objects.all():
        month = budget.month
        end = month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)
        JournalLine.objects.filter(
            account_id=budget.category_id,
            journal_entry__entry_date__gte=month,
            journal_entry__entry_date__lt=end,
        ).update(budget=budget)


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0010_budget_entries_backfill"),
        ("journal", "0007_one_budget_entry_per_month"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
