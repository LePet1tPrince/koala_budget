"""
One set of books for every existing team: "Personal", slug `personal`.

`budget_future_income` is on for these books -- it is how every existing budget
already behaves (income budgeted this month and not yet received counts toward
Unassigned), so migrating changes no one's numbers. New books default to off.
"""

from django.db import migrations

DEFAULT_BOOK_NAME = "Personal"
DEFAULT_BOOK_SLUG = "personal"


def create_default_books(apps, schema_editor):
    Team = apps.get_model("teams", "Team")
    Book = apps.get_model("books", "Book")
    have_books = set(Book.objects.values_list("team_id", flat=True))
    Book.objects.bulk_create(
        [
            Book(
                team_id=team_id,
                name=DEFAULT_BOOK_NAME,
                slug=DEFAULT_BOOK_SLUG,
                budget_future_income=True,
                sort_order=0,
            )
            for team_id in Team.objects.exclude(id__in=have_books).values_list("id", flat=True)
        ]
    )


def delete_books(apps, schema_editor):
    apps.get_model("books", "Book").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("books", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_books, delete_books),
    ]
