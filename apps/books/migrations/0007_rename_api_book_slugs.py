"""
`api` became a reserved book slug when `/a/{team}/{book}/api/` was mounted (the
nav-state endpoint), so a book already called "api" would be shadowed by it. Such a
book moves to the next free `api-N` slug in its team, as `unique_book_slug` would
have given it. (A link to its old address now reads as a pre-books link and
opens the team's default book.)
"""

from django.db import migrations

NEWLY_RESERVED = ("api",)


def rename_shadowed_books(apps, schema_editor):
    Book = apps.get_model("books", "Book")
    for book in Book.objects.filter(slug__in=NEWLY_RESERVED):
        taken = set(Book.objects.filter(team_id=book.team_id).values_list("slug", flat=True))
        suffix = 2
        while f"{book.slug}-{suffix}" in taken:
            suffix += 1
        book.slug = f"{book.slug}-{suffix}"
        book.save(update_fields=["slug"])


class Migration(migrations.Migration):
    dependencies = [
        ("books", "0006_book_locked_through"),
    ]

    operations = [
        migrations.RunPython(rename_shadowed_books, migrations.RunPython.noop),
    ]
