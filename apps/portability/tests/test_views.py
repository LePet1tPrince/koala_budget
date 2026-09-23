"""
The export/import page and its endpoints (§7 Phase 4).

Every write route is `@team_admin_required`; only the export itself is open
to any team member (§9's "yes, read-only, own team"). `GuardTests` locks
that split down explicitly, since it is the one guarantee this whole feature
would be dangerous without.
"""

import zipfile
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.portability.models import DataImport
from apps.teams.models import Membership
from apps.teams.roles import ROLE_MEMBER

from .db_fixtures import build_db_fixture_team, make_team


def _export_file(team) -> SimpleUploadedFile:
    from apps.portability.services import export, write

    accounts, journal_rows, budget_rows = export.build_archive(team)
    data = write.build_archive_bytes(
        accounts=accounts,
        journal=journal_rows,
        budget=budget_rows,
        source={"team_name": team.name},
        checks=export.build_checks(team),
        omitted=export.build_omitted(team),
    )
    return SimpleUploadedFile("export.zip", data, content_type="application/zip")


class ExportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.admin, cls.handles = build_db_fixture_team("Export Team", "export-team")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_export_downloads_a_valid_zip(self):
        response = self.client.get(reverse("portability:export", args=[self.team.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertTrue(response["Content-Length"])
        with zipfile.ZipFile(BytesIO(response.content)) as zf:
            self.assertEqual(
                set(zf.namelist()),
                {"manifest.json", "accounts.csv", "journal.csv", "budget.csv", "reconciliations.csv"},
            )

    def test_a_plain_member_can_export_their_own_team(self):
        member = self._add_member()
        self.client.force_login(member)
        response = self.client.get(reverse("portability:export", args=[self.team.slug]))
        self.assertEqual(response.status_code, 200)

    def _add_member(self):
        from apps.users.models import CustomUser

        user = CustomUser.objects.create_user(username="plain-member", password="pass")
        Membership.objects.create(team=self.team, user=user, role=ROLE_MEMBER)
        return user


class UploadApplyStatusFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source_team, cls.source_user, cls.handles = build_db_fixture_team("View Src", "view-src")
        cls.dest_team, cls.dest_admin = make_team("View Dst", "view-dst")

    def setUp(self):
        self.client.force_login(self.dest_admin)

    def url(self, name, **kwargs):
        return reverse(f"portability:{name}", args=[self.dest_team.slug], **kwargs)

    def test_home_page_loads(self):
        response = self.client.get(self.url("home"))
        self.assertEqual(response.status_code, 200)

    def test_upload_returns_a_file_summary_and_writes_nothing(self):
        before = DataImport.objects.filter(team=self.dest_team).count()
        response = self.client.post(self.url("api_upload"), {"file": _export_file(self.source_team)})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("import_id", payload)
        self.assertIn("checks", payload["file"])
        self.assertIn("checks", payload["destination"])
        # A DataImport row is created to hold the bytes for the apply step,
        # but nothing about the team's own books is written yet.
        self.assertEqual(DataImport.objects.filter(team=self.dest_team).count(), before + 1)

    def test_upload_rejects_a_non_export_file(self):
        junk = SimpleUploadedFile("notes.txt", b"not an export", content_type="text/plain")
        response = self.client.post(self.url("api_upload"), {"file": junk})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_apply_refuses_a_wrong_team_name(self):
        upload = self.client.post(self.url("api_upload"), {"file": _export_file(self.source_team)}).json()
        response = self.client.post(
            self.url("api_apply"),
            data={"import_id": upload["import_id"], "team_name": "not the team name"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        record = DataImport.objects.get(id=upload["import_id"])
        self.assertEqual(record.status, DataImport.STATUS_UPLOADED)  # never queued

    @patch("apps.portability.services.progress.ProgressChannel.report", lambda self, percent, step: None)
    @patch("apps.portability.services.progress.ProgressChannel.close", lambda self: None)
    @patch("celery_progress.backend.ProgressRecorder.set_progress", lambda self, *a, **k: None)
    def test_apply_with_the_correct_name_runs_the_import(self):
        upload = self.client.post(self.url("api_upload"), {"file": _export_file(self.source_team)}).json()
        response = self.client.post(
            self.url("api_apply"),
            data={"import_id": upload["import_id"], "team_name": self.dest_team.name},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        record = DataImport.objects.get(id=upload["import_id"])
        self.assertEqual(record.status, DataImport.STATUS_DONE)  # CELERY_TASK_ALWAYS_EAGER

        status = self.client.get(f"{self.url('api_status')}?import_id={record.id}").json()
        self.assertEqual(status["status"], "done")

    def test_status_404s_for_an_unknown_import_id(self):
        response = self.client.get(f"{self.url('api_status')}?import_id=999999")
        self.assertEqual(response.status_code, 404)

    def test_safety_export_404s_before_anything_has_run(self):
        response = self.client.get(f"{self.url('api_safety_export')}?import_id=999999")
        self.assertEqual(response.status_code, 404)


class GuardTests(TestCase):
    """Every write route is admin-only; export is not."""

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.admin, cls.handles = build_db_fixture_team("Guarded", "guarded")
        from apps.users.models import CustomUser

        cls.member = CustomUser.objects.create_user(username="guard-member", password="pass")
        Membership.objects.create(team=cls.team, user=cls.member, role=ROLE_MEMBER)

    def setUp(self):
        self.client.force_login(self.member)

    def test_home_refuses_a_plain_member(self):
        response = self.client.get(reverse("portability:home", args=[self.team.slug]))
        self.assertEqual(response.status_code, 404)  # team_admin_required treats it as not-found

    def test_upload_refuses_a_plain_member(self):
        response = self.client.post(
            reverse("portability:api_upload", args=[self.team.slug]), {"file": _export_file(self.team)}
        )
        self.assertEqual(response.status_code, 404)

    def test_apply_refuses_a_plain_member(self):
        response = self.client.post(
            reverse("portability:api_apply", args=[self.team.slug]),
            data={"import_id": 1, "team_name": self.team.name},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_status_refuses_a_plain_member(self):
        response = self.client.get(f"{reverse('portability:api_status', args=[self.team.slug])}?import_id=1")
        self.assertEqual(response.status_code, 404)

    def test_safety_export_refuses_a_plain_member(self):
        response = self.client.get(f"{reverse('portability:api_safety_export', args=[self.team.slug])}?import_id=1")
        self.assertEqual(response.status_code, 404)

    def test_a_logged_out_user_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("portability:home", args=[self.team.slug]))
        self.assertEqual(response.status_code, 302)
