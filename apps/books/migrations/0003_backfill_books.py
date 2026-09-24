"""
Fill the new `book` column on every financial row with its team's default book.

Each team has exactly one book at this point (0002), so there is nothing to
choose. Audit rows get a book too, except the events that belong to the team
rather than to its books (logins, membership changes).
"""

from django.db import migrations

from apps.books.migration_utils import BOOK_MODELS, TEAM_LEVEL_AUDIT_EVENTS, default_book_subquery


def backfill(apps, schema_editor):
    default_book = default_book_subquery(apps)
    for app_label, model_name in BOOK_MODELS:
        model = apps.get_model(app_label, model_name)
        model._base_manager.filter(book__isnull=True).update(book_id=default_book)

    AuditLog = apps.get_model("audit", "AuditLog")
    AuditLog._base_manager.filter(book__isnull=True, team__isnull=False).update(book_id=default_book)
    AuditEvent = apps.get_model("audit", "AuditEvent")
    AuditEvent._base_manager.filter(book__isnull=True, team__isnull=False).exclude(
        event_type__in=TEAM_LEVEL_AUDIT_EVENTS
    ).update(book_id=default_book)


class Migration(migrations.Migration):
    dependencies = [
        ("books", "0002_default_books"),
        ("accounts", "0009_book"),
        ("journal", "0003_book"),
        ("budget", "0005_book"),
        ("bank_feed", "0005_book"),
        ("plaid", "0004_book"),
        ("reconciliation", "0002_book"),
        ("monthly_review", "0003_book"),
        ("onboarding", "0003_book"),
        ("portability", "0002_book"),
        ("ynab_import", "0003_book"),
        ("audit", "0011_book"),
    ]

    operations = [
        # Reversing leaves the columns filled; the add-book migrations drop them.
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
