from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_book_required"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="hidden_from_budget",
            field=models.BooleanField(
                default=False,
                help_text="Income/expense category tucked into the budget page's collapsed Hidden group. "
                "A display choice only: its figures still count in every total.",
            ),
        ),
    ]
