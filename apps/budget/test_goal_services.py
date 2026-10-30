"""
Unit tests for `goal_cards.py` and `goal_funds.py`: a goal card's figures and
moving money into and out of a goal, called without a request.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Account, AccountGroup
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team

from . import goal_cards, goal_funds
from .ledger import goal_allocation, set_goal_allocation
from .models import Goal

AUG, SEPT, OCT = date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)
D = Decimal


class GoalServicesTest(TestCase):
    """Checking holds 10,000 of opening balance; "Car" has 1,000 in August and 500 in September."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Team.objects.create(name="Goal Svc", slug="goal-svc").default_book
        assets = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        equity = AccountGroup.objects.create(book=cls.book, name="Opening Balances", account_type="goal")
        checking = Account.objects.create(book=cls.book, name="Checking", account_group=assets)
        opening = Account.objects.create(book=cls.book, name="Opening Balance", account_group=equity)
        entry = JournalEntry.objects.create(book=cls.book, entry_date=AUG, status="posted")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=checking, dr_amount=D("10000"))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=opening, cr_amount=D("10000"))

        cls.car = Goal.objects.create(book=cls.book, name="Car", target_amount=D("5000"))
        set_goal_allocation(cls.book, cls.car, AUG, D("1000"))
        set_goal_allocation(cls.book, cls.car, SEPT, D("500"))

    def test_streak_counts_back_from_the_month_and_forgives_an_unfunded_one(self):
        self.assertEqual(goal_cards.goal_streak({AUG, SEPT}, SEPT), 2)
        self.assertEqual(goal_cards.goal_streak({AUG, SEPT}, OCT), 2)
        self.assertEqual(goal_cards.goal_streak({AUG}, OCT), 0)

    def test_card_progress_with_and_without_a_target(self):
        self.assertEqual(goal_cards.goal_card_progress(self.car, D("1500"), D("0")), (30.0, D("3500")))
        open_ended = Goal(book=self.book, name="Fun", target_amount=D("0"), monthly_contribution=D("200"))
        self.assertEqual(goal_cards.goal_card_progress(open_ended, D("1500"), D("50")), (25.0, D("150")))
        self.assertEqual(goal_cards.goal_card_progress(Goal(target_amount=D("0")), D("1"), D("1")), (0, D("0")))

    def test_goal_items_for_the_page(self):
        goals = list(Goal.objects.filter(book=self.book).with_progress(SEPT))
        (item,) = goal_cards.goal_items(self.book, goals, SEPT)
        self.assertEqual((item["saved"], item["remaining"], item["pct"]), (D("1500"), D("3500"), 30.0))
        self.assertEqual(item["streak"], 2)
        self.assertEqual(item["state"], self.car.state)
        self.assertIn(f"a%3A{self.car.account_id}", item["spending_url"])

    def test_assign_adds_to_the_months_allocation(self):
        amount, result = goal_funds.assign(self.book, self.car, SEPT, "250")
        self.assertEqual(amount, D("250.00"))
        self.assertEqual(goal_allocation(self.book, self.car, SEPT), D("750"))
        self.assertEqual((result["old_saved"], result["new_saved"], result["this_month"]), (1500.0, 1750.0, 750.0))

    def test_quick_assign_is_capped_at_what_the_goal_needs(self):
        amount, result = goal_funds.assign(self.book, self.car, SEPT)
        self.assertEqual(amount, D("3500.00"))
        self.assertTrue(result["completed"])

    def test_assign_refusals(self):
        for raw in ("-5", "0", "lots"):
            with self.subTest(raw=raw), self.assertRaisesMessage(goal_funds.GoalFundsError, "Invalid amount."):
                goal_funds.assign(self.book, self.car, SEPT, raw)
        archived = Goal.objects.create(book=self.book, name="Old", target_amount=D("1"), is_archived=True)
        with self.assertRaisesMessage(goal_funds.GoalFundsError, "no longer active"):
            goal_funds.assign(self.book, archived, SEPT, "1")

    def test_withdraw_goes_against_the_month_and_is_capped_at_left(self):
        amount, result = goal_funds.withdraw(self.book, self.car, OCT, "100")
        self.assertEqual(goal_allocation(self.book, self.car, OCT), D("-100"))
        self.assertEqual(result["new_saved"], 1400.0)
        with self.assertRaisesMessage(goal_funds.GoalFundsError, "only has $1,400.00 left"):
            goal_funds.withdraw(self.book, self.car, OCT, "5000")
        amount, _ = goal_funds.withdraw(self.book, self.car, OCT)
        self.assertEqual(amount, D("1400.00"))
        with self.assertRaisesMessage(goal_funds.GoalFundsError, "Nothing left"):
            goal_funds.withdraw(self.book, self.car, OCT)
