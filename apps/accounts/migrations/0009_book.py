# Generated for docs/books-plan.md (M3 + M6)

"""
Every accounts row gains the set of books it belongs to. Nullable here, so the
column can be added to a populated table; `books.0003_backfill_books` fills it
from the row's team and `0010_book_required` makes it required and drops `team`.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("books", "0002_default_books"),
        ("accounts", "0008_add_sort_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountgroup",
            name="book",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
        migrations.AddField(
            model_name="account",
            name="book",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
        migrations.AddField(
            model_name="institution",
            name="book",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
        migrations.AddField(
            model_name="payee",
            name="book",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
    ]
