# Generated migration to remove account_type field from Account model

from django.db import migrations, models
import django.db.models.deletion


def populate_account_groups_from_account_type(apps, schema_editor):
    """
    Ensure all accounts have an account_group before we remove account_type.
    For accounts without an account_group, create a default one based on their account_type.
    """
    Account = apps.get_model("transactions", "Account")
    AccountGroup = apps.get_model("transactions", "AccountGroup")

    # Get all accounts without an account_group
    accounts_without_group = Account.objects.filter(account_group__isnull=True)

    for account in accounts_without_group:
        # Try to find or create a default account group for this account type
        account_group, created = AccountGroup.objects.get_or_create(
            team=account.team,
            name=f"Default {account.get_account_type_display()}",
            defaults={
                "account_type": account.account_type,
                "description": f"Default group for {account.get_account_type_display()} accounts",
            },
        )
        account.account_group = account_group
        account.save()


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0001_initial"),
    ]

    operations = [
        # Step 1: Populate account_group for all accounts that don't have one
        migrations.RunPython(populate_account_groups_from_account_type, migrations.RunPython.noop),
        # Step 2: Make account_group non-nullable
        migrations.AlterField(
            model_name="account",
            name="account_group",
            field=models.ForeignKey(
                help_text="Account group classification",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accounts",
                to="transactions.accountgroup",
            ),
        ),
        # Step 3: Remove the account_type field
        migrations.RemoveField(
            model_name="account",
            name="account_type",
        ),
    ]

