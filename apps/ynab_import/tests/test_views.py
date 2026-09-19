"""
The wizard's endpoints.

Two things are worth testing here rather than in the services: that the import is
scoped to the team on every call, and that the apply path -- which runs as a Celery
task -- actually lands the books when it is driven the way the wizard drives it.
"""

import json
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Payee
from apps.audit.models import AuditEvent
from apps.journal.models import JournalEntry
from apps.onboarding.models import OnboardingState
from apps.ynab_import.models import YnabImport
from apps.ynab_import.services.progress import ProgressChannel

from .fixtures import TINY_PLAN, TINY_REGISTER
from .test_apply import make_team


def upload_files():
    return [
        SimpleUploadedFile("register.csv", TINY_REGISTER.encode(), content_type="text/csv"),
        SimpleUploadedFile("plan.csv", TINY_PLAN.encode(), content_type="text/csv"),
    ]


class WizardTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("Wizard", "wizard")

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, name):
        return reverse(f"ynab_import:{name}", args=[self.team.slug])

    def upload(self):
        response = self.client.post(self.url("api_upload"), {"files": upload_files()})
        self.assertEqual(response.status_code, 200, response.content[:400])
        return response.json()

    def test_the_page_renders(self):
        response = self.client.get(self.url("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ynab-import-app")

    def test_upload_returns_what_we_made_of_the_export(self):
        payload = self.upload()
        self.assertEqual({a["name"] for a in payload["accounts"]}, {"Chequing", "Savings", "Visa"})
        self.assertEqual(payload["summary"]["entries"], 5)  # plus the two opening balances
        self.assertTrue(payload["can_import"])
        self.assertTrue(YnabImport.objects.filter(team=self.team, id=payload["import_id"]).exists())
        # Nothing is written to the books by looking at a file.
        self.assertFalse(JournalEntry.objects.filter(team=self.team).exists())

    def test_upload_needs_both_files(self):
        response = self.client.post(self.url("api_upload"), {"files": [upload_files()[0]]})
        self.assertEqual(response.status_code, 400)

    def test_upload_rejects_a_file_that_is_not_an_export(self):
        junk = SimpleUploadedFile("notes.csv", b"a,b,c\n1,2,3\n", content_type="text/csv")
        response = self.client.post(self.url("api_upload"), {"files": [junk, upload_files()[0]]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("plan file", response.json()["error"])

    def test_preview_reflects_the_choices(self):
        payload = self.upload()
        response = self.client.post(
            self.url("api_preview"),
            data=json.dumps(
                {
                    "import_id": payload["import_id"],
                    "choices": {"accounts": {"Savings": {"name": "Rainy Day"}}},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        names = [name for section in response.json()["chart"] for g in section["groups"] for name in g["accounts"]]
        self.assertIn("Rainy Day", names)
        self.assertNotIn("Savings", names)

    def test_preview_runs_the_reconciliation_before_anything_is_written(self):
        payload = self.upload()
        response = self.client.post(
            self.url("api_preview"),
            data=json.dumps({"import_id": payload["import_id"], "choices": {}}),
            content_type="application/json",
        )
        self.assertTrue(response.json()["reconciliation"]["passed"])
        self.assertFalse(JournalEntry.objects.filter(team=self.team).exists())

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_apply_imports_the_books(self):
        payload = self.upload()
        response = self.client.post(
            self.url("api_apply"),
            data=json.dumps({"import_id": payload["import_id"], "choices": {}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        status = self.client.get(f"{self.url('api_status')}?import_id={payload['import_id']}").json()
        self.assertEqual(status["status"], "done")
        self.assertEqual(status["result"]["created"]["entries"], 5)
        self.assertTrue(status["result"]["reconciliation"]["passed"])
        self.assertEqual(JournalEntry.objects.filter(team=self.team).count(), 5 + 2)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_the_stored_export_is_cleared_once_it_is_in_the_ledger(self):
        payload = self.upload()
        self.client.post(
            self.url("api_apply"),
            data=json.dumps({"import_id": payload["import_id"]}),
            content_type="application/json",
        )
        record = YnabImport.objects.get(id=payload["import_id"])
        self.assertEqual(record.register_csv, "")
        self.assertEqual(record.plan_csv, "")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_applying_twice_does_not_import_twice(self):
        payload = self.upload()
        body = json.dumps({"import_id": payload["import_id"]})
        self.client.post(self.url("api_apply"), data=body, content_type="application/json")
        before = JournalEntry.objects.filter(team=self.team).count()
        self.client.post(self.url("api_apply"), data=body, content_type="application/json")
        self.assertEqual(JournalEntry.objects.filter(team=self.team).count(), before)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_a_team_that_already_has_transactions_is_refused(self):
        payload = self.upload()
        self.client.post(
            self.url("api_apply"),
            data=json.dumps({"import_id": payload["import_id"]}),
            content_type="application/json",
        )

        second = self.upload()
        response = self.client.post(
            self.url("api_apply"),
            data=json.dumps({"import_id": second["import_id"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("already has transactions", response.json()["error"])

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, ONBOARDING_ENABLED=True)
    def test_an_import_finishes_the_onboarding_takeover(self):
        # The export answers the questionnaire better than the user could, so the
        # takeover is finished rather than waited for -- with the guided tasks the
        # import has plainly done already ticked off.
        payload = self.upload()
        self.client.post(
            self.url("api_apply"),
            data=json.dumps({"import_id": payload["import_id"]}),
            content_type="application/json",
        )
        state = OnboardingState.objects.get(team=self.team)
        self.assertEqual(state.phase, OnboardingState.PHASE_TASKS)
        self.assertTrue(state.is_finished)
        self.assertEqual(set(state.tasks_done), {"import", "categorize", "budget"})

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_the_import_is_recorded_in_the_audit_trail(self):
        payload = self.upload()
        self.client.post(
            self.url("api_apply"),
            data=json.dumps({"import_id": payload["import_id"]}),
            content_type="application/json",
        )
        event = AuditEvent.objects.filter(team=self.team, event_type=AuditEvent.YNAB_IMPORT).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.metadata["created"]["entries"], 5)
        self.assertTrue(event.metadata["reconciliation_passed"])


class TeamScopingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("Mine", "mine")
        cls.other_team, cls.other_user = make_team("Theirs", "theirs")
        cls.record = YnabImport.objects.create(team=cls.other_team, register_csv=TINY_REGISTER, plan_csv=TINY_PLAN)

    def test_another_teams_import_is_not_reachable(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ynab_import:api_preview", args=[self.team.slug]),
            data=json.dumps({"import_id": self.record.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_a_non_member_cannot_open_the_wizard(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("ynab_import:home", args=[self.other_team.slug]))
        self.assertIn(response.status_code, (403, 404, 302))

    def test_anonymous_users_are_sent_to_log_in(self):
        response = self.client.get(reverse("ynab_import:home", args=[self.team.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)


class UnexpectedErrorTest(TestCase):
    """
    What the wizard says when something breaks that is not the user's doing.

    The endpoints are read by `fetch`, so an unhandled exception that returned
    Django's HTML page left the wizard with nothing to show but "Something went
    wrong." The commonest cause is a database that has not been migrated, which is
    a one-command fix the user can only make if they are told.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("Broken", "broken")

    def setUp(self):
        self.client.force_login(self.user)

    def test_a_crash_answers_json_the_wizard_can_read(self):
        url = reverse("ynab_import:api_upload", args=[self.team.slug])
        with patch("apps.ynab_import.views.YnabImport.objects.create", side_effect=ProgrammingError("no such table")):
            response = self.client.post(url, {"files": upload_files()})

        self.assertEqual(response.status_code, 500)
        self.assertIn("migrating", response.json()["error"])

    @override_settings(DEBUG=True)
    def test_in_debug_the_reason_itself_reaches_the_browser(self):
        url = reverse("ynab_import:api_upload", args=[self.team.slug])
        with patch("apps.ynab_import.views.YnabImport.objects.create", side_effect=ProgrammingError("no such table")):
            response = self.client.post(url, {"files": upload_files()})

        self.assertIn("ProgrammingError: no such table", response.json()["detail"])


class ProgressChannelTest(TransactionTestCase):
    """
    The property the progress bar depends on: a figure written from inside the
    import's transaction is readable by the web process *before* that transaction
    commits. Without it the bar sits at zero for the whole import and then jumps,
    which is worse than no bar -- it says the import is doing nothing.

    `TransactionTestCase` because the point is what other connections can see, and
    an ordinary `TestCase` wraps each test in a transaction of its own.
    """

    def setUp(self):
        self.team, self.user = make_team("Progress", "progress")
        self.record = YnabImport.objects.create(team=self.team, register_csv="x", plan_csv="y")

    def count_payees_from_another_connection(self) -> int:
        connection = connections.create_connection(DEFAULT_DB_ALIAS)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM accounts_payee WHERE team_id = %s", [self.team.id])
                return cursor.fetchone()[0]
        finally:
            connection.close()

    def read_progress_from_another_connection(self) -> tuple[int, str]:
        connection = connections.create_connection(DEFAULT_DB_ALIAS)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT progress, step FROM ynab_import_ynabimport WHERE id = %s",
                    [self.record.id],
                )
                return cursor.fetchone()
        finally:
            connection.close()

    def test_progress_is_visible_while_the_import_transaction_is_still_open(self):
        channel = ProgressChannel(self.record.id)
        try:
            with transaction.atomic():
                # Stand in for the import: a write in this transaction, invisible to
                # anyone else until it commits...
                Payee.objects.create(team=self.team, name="Mid-import payee")
                # ...while the progress written through the channel is not.
                channel.report(42, "Importing your transactions")
                progress, step = self.read_progress_from_another_connection()

                self.assertEqual(progress, 42)
                self.assertEqual(step, "Importing your transactions")
                # The control: the import's own write really is still invisible, so
                # the test is measuring what it claims to.
                self.assertEqual(self.count_payees_from_another_connection(), 0)
        finally:
            channel.close()

    def test_a_channel_that_cannot_open_a_connection_does_not_fail_the_import(self):
        channel = ProgressChannel(self.record.id)
        with patch.object(ProgressChannel, "_ensure_connection", side_effect=OperationalError("no connections")):
            channel.report(10, "Creating your accounts")  # must not raise
        self.assertEqual(YnabImport.objects.get(id=self.record.id).progress, 0)

    def test_a_locked_row_gives_up_rather_than_stalling_the_import(self):
        """
        The safeguard: this connection writes to a row the import's transaction
        could be holding, and waiting on that lock would hold the import up until
        it finished -- which is to say, forever.
        """
        channel = ProgressChannel(self.record.id)
        try:
            with transaction.atomic():
                # Take the lock the channel wants.
                YnabImport.objects.select_for_update().get(id=self.record.id)
                channel.report(42, "Importing your transactions")  # must return, not block

            self.assertEqual(YnabImport.objects.get(id=self.record.id).progress, 0)
        finally:
            channel.close()


class StatusReportingTest(TestCase):
    """
    What the wizard is told while it waits, and what it is told when the waiting is
    pointless because the worker is gone.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("Status", "status")

    def setUp(self):
        self.client.force_login(self.user)
        self.record = YnabImport.objects.create(
            team=self.team,
            register_csv=TINY_REGISTER,
            plan_csv=TINY_PLAN,
            status=YnabImport.STATUS_RUNNING,
            task_id="task-1",
            progress=40,
            started_at=timezone.now() - timedelta(seconds=30),
        )

    def status(self) -> dict:
        url = reverse("ynab_import:api_status", args=[self.team.slug])
        return self.client.get(f"{url}?import_id={self.record.id}").json()

    def live(self, **info):
        return patch("apps.ynab_import.views._live_progress", return_value=info)

    def test_a_running_import_reports_elapsed_and_an_estimate(self):
        payload = self.status()
        self.assertTrue(payload["started"])
        self.assertGreater(payload["elapsed_seconds"], 25)
        # 40% in 30 seconds puts the rest at around 45 more.
        self.assertGreater(payload["eta_seconds"], 30)
        self.assertLess(payload["eta_seconds"], 60)

    def test_no_estimate_before_there_is_anything_to_estimate_from(self):
        self.record.progress = 5
        self.record.save(update_fields=["progress"])
        self.assertIsNone(self.status()["eta_seconds"])

    def test_live_progress_overtakes_the_row(self):
        with self.live(complete=False, progress={"percent": 72, "description": "Importing your transactions"}):
            payload = self.status()
        self.assertEqual(payload["progress"], 72)
        self.assertEqual(payload["step"], "Importing your transactions")

    def test_a_finished_task_never_fills_the_bar_while_the_row_says_running(self):
        # `celery_progress` reports 100% for any finished task. Handing that to a
        # bar while work is still going on is the "full and stuck" the user sees.
        self.record.save(update_fields=["updated_at"])
        with self.live(complete=True, success=True, progress={"percent": 100}):
            payload = self.status()
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["progress"], 99)

    def test_a_worker_that_died_is_reported_rather_than_waited_for(self):
        YnabImport.objects.filter(id=self.record.id).update(updated_at=timezone.now() - timedelta(minutes=5))
        with self.live(complete=True, success=False, progress={"percent": 100}):
            payload = self.status()

        self.assertEqual(payload["status"], "failed")
        self.assertIn("stopped before it finished", payload["error"])
        self.assertIn("exactly as they were", payload["error"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, YnabImport.STATUS_FAILED)

    def test_without_a_result_backend_the_row_is_still_reported(self):
        with patch("apps.ynab_import.views._live_progress", return_value=None):
            payload = self.status()
        self.assertEqual(payload["progress"], 40)
        self.assertEqual(payload["status"], "running")
