"""
Tests for the guided task endpoints and the rail's visibility.

The rule worth protecting here: a task the server can detect for itself cannot be
claimed by the client. Accepting such a claim would let the checklist say a user
imported transactions when they never did.
"""

import json
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry
from apps.onboarding.context_processors import onboarding_rail
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class TaskTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Tasked", slug="tasked")
        cls.user = CustomUser.objects.create_user(username="worker", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        group = AccountGroup.objects.create(team=cls.team, name="Bank Accounts", account_type="asset")
        cls.account = Account.objects.create(team=cls.team, name="Chequing Account", account_group=group, has_feed=True)

    def setUp(self):
        self.client.force_login(self.user)
        self.tasks_url = reverse("onboarding:api_tasks", args=[self.team.slug])
        self.task_url = reverse("onboarding:api_task", args=[self.team.slug])

        self.state = OnboardingState.objects.create(team=self.team)
        self.state.complete()
        self.state.save()

    def post_json(self, payload):
        return self.client.post(
            self.task_url,
            data=json.dumps(payload),
            content_type="application/json",
            headers={"accept": "application/json"},
        )

    def states(self):
        return {t["slug"]: t["state"] for t in self.client.get(self.tasks_url).json()["tasks"]}

    def add_transaction(self):
        BankTransaction.objects.create(
            team=self.team,
            account=self.account,
            posted_date=date(2026, 9, 1),
            amount=Decimal("25.00"),
            description="LOBLAWS",
            source=BankTransaction.SOURCE_CSV,
        )

    def add_entry(self):
        JournalEntry.objects.create(
            team=self.team,
            entry_date=date(2026, 9, 1),
            description="groceries",
            status=JournalEntry.STATUS_POSTED,
        )


class TaskListTest(TaskTestCase):
    def test_lists_every_task_with_a_state(self):
        payload = self.client.get(self.tasks_url).json()

        self.assertTrue(payload["active"])
        self.assertTrue(payload["tasks"])
        for task in payload["tasks"]:
            with self.subTest(task=task["slug"]):
                self.assertIn(task["state"], ("locked", "available", "done"))

    def test_each_task_carries_a_link(self):
        """The rail's rows are links; a task with nowhere to go is a dead row."""
        for task in self.client.get(self.tasks_url).json()["tasks"]:
            with self.subTest(task=task["slug"]):
                self.assertTrue(task["url"].startswith(f"/a/{self.team.slug}/"))

    def test_locked_tasks_explain_themselves(self):
        for task in self.client.get(self.tasks_url).json()["tasks"]:
            if task["state"] == "locked":
                with self.subTest(task=task["slug"]):
                    self.assertTrue(task["reason"])

    def test_importing_unlocks_the_next_tasks(self):
        self.assertEqual(self.states()["categorize"], "locked")

        self.add_transaction()
        self.assertEqual(self.states()["categorize"], "available")

    def test_reporting_waits_for_a_categorized_transaction(self):
        """An uncategorized import moves nothing, so the report would be empty."""
        self.add_transaction()
        self.assertEqual(self.states()["report"], "locked")

        self.add_entry()
        self.assertEqual(self.states()["report"], "available")

    def test_requires_login(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(self.tasks_url).status_code, 200)

    def test_non_member_is_refused(self):
        outsider = CustomUser.objects.create_user(username="nosy", password="pass")
        self.client.force_login(outsider)

        self.assertNotEqual(self.client.get(self.tasks_url).status_code, 200)


class MarkTaskTest(TaskTestCase):
    def test_a_look_at_it_task_can_be_reported(self):
        self.add_transaction()
        self.add_entry()

        response = self.post_json({"slug": "report"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.states()["report"], "done")

    def test_a_detected_task_cannot_be_claimed(self):
        """Otherwise the checklist would say a user imported what they never did."""
        response = self.post_json({"slug": "import"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.states()["import"], "available")
        self.assertNotIn("import", OnboardingState.objects.get(team=self.team).tasks_done)

    def test_an_unknown_task_is_refused(self):
        self.assertEqual(self.post_json({"slug": "buy_a_boat"}).status_code, 400)

    def test_reporting_twice_is_harmless(self):
        self.add_transaction()
        self.add_entry()
        self.post_json({"slug": "report"})
        self.post_json({"slug": "report"})

        self.assertEqual(OnboardingState.objects.get(team=self.team).tasks_done.count("report"), 1)

    def test_finishing_every_task_ends_the_walkthrough(self):
        self.add_transaction()
        self.add_entry()
        from apps.budget.models import Budget

        expenses = AccountGroup.objects.create(team=self.team, name="Regular", account_type="expense")
        category = Account.objects.create(team=self.team, name="Groceries", account_group=expenses)
        Budget.objects.create(team=self.team, month=date(2026, 9, 1), category=category, budget_amount=Decimal("300"))

        self.post_json({"slug": "report"})
        response = self.post_json({"slug": "net_worth"})

        self.assertFalse(response.json()["active"])
        self.assertEqual(OnboardingState.objects.get(team=self.team).phase, OnboardingState.PHASE_DONE)

    def test_get_is_refused(self):
        self.assertEqual(self.client.get(self.task_url).status_code, 405)


class DismissTest(TaskTestCase):
    def test_dismissing_ends_the_walkthrough(self):
        response = self.post_json({"action": "dismiss"})

        self.assertFalse(response.json()["active"])
        self.assertEqual(OnboardingState.objects.get(team=self.team).phase, OnboardingState.PHASE_DONE)

    def test_a_dismissed_team_keeps_its_books(self):
        """Dismissing the guide is not undoing the setup."""
        self.post_json({"action": "dismiss"})

        self.assertTrue(Account.objects.filter(team=self.team).exists())


class RailVisibilityTest(TaskTestCase):
    """The context processor decides whether the rail renders at all."""

    def _request(self):
        request = self.client.get(reverse("web_team:home", args=[self.team.slug])).wsgi_request
        return request

    def test_shown_during_the_task_phase(self):
        self.assertIn("onboarding_rail", onboarding_rail(self._request()))

    def test_hidden_once_dismissed(self):
        self.post_json({"action": "dismiss"})

        self.assertEqual(onboarding_rail(self._request()), {})

    def test_hidden_before_the_questionnaire_is_finished(self):
        """A team still in the takeover does not also get a rail behind it."""
        self.state.phase = OnboardingState.PHASE_QUESTIONS
        self.state.completed_at = None
        self.state.save()

        self.assertEqual(onboarding_rail(self._request()), {})

    def test_hidden_for_a_team_that_skipped(self):
        self.state.phase = OnboardingState.PHASE_DONE
        self.state.save()

        self.assertEqual(onboarding_rail(self._request()), {})
