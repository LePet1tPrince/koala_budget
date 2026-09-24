# Generated for docs/books-plan.md (M3 + M6)

"""
Every plaid row gains the set of books it belongs to. Nullable here, so the
column can be added to a populated table; `books.0003_backfill_books` fills it
from the row's team and `0005_book_required` makes it required and drops `team`.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("books", "0002_default_books"),
        ("plaid", "0003_plaiditem_last_synced_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="plaiditem",
            name="book",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
        migrations.AddField(
            model_name="plaidaccount",
            name="book",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
        migrations.AddField(
            model_name="plaidtransaction",
            name="book",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="books.book",
                verbose_name="Book",
            ),
        ),
    ]
