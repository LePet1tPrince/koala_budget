"""
The Celery task (§7 Phase 3's `tasks.py`). `settings_test.py` sets
`CELERY_TASK_ALWAYS_EAGER = True`, so `.delay(...)` runs synchronously here,
same as the YNAB importer's own tests.

Two progress-reporting calls are patched to no-ops for this module only,
neither because they are wrong but because neither has anything real to talk
to in this environment:

* `ProgressChannel` opens a **second** database connection so progress
  updates are visible before the import's own transaction commits (see its
  docstring). That is exactly right against Postgres -- what `make test`
  actually runs against -- but a plain sqlite `:memory:` database (the
  stand-in used to run this suite without Docker here) has one writer and no
  real concurrent-connection support, so a second connection touching the
  same row deadlocks against the first.
* `celery_progress`'s `ProgressRecorder.set_progress` writes to
  `CELERY_RESULT_BACKEND`, which defaults to a Redis URL
  (`koala_budget/settings.py`) that nothing is listening on here, and the
  client can hang rather than fail fast.

Everything under test in this module is the task's own orchestration (the
status guard, the safety-copy sequencing, error handling) -- not either
progress channel, which `apps/ynab_import` already proved out against the
real backends.
"""

from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import Account
from apps.audit.models import AuditEvent
from apps.portability.models import DataImport
from apps.portability.services.export import build_archive, build_checks, build_omitted
from apps.portability.services.write import build_archive_bytes
from apps.portability.tasks import run_data_import

from .db_fixtures import build_db_fixture_team, make_team


def _export_bytes(book) -> bytes:
    accounts, journal_rows, budget_rows = build_archive(book)
    return build_archive_bytes(
        accounts=accounts,
        journal=journal_rows,
        budget=budget_rows,
        source={"team_name": book.name},
        checks=build_checks(book),
        omitted=build_omitted(book),
    )


@patch("apps.portability.services.progress.ProgressChannel.report", lambda self, percent, step: None)
@patch("apps.portability.services.progress.ProgressChannel.close", lambda self: None)
@patch("celery_progress.backend.ProgressRecorder.set_progress", lambda self, *a, **k: None)
class RunDataImportTests(TestCase):
    def test_a_successful_import_marks_the_row_done_and_clears_the_archive(self):
        source_team, _u, _h = build_db_fixture_team("Src", "task-src")
        source_book = source_team.default_book
        dest_team, dest_user = make_team("Dst", "task-dst")
        dest_book = dest_team.default_book
        record = DataImport.objects.create(book=dest_book, created_by=dest_user, archive=_export_bytes(source_book))

        run_data_import.delay(record.id)

        record.refresh_from_db()
        self.assertEqual(record.status, DataImport.STATUS_DONE)
        self.assertEqual(record.progress, 100)
        self.assertEqual(bytes(record.archive), b"")
        self.assertTrue(record.result)
        self.assertTrue(Account.objects.filter(book=dest_book, name="Goal: New Deck").exists())

    def test_the_safety_archive_is_saved_and_not_cleared(self):
        source_team, _u, _h = build_db_fixture_team("Src2", "task-src2")
        source_book = source_team.default_book
        dest_team, dest_user, _h2 = build_db_fixture_team("Dst2", "task-dst2")
        dest_book = dest_team.default_book
        record = DataImport.objects.create(book=dest_book, created_by=dest_user, archive=_export_bytes(source_book))

        run_data_import.delay(record.id)

        record.refresh_from_db()
        self.assertTrue(bytes(record.safety_archive))
        self.assertIsNotNone(record.safety_archive_created_at)

    def test_a_malformed_archive_marks_the_row_failed_and_touches_nothing(self):
        dest_team, dest_user, _h = build_db_fixture_team("Dst3", "task-dst3")
        dest_book = dest_team.default_book
        original_count = Account.objects.filter(book=dest_book).count()
        record = DataImport.objects.create(book=dest_book, created_by=dest_user, archive=b"not a zip")

        run_data_import.delay(record.id)

        record.refresh_from_db()
        self.assertEqual(record.status, DataImport.STATUS_FAILED)
        self.assertTrue(record.error)
        self.assertEqual(Account.objects.filter(book=dest_book).count(), original_count)

    def test_already_running_import_is_not_picked_up_twice(self):
        source_team, _u, _h = build_db_fixture_team("Src4", "task-src4")
        source_book = source_team.default_book
        dest_team, dest_user = make_team("Dst4", "task-dst4")
        dest_book = dest_team.default_book
        record = DataImport.objects.create(
            book=dest_book, created_by=dest_user, archive=_export_bytes(source_book), status=DataImport.STATUS_DONE
        )

        run_data_import.delay(record.id)

        record.refresh_from_db()
        self.assertEqual(record.status, DataImport.STATUS_DONE)  # unchanged -- guard held

    def test_two_audit_events_are_logged_exactly_once(self):
        source_team, _u, _h = build_db_fixture_team("Src5", "task-src5")
        source_book = source_team.default_book
        dest_team, dest_user = make_team("Dst5", "task-dst5")
        dest_book = dest_team.default_book
        record = DataImport.objects.create(book=dest_book, created_by=dest_user, archive=_export_bytes(source_book))

        run_data_import.delay(record.id)

        events = AuditEvent.objects.filter(team=dest_team)
        self.assertEqual(events.filter(event_type=AuditEvent.DATA_WIPED).count(), 1)
        self.assertEqual(events.filter(event_type=AuditEvent.DATA_IMPORTED).count(), 1)
