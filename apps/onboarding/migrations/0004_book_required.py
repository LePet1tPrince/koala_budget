# Generated for docs/books-plan.md (M3 + M6)

"""
With every row backfilled, `book` becomes required, uniqueness is keyed on the
book instead of the team, and the transitional `team` column goes: the book is
the one source of truth for which tenant a row belongs to.
"""

import django.db.models.deletion
from django.db import migrations, models

from apps.books.migration_utils import fill_team_from_book


class Migration(migrations.Migration):
    dependencies = [
        ("books", "0003_backfill_books"),
        ("onboarding", "0003_book"),
    ]

    operations = [
        migrations.AlterField(
            model_name="onboardingstate",
            name="book",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="onboardingstate",
            unique_together={("book",)},
        ),
        # Nullable first, so reversing the removal re-adds a column that can be
        # created on a populated table and then filled from the book.
        migrations.AlterField(
            model_name="onboardingstate",
            name="team",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="teams.team",
                verbose_name="Team",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            fill_team_from_book("onboarding", ("onboardingstate",)),
        ),
        migrations.RemoveField(
            model_name="onboardingstate",
            name="team",
        ),
    ]
