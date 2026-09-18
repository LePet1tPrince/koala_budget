import json
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.journal.models import JournalEntry, JournalLine
from apps.monthly_review.models import MonthlyReviewState
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class MonthlyReviewViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Review Home Team", slug="review-home-team")
        cls.user = CustomUser.objects.create_user(username="member", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Pay", account_type=ACCOUNT_TYPE_INCOME)
        cls.chequing = Account.objects.create(team=cls.team, name="Chequing", account_group=cls.asset_group)
        cls.salary = Account.objects.create(team=cls.team, name="Salary", account_group=cls.income_group)

        entry = JournalEntry.objects.create(
            team=cls.team, entry_date=date(2026, 8, 10), description="pay", status=JournalEntry.STATUS_POSTED
        )
        JournalLine.objects.create(team=cls.team, journal_entry=entry, account=cls.chequing, dr_amount=Decimal("1000"))
        JournalLine.objects.create(team=cls.team, journal_entry=entry, account=cls.salary, cr_amount=Decimal("1000"))

    def setUp(self):
        self.client.force_login(self.user)
        self.home_url = reverse("monthly_review:home", args=[self.team.slug])
        self.step_url = reverse("monthly_review:api_step", args=[self.team.slug])
        self.complete_url = reverse("monthly_review:api_complete", args=[self.team.slug])
        self.dismiss_url = reverse("monthly_review:api_dismiss", args=[self.team.slug])
        self.export_url = reverse("monthly_review:export", args=[self.team.slug])

    def post_json(self, url, payload=None):
        return self.client.post(
            url,
            data=json.dumps(payload or {}),
            content_type="application/json",
            headers={"accept": "application/json"},
        )


class MonthlyReviewHomeTests(MonthlyReviewViewTestCase):
    def test_happy_path_renders_and_creates_state(self):
        self.assertFalse(MonthlyReviewState.objects.filter(team=self.team).exists())

        response = self.client.get(self.home_url, {"month": "2026-08"})

        self.assertEqual(response.status_code, 200)
        state = MonthlyReviewState.objects.get(team=self.team, month=date(2026, 8, 1))
        self.assertIsNotNone(state.started_at)
        self.assertTrue(
            AuditEvent.objects.filter(team=self.team, event_type=AuditEvent.MONTHLY_REVIEW_STARTED).exists()
        )

    def test_month_query_param_is_parsed(self):
        response = self.client.get(self.home_url, {"month": "2026-08"})
        self.assertContains(response, "2026-08-01")

    def test_month_defaults_to_last_complete_month(self):
        response = self.client.get(self.home_url)
        self.assertEqual(response.status_code, 200)
        # Some MonthlyReviewState row was created for the default month.
        self.assertTrue(MonthlyReviewState.objects.filter(team=self.team).exists())

    def test_month_before_first_activity_is_empty_state_not_404(self):
        response = self.client.get(self.home_url, {"month": "2020-01"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "nothing to review")

    def test_empty_state_offers_prev_next_month_navigation(self):
        response = self.client.get(self.home_url, {"month": "2020-01"})
        self.assertContains(response, "?month=2019-12-01")
        self.assertContains(response, "?month=2020-02-01")

    def test_any_month_on_or_after_first_activity_shows_full_dashboard(self):
        # August 2026 has the seeded entry; a later month with no activity of
        # its own still renders the full page (zeroed figures), not the
        # "nothing to review" empty state -- the team's ledger has started.
        response = self.client.get(self.home_url, {"month": "2026-10"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "nothing to review")
        self.assertContains(response, "monthly-review-props")

    def test_can_navigate_back_to_an_earlier_reviewed_month(self):
        first_response = self.client.get(self.home_url, {"month": "2026-08"})
        self.assertContains(first_response, "2026-08-01")

        later_response = self.client.get(self.home_url, {"month": "2026-09"})
        self.assertContains(later_response, "2026-09-01")

        # Each month keeps its own state row.
        self.assertTrue(MonthlyReviewState.objects.filter(team=self.team, month=date(2026, 8, 1)).exists())
        self.assertTrue(MonthlyReviewState.objects.filter(team=self.team, month=date(2026, 9, 1)).exists())

    def test_non_member_gets_404(self):
        outsider = CustomUser.objects.create_user(username="outsider", password="pass")
        self.client.force_login(outsider)
        response = self.client.get(self.home_url, {"month": "2026-08"})
        self.assertEqual(response.status_code, 404)


class ApiStepTests(MonthlyReviewViewTestCase):
    def test_records_step_and_logs_event(self):
        response = self.post_json(self.step_url, {"month": "2026-08-01", "step": 3})
        self.assertEqual(response.status_code, 200)
        state = MonthlyReviewState.objects.get(team=self.team, month=date(2026, 8, 1))
        self.assertEqual(state.step, 3)
        self.assertIn(3, state.steps_seen)
        self.assertTrue(
            AuditEvent.objects.filter(team=self.team, event_type=AuditEvent.MONTHLY_REVIEW_STEP_COMPLETED).exists()
        )

    def test_baseline_change_is_logged(self):
        self.post_json(self.step_url, {"month": "2026-08-01", "baseline": "6m"})
        state = MonthlyReviewState.objects.get(team=self.team, month=date(2026, 8, 1))
        self.assertEqual(state.baseline, "6m")
        self.assertTrue(
            AuditEvent.objects.filter(team=self.team, event_type=AuditEvent.MONTHLY_REVIEW_BASELINE_CHANGED).exists()
        )

    def test_non_member_is_refused(self):
        outsider = CustomUser.objects.create_user(username="outsider2", password="pass")
        self.client.force_login(outsider)
        response = self.post_json(self.step_url, {"month": "2026-08-01", "step": 2})
        self.assertNotEqual(response.status_code, 200)


class ApiCompleteTests(MonthlyReviewViewTestCase):
    def test_marks_month_reviewed_and_returns_recap(self):
        response = self.post_json(self.complete_url, {"month": "2026-08-01"})
        self.assertEqual(response.status_code, 200)
        state = MonthlyReviewState.objects.get(team=self.team, month=date(2026, 8, 1))
        self.assertTrue(state.is_finished)
        payload = response.json()
        self.assertIn("current", payload)
        self.assertEqual(Decimal(str(payload["current"]["income"])), Decimal("1000"))
        self.assertTrue(
            AuditEvent.objects.filter(team=self.team, event_type=AuditEvent.MONTHLY_REVIEW_COMPLETED).exists()
        )

    def test_already_finished_is_a_no_op(self):
        self.post_json(self.complete_url, {"month": "2026-08-01"})
        response = self.post_json(self.complete_url, {"month": "2026-08-01"})
        self.assertEqual(response.json(), {"already_finished": True})


class ApiDismissTests(MonthlyReviewViewTestCase):
    def test_dismisses_and_logs_event(self):
        response = self.post_json(self.dismiss_url, {"month": "2026-08-01"})
        self.assertEqual(response.status_code, 200)
        state = MonthlyReviewState.objects.get(team=self.team, month=date(2026, 8, 1))
        self.assertTrue(state.is_finished)
        self.assertTrue(
            AuditEvent.objects.filter(team=self.team, event_type=AuditEvent.MONTHLY_REVIEW_DISMISSED).exists()
        )


class ExportTests(MonthlyReviewViewTestCase):
    def test_export_returns_csv(self):
        response = self.client.get(self.export_url, {"month": "2026-08"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
