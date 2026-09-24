"""
Tests for the walkthrough's audit trail and its ending.

The funnel is the point: a single completion rate says people drop out, while a
per-phase event says *which question* loses them. These tests guard that the
events carry enough to answer that, and that the walkthrough ends cleanly whether
the user finishes it or walks away.
"""

import json
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.bank_feed.models import BankTransaction
from apps.budget.models import Budget
from apps.journal.models import JournalEntry
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

ANSWERS = {
    "income_sources": ["employment"],
    "household_shape": "solo",
    "budget_future_income": "no",
    "housing": "rent",
    "kids": "no",
    "transport": ["transit"],
    "debts": ["none"],
    "savings": ["none"],
    "extras": ["none"],
}


class InstrumentationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Tracked", slug="tracked")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="tracked-user", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.client.force_login(self.user)
        self.home_url = reverse("onboarding:home", args=[self.team.slug, self.book.slug])
        self.answers_url = reverse("onboarding:api_answers", args=[self.team.slug, self.book.slug])
        self.complete_url = reverse("onboarding:api_complete", args=[self.team.slug, self.book.slug])
        self.skip_url = reverse("onboarding:api_skip", args=[self.team.slug, self.book.slug])
        self.task_url = reverse("onboarding:api_task", args=[self.team.slug, self.book.slug])

    def post_json(self, url, payload=None):
        return self.client.post(
            url,
            data=json.dumps(payload or {}),
            content_type="application/json",
            headers={"accept": "application/json"},
        )

    def events(self, event_type):
        return list(AuditEvent.objects.filter(team=self.team, event_type=event_type).order_by("id"))


class FunnelEventsTest(InstrumentationTestCase):
    def test_opening_the_takeover_is_recorded_once(self):
        self.client.get(self.home_url)
        self.client.get(self.home_url)

        self.assertEqual(len(self.events(AuditEvent.ONBOARDING_STARTED)), 1)

    def test_moving_between_phases_records_the_one_left(self):
        """
        This is what makes the funnel answer "which question loses people" rather
        than just "how many finish".
        """
        self.post_json(self.answers_url, {"answers": {"housing": "rent"}, "question_phase": "income"})
        self.post_json(self.answers_url, {"answers": {"kids": "no"}, "question_phase": "household"})

        events = self.events(AuditEvent.ONBOARDING_PHASE_COMPLETED)
        self.assertEqual([e.metadata["phase"] for e in events], ["income"])
        self.assertEqual(events[0].metadata["next"], "household")

    def test_staying_on_a_phase_records_nothing(self):
        self.post_json(self.answers_url, {"answers": {"housing": "rent"}, "question_phase": "income"})
        self.post_json(self.answers_url, {"answers": {"kids": "no"}, "question_phase": "income"})

        self.assertEqual(self.events(AuditEvent.ONBOARDING_PHASE_COMPLETED), [])

    def test_completion_records_what_was_built(self):
        self.post_json(self.complete_url, {"answers": ANSWERS})

        event = self.events(AuditEvent.ONBOARDING_COMPLETED)[0]
        self.assertGreater(event.metadata["accounts"], 0)
        # The answers travel with it, so a question that drives nothing can be spotted.
        self.assertIn("housing", event.metadata["answers"])

    def test_skipping_records_where_they_were(self):
        self.post_json(self.answers_url, {"answers": {"housing": "rent"}, "question_phase": "household"})
        self.post_json(self.skip_url)

        event = self.events(AuditEvent.ONBOARDING_SKIPPED)[0]
        self.assertEqual(event.metadata["phase"], "household")

    def test_the_user_is_attributed(self):
        self.client.get(self.home_url)

        self.assertEqual(self.events(AuditEvent.ONBOARDING_STARTED)[0].user, self.user)


