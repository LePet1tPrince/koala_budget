"""
Tests for the guided-task gates.

The gates exist so the walkthrough never walks a user into an empty screen. The
distinction they encode -- import unlocks working *on* transactions, but only
categorizing unlocks anything that shows a *balance* -- is the part worth
protecting, so most of these tests are about that boundary.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.budget.models import Budget
from apps.journal.models import JournalEntry
from apps.onboarding.services.gates import (
    AVAILABLE,
    DONE,
    LOCKED,
    TASKS,
    can_set_opening_balances,
    task_state,
)
from apps.teams.models import Team


class GateTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Gated", slug="gated")
        cls.book = cls.team.default_book
        assets = AccountGroup.objects.create(book=cls.book, name="Bank Accounts", account_type="asset")
        expenses = AccountGroup.objects.create(book=cls.book, name="Regular Expenses", account_type="expense")
        cls.account = Account.objects.create(
            book=cls.book, name="Chequing Account", account_group=assets, has_feed=True
        )
        cls.category = Account.objects.create(book=cls.book, name="Groceries", account_group=expenses)

    def states(self, tasks_done=None):
        return {t["slug"]: t["state"] for t in task_state(self.book, tasks_done)}

    def add_transaction(self):
        return BankTransaction.objects.create(
            book=self.book,
            account=self.account,
            posted_date=date(2026, 9, 1),
            amount=Decimal("25.00"),
            description="LOBLAWS",
            source=BankTransaction.SOURCE_CSV,
        )

    def add_entry(self, status=JournalEntry.STATUS_POSTED):
        return JournalEntry.objects.create(
            book=self.book, entry_date=date(2026, 9, 1), description="groceries", status=status
        )


class EmptyTeamTest(GateTestCase):
    def test_only_the_import_task_is_open(self):
        states = self.states()
        self.assertEqual(states["import"], AVAILABLE)
        self.assertEqual(states["categorize"], LOCKED)
        self.assertEqual(states["budget"], LOCKED)
        self.assertEqual(states["report"], LOCKED)
        self.assertEqual(states["net_worth"], LOCKED)

    def test_locked_tasks_say_why(self):
        for task in task_state(self.book):
            with self.subTest(task=task["slug"]):
                if task["state"] == LOCKED:
                    self.assertTrue(task["reason"], f"{task['slug']} is locked with no reason given")

    def test_open_tasks_carry_no_reason(self):
        for task in task_state(self.book):
            if task["state"] != LOCKED:
                with self.subTest(task=task["slug"]):
                    self.assertEqual(task["reason"], "")

    def test_every_task_is_reported(self):
        self.assertEqual([t["slug"] for t in task_state(self.book)], [t.slug for t in TASKS])


class AfterImportTest(GateTestCase):
    def setUp(self):
        self.add_transaction()

    def test_import_is_done_and_working_tasks_open(self):
        states = self.states()
        self.assertEqual(states["import"], DONE)
        self.assertEqual(states["categorize"], AVAILABLE)
        self.assertEqual(states["budget"], AVAILABLE)

    def test_balance_tasks_stay_locked(self):
        """
        An uncategorized import moves nothing. Opening the report here would show
        an empty statement and a flat net-worth line at the payoff moment.
        """
        states = self.states()
        self.assertEqual(states["report"], LOCKED)
        self.assertEqual(states["net_worth"], LOCKED)

    def test_opening_balances_are_refused(self):
        self.assertFalse(can_set_opening_balances(self.book))


class AfterCategorizingTest(GateTestCase):
    def setUp(self):
        self.add_transaction()
        self.add_entry()

    def test_everything_is_open(self):
        states = self.states()
        self.assertEqual(states["categorize"], DONE)
        self.assertEqual(states["report"], AVAILABLE)
        self.assertEqual(states["net_worth"], AVAILABLE)

    def test_opening_balances_are_allowed(self):
        self.assertTrue(can_set_opening_balances(self.book))

    def test_budget_completes_when_a_budget_row_exists(self):
        self.assertEqual(self.states()["budget"], AVAILABLE)

        Budget.objects.create(
            book=self.book, month=date(2026, 9, 1), category=self.category, budget_amount=Decimal("400.00")
        )
        self.assertEqual(self.states()["budget"], DONE)


class VoidedEntryTest(GateTestCase):
    """
    A voided entry is excluded from every balance in the app, so it must not
    count as having categorized anything here either -- otherwise the gate opens
    onto exactly the empty report it exists to prevent.
    """

    def setUp(self):
        self.add_transaction()
        self.add_entry(status=JournalEntry.STATUS_VOID)

    def test_voided_entry_does_not_unlock_the_balance_tasks(self):
        states = self.states()
        self.assertEqual(states["report"], LOCKED)
        self.assertEqual(states["net_worth"], LOCKED)

    def test_voided_entry_does_not_allow_opening_balances(self):
        self.assertFalse(can_set_opening_balances(self.book))


class ManualCompletionTest(GateTestCase):
    def test_recorded_tasks_read_as_done(self):
        """Report and net worth are 'go and look', which only the client can report."""
        self.add_transaction()
        self.add_entry()

        self.assertEqual(self.states(["report"])["report"], DONE)

    def test_a_recorded_task_stays_done_after_its_data_goes(self):
        """
        Being sent back through a step you already finished is worse than a
        checklist that is slightly out of date.
        """
        self.add_transaction()
        self.assertEqual(self.states()["import"], DONE)

        BankTransaction.objects.filter(book=self.book).delete()
        self.assertEqual(self.states(["import"])["import"], DONE)


class TeamIsolationTest(GateTestCase):
    def test_another_teams_data_does_not_unlock_anything(self):
        other = Team.objects.create(name="Other", slug="other-gated")
        other_book = other.default_book
        group = AccountGroup.objects.create(book=other_book, name="Bank Accounts", account_type="asset")
        account = Account.objects.create(book=other_book, name="Chequing", account_group=group, has_feed=True)
        BankTransaction.objects.create(
            book=other_book,
            account=account,
            posted_date=date(2026, 9, 1),
            amount=Decimal("10.00"),
            description="THEIRS",
            source=BankTransaction.SOURCE_CSV,
        )

        self.assertEqual(self.states()["categorize"], LOCKED)
