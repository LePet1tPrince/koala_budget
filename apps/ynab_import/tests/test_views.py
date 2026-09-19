"""
The wizard's endpoints.

Two things are worth testing here rather than in the services: that the import is
scoped to the team on every call, and that the apply path -- which runs as a Celery
task -- actually lands the books when it is driven the way the wizard drives it.
"""

import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.journal.models import JournalEntry
from apps.onboarding.models import OnboardingState
from apps.ynab_import.models import YnabImport

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
