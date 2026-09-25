import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("teams", "0005_invitation_archived_at_membership_archived_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Book",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "is_archived",
                    models.BooleanField(default=False, help_text="Set to true to archive this item"),
                ),
                (
                    "archived_at",
                    models.DateTimeField(blank=True, help_text="Date this item was archived", null=True),
                ),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField()),
                (
                    "budget_future_income",
                    models.BooleanField(
                        default=False,
                        help_text="Budget income before it arrives: this month's expected income counts toward "
                        "Unassigned.",
                    ),
                ),
                ("sort_order", models.IntegerField(default=0)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="books", to="teams.team"
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "name"],
                "unique_together": {("team", "name"), ("team", "slug")},
            },
        ),
    ]
