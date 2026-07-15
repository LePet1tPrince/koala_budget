from django.db import migrations, models


def backfill_sort_order(apps, schema_editor):
    """Seed sort_order from the previous alphabetical display order."""
    AccountGroup = apps.get_model("accounts", "AccountGroup")
    Account = apps.get_model("accounts", "Account")

    groups = []
    positions = {}  # (team_id, account_type) -> next index
    for group in AccountGroup.objects.order_by("team_id", "account_type", "name").iterator():
        key = (group.team_id, group.account_type)
        group.sort_order = positions.get(key, 0)
        positions[key] = group.sort_order + 1
        groups.append(group)
    AccountGroup.objects.bulk_update(groups, ["sort_order"], batch_size=500)

    accounts = []
    positions = {}  # account_group_id -> next index
    for account in Account.objects.order_by("account_group_id", "name").iterator():
        account.sort_order = positions.get(account.account_group_id, 0)
        positions[account.account_group_id] = account.sort_order + 1
        accounts.append(account)
    Account.objects.bulk_update(accounts, ["sort_order"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_add_is_system_to_account_and_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountgroup",
            name="sort_order",
            field=models.PositiveIntegerField(
                default=0, help_text="Manual display order within the account type"
            ),
        ),
        migrations.AddField(
            model_name="account",
            name="sort_order",
            field=models.PositiveIntegerField(
                default=0, help_text="Manual display order within the account group"
            ),
        ),
        migrations.AlterModelOptions(
            name="accountgroup",
            options={"ordering": ["sort_order", "name"]},
        ),
        migrations.AlterModelOptions(
            name="account",
            options={
                "ordering": [
                    "account_group__account_type",
                    "account_group__sort_order",
                    "account_group__name",
                    "sort_order",
                    "name",
                ]
            },
        ),
        migrations.RunPython(backfill_sort_order, migrations.RunPython.noop),
    ]
