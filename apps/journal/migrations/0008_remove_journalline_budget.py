from django.db import migrations


class Migration(migrations.Migration):
    """The budget lives in the ledger (apps.budget.ledger); a line no longer points at a `Budget` row."""

    dependencies = [
        ("journal", "0007_one_budget_entry_per_month"),
        ("budget", "0011_ledger_is_the_budget"),
    ]

    operations = [
        migrations.RemoveField(model_name="journalline", name="budget"),
    ]