class TaskEventsTest(InstrumentationTestCase):
    def setUp(self):
        super().setUp()
        self.state = OnboardingState.objects.create(book=self.book)
        self.state.complete()
        self.state.save()

        group = AccountGroup.objects.create(book=self.book, name="Bank Accounts", account_type="asset")
        self.account = Account.objects.create(book=self.book, name="Chequing", account_group=group, has_feed=True)
        expenses = AccountGroup.objects.create(book=self.book, name="Regular", account_type="expense")
        self.category = Account.objects.create(book=self.book, name="Groceries", account_group=expenses)

    def do_the_work(self):
        BankTransaction.objects.create(
            book=self.book,
            account=self.account,
            posted_date=date(2026, 9, 1),
            amount=Decimal("42"),
            description="LOBLAWS",
            source=BankTransaction.SOURCE_CSV,
        )
        JournalEntry.objects.create(
            book=self.book, entry_date=date(2026, 9, 1), description="x", status=JournalEntry.STATUS_POSTED
        )
        Budget.objects.create(
            book=self.book, month=date(2026, 9, 1), category=self.category, budget_amount=Decimal("300")
        )

    def test_a_completed_task_is_recorded(self):
        self.do_the_work()
        self.post_json(self.task_url, {"slug": "report"})

        self.assertEqual(self.events(AuditEvent.ONBOARDING_TASK_COMPLETED)[0].metadata["task"], "report")

    def test_reporting_the_same_task_twice_records_once(self):
        self.do_the_work()
        self.post_json(self.task_url, {"slug": "report"})
        self.post_json(self.task_url, {"slug": "report"})

        self.assertEqual(len(self.events(AuditEvent.ONBOARDING_TASK_COMPLETED)), 1)

    def test_finishing_every_task_is_recorded_and_returns_a_summary(self):
        self.do_the_work()
        self.post_json(self.task_url, {"slug": "report"})
        response = self.post_json(self.task_url, {"slug": "net_worth"})

        data = response.json()
        self.assertTrue(data["finished"])
        self.assertEqual(data["summary"]["transactions"], 1)
        self.assertGreater(data["summary"]["accounts"], 0)

        event = self.events(AuditEvent.ONBOARDING_FINISHED)[0]
        self.assertEqual(event.metadata["reason"], "all_tasks_done")

    def test_an_unfinished_task_post_carries_no_summary(self):
        """The summary costs extra queries; it is only computed when it is needed."""
        self.do_the_work()
        response = self.post_json(self.task_url, {"slug": "report"})

        self.assertFalse(response.json()["finished"])
        self.assertIsNone(response.json()["summary"])

    def test_dismissing_is_recorded_as_such(self):
        response = self.post_json(self.task_url, {"action": "dismiss"})

        self.assertFalse(response.json()["active"])
        self.assertEqual(self.events(AuditEvent.ONBOARDING_FINISHED)[0].metadata["reason"], "dismissed")


class ResumeTest(InstrumentationTestCase):
    def setUp(self):
        super().setUp()
        self.state = OnboardingState.objects.create(book=self.book)
        self.state.complete()
        self.state.finish_tasks()
        self.state.save()

    def test_resuming_brings_the_rail_back(self):
        response = self.post_json(self.task_url, {"action": "resume"})

        self.assertTrue(response.json()["active"])
        self.assertTrue(OnboardingState.objects.get(book=self.book).shows_tasks)

    def test_resuming_keeps_the_work_already_done(self):
        self.state.mark_task("report")
        self.state.save()

        self.post_json(self.task_url, {"action": "resume"})

        self.assertIn("report", OnboardingState.objects.get(book=self.book).tasks_done)


class ResumeCardTest(InstrumentationTestCase):
    """The dashboard nudge that replaced the old three-step checklist."""

    def setUp(self):
        super().setUp()
        self.dashboard = reverse("web_book:home", args=[self.team.slug, self.book.slug])
        self.state = OnboardingState.objects.create(book=self.book)

    def test_offered_to_a_team_that_skipped_and_still_has_gaps(self):
        self.state.skip()
        self.state.save()

        self.assertTrue(self.client.get(self.dashboard).context["show_resume"])

    def test_not_offered_while_the_rail_is_already_up(self):
        """Two prompts for the same thing on one screen."""
        self.state.complete()
        self.state.save()

        self.assertFalse(self.client.get(self.dashboard).context["show_resume"])

    def test_not_offered_to_a_team_that_is_already_set_up(self):
        self.state.skip()
        self.state.save()

        group = AccountGroup.objects.create(book=self.book, name="Bank", account_type="asset")
        account = Account.objects.create(book=self.book, name="Chequing", account_group=group)
        expenses = AccountGroup.objects.create(book=self.book, name="Regular", account_type="expense")
        category = Account.objects.create(book=self.book, name="Groceries", account_group=expenses)
        BankTransaction.objects.create(
            book=self.book,
            account=account,
            posted_date=date(2026, 9, 1),
            amount=Decimal("1"),
            description="x",
            source=BankTransaction.SOURCE_CSV,
        )
        Budget.objects.create(book=self.book, month=date(2026, 9, 1), category=category, budget_amount=Decimal("1"))

        self.assertFalse(self.client.get(self.dashboard).context["show_resume"])

    def test_the_old_checklist_is_gone(self):
        """It duplicated the task rail, with none of its gates."""
        self.state.skip()
        self.state.save()

        self.assertNotContains(self.client.get(self.dashboard), "onboarding-checklist")
