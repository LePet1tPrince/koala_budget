import apps.utils.fields
from django.db import migrations


def encrypt_tokens(apps, schema_editor):
    """Re-save every token: read as legacy plaintext, written encrypted."""
    PlaidItem = apps.get_model("plaid", "PlaidItem")
    for item in PlaidItem.objects.only("pk", "access_token"):
        PlaidItem.objects.filter(pk=item.pk).update(access_token=item.access_token)


def decrypt_tokens(apps, schema_editor):
    """Write the plaintext back with raw SQL, since the field would encrypt it again."""
    PlaidItem = apps.get_model("plaid", "PlaidItem")
    table = schema_editor.quote_name(PlaidItem._meta.db_table)
    with schema_editor.connection.cursor() as cursor:
        for item in PlaidItem.objects.only("pk", "access_token"):
            cursor.execute(f"UPDATE {table} SET access_token = %s WHERE id = %s", [item.access_token, item.pk])


class Migration(migrations.Migration):
    dependencies = [
        ("plaid", "0008_plaiditem_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="plaiditem",
            name="access_token",
            field=apps.utils.fields.EncryptedTextField(help_text="Access token for Plaid API (encrypted at rest)"),
        ),
        migrations.RunPython(encrypt_tokens, decrypt_tokens),
    ]
