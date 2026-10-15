from django.db import migrations


class Migration(migrations.Migration):
    """The budget entries are the budget (apps.budget.ledger); the rows they were built from go."""

    dependencies = [
        ("budget", "0011_ledger_is_the_budget"),
        ("journal", "0008_remove_journalline_budget"),
    ]

    operations = [
        migrations.DeleteModel(name="GoalAllocation"),
        migrations.DeleteModel(name="Budget"),
    ]
