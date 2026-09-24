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
        ("plaid", "0004_book"),
    ]

    operations = [
        migrations.AlterField(
            model_name="plaiditem",
            name="book",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
        # Nullable first, so reversing the removal re-adds a column that can be
        # created on a populated table and then filled from the book.
        migrations.AlterField(
            model_name="plaiditem",
            name="team",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="teams.team",
                verbose_name="Team",
            ),
        ),
        migrations.AlterField(
            model_name="plaidaccount",
            name="book",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
        # Nullable first, so reversing the removal re-adds a column that can be
        # created on a populated table and then filled from the book.
        migrations.AlterField(
            model_name="plaidaccount",
            name="team",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="teams.team",
                verbose_name="Team",
            ),
        ),
        migrations.AlterField(
            model_name="plaidtransaction",
            name="book",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
        # Nullable first, so reversing the removal re-adds a column that can be
        # created on a populated table and then filled from the book.
        migrations.AlterField(
            model_name="plaidtransaction",
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
            fill_team_from_book(
                "plaid",
                (
                    "plaiditem",
                    "plaidaccount",
                    "plaidtransaction",
                ),
            ),
        ),
        migrations.RemoveField(
            model_name="plaiditem",
            name="team",
        ),
        migrations.RemoveField(
            model_name="plaidaccount",
            name="team",
        ),
        migrations.RemoveField(
            model_name="plaidtransaction",
            name="team",
        ),
    ]
