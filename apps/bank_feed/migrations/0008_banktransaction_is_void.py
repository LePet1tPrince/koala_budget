from django.db import migrations, models


class Migration(migrations.Migration):
    """
    `is_archived` becomes `is_void`.

    A renamed column, not a new one: an archived bank row already counted toward
    nothing (its entry was excluded from every balance), which is what void means.
    `0009` then brings each linked row into line with its entry's status.
    """

    dependencies = [
        ("bank_feed", "0007_bank_transaction_source_ynab"),
    ]

    operations = [
        migrations.RenameField(model_name="banktransaction", old_name="is_archived", new_name="is_void"),
        migrations.RenameField(model_name="banktransaction", old_name="archived_at", new_name="voided_at"),
        migrations.AlterField(
            model_name="banktransaction",
            name="is_void",
            field=models.BooleanField(default=False, help_text="Whether this transaction is void (counts toward nothing)"),
        ),
        migrations.AlterField(
            model_name="banktransaction",
            name="voided_at",
            field=models.DateTimeField(blank=True, help_text="When this transaction was voided", null=True),
        ),
    ]
