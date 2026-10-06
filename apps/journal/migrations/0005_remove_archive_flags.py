from django.db import migrations


class Migration(migrations.Migration):
    """
    Drop the archive flags on entries and lines.

    Nothing read them: a transaction is voided, never archived, and `status` is
    the one state that takes it out of balances. Reversible (the columns come
    back empty, which is what they held in practice).
    """

    dependencies = [
        ("journal", "0004_book_required"),
        ("bank_feed", "0009_void_consistency"),
    ]

    operations = [
        migrations.RemoveField(model_name="journalentry", name="is_archived"),
        migrations.RemoveField(model_name="journalentry", name="archived_at"),
        migrations.RemoveField(model_name="journalline", name="is_archived"),
        migrations.RemoveField(model_name="journalline", name="archived_at"),
    ]
