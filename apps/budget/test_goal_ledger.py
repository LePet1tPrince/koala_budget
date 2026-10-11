"""The goal ledger: saving entries booked from plans and linked accounts (docs/goals-ledger-plan.md)."""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_SAVING, Account, AccountGroup
from apps.journal.models import JournalEntry, JournalLine
from apps.journal.services import voiding
from apps.journal.services.simple_edit import EditRefused, delete_transaction, set_status
from apps.reports.services import ReportService
from apps.teams.models import Team

from . import goal_ledger
from .models import Goal, GoalAccountLink, GoalAllocation, GoalSaving
from .services import GoalService, NetWorthService

AUG = date(2026, 8, 1)
SEPT = date(2026, 9, 1)
D = Decimal


class LedgerFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Ledger Team", slug="ledger-team")
        cls.book = cls.team.default_book
        assets = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        equity = AccountGroup.objects.create(book=cls.book, name="Opening", account_type="goal")
        expense = AccountGroup.objects.create(book=cls.book, name="Living", account_type="expense")
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=assets)
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=assets)
        cls.opening = Account.objects.create(book=cls.book, name="Opening Balance", account_group=equity)
        cls.car_repair = Account.objects.create(book=cls.book, name="Car repair", account_group=expense)
        cls.post(date(2026, 8, 2), cls.checking, cls.opening, "10000")
        cls.goal = Goal.objects.create(book=cls.book, name="Car", target_amount=D("5000"))

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="entry", status="posted")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=D(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=D(amount))
        return entry

    def plan(self, month, amount):
        allocation, _ = GoalAllocation.objects.get_or_create(book=self.book, goal=self.goal, month=month)
        allocation.amount = D(amount)
        allocation.save()

    def link(self, start=SEPT, include=False):
        return GoalAccountLink.objects.create(
            book=self.book, goal=self.goal, account=self.savings, start_date=start, include_starting_balance=include
        )

    def saving_entry(self, month=SEPT):
        row = GoalSaving.objects.filter(goal=self.goal, month=month, kind=GoalSaving.KIND_SAVING).first()
        return row.entry if row else None

    def fund_balance(self):
        totals = JournalLine.objects.filter(account=self.goal.account).aggregate(
            total=Sum(F("cr_amount") - F("dr_amount"))
        )
        return totals["total"] or D("0")

    def left(self, month=SEPT):
        return Goal.objects.filter(pk=self.goal.pk).with_progress(month).values_list("left", flat=True).get()

    def snapshot(self):
        return sorted(
            JournalLine.objects.filter(journal_entry__source=JournalEntry.SOURCE_GOAL).values_list(
                "journal_entry_id", "account_id", "dr_amount", "cr_amount", "journal_entry__entry_date"
            )
        )


class SavingEntryTest(LedgerFixture):
    def test_a_goal_gets_a_saving_account(self):
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.saving_account.name, "Saving: Car")
        self.assertEqual(self.goal.saving_account.account_group.account_type, ACCOUNT_TYPE_SAVING)
        self.assertTrue(self.goal.saving_account.is_system)

    def test_a_plan_books_dr_saving_cr_fund_on_the_first(self):
        self.plan(SEPT, "400")
        entry = self.saving_entry()
        self.assertEqual(entry.source, JournalEntry.SOURCE_GOAL)
        self.assertEqual(entry.entry_date, SEPT)
        lines = {line.account_id: (line.dr_amount, line.cr_amount) for line in entry.lines.all()}
        self.assertEqual(lines[self.goal.saving_account_id], (D("400"), D("0")))
        self.assertEqual(lines[self.goal.account_id], (D("0"), D("400")))

    def test_the_fund_balance_is_what_is_left(self):
        self.plan(SEPT, "400")
        self.post(date(2026, 9, 10), self.goal.account, self.checking, "150")
        self.assertEqual(self.fund_balance(), D("250"))
        self.assertEqual(self.left(), D("250"))

    def test_changing_the_plan_changes_the_entry_in_place(self):
        self.plan(SEPT, "400")
        entry_id = self.saving_entry().pk
        self.plan(SEPT, "650")
        self.assertEqual(self.saving_entry().pk, entry_id)
        self.assertEqual(self.fund_balance(), D("650"))

    def test_a_zero_plan_removes_the_entry(self):
        self.plan(SEPT, "400")
        self.plan(SEPT, "0")
        self.assertIsNone(self.saving_entry())
        self.assertFalse(JournalEntry.objects.filter(source=JournalEntry.SOURCE_GOAL).exists())

    def test_a_withdrawal_flips_the_sides(self):
        with transaction.atomic():
            GoalService(self.book).adjust(self.goal, SEPT, D("-100"))
        lines = {line.account_id: (line.dr_amount, line.cr_amount) for line in self.saving_entry().lines.all()}
        self.assertEqual(lines[self.goal.account_id], (D("100"), D("0")))

    def test_saving_never_moves_net_worth(self):
        before = NetWorthService(self.book).get_net_worth(SEPT)
        self.plan(SEPT, "400")
        self.assertEqual(NetWorthService(self.book).get_net_worth(SEPT), before)

    def test_rebuilding_changes_nothing(self):
        self.link()
        self.plan(SEPT, "400")
        self.post(date(2026, 9, 5), self.savings, self.checking, "600")
        before = self.snapshot()
        goal_ledger.rebuild_book(self.book)
        goal_ledger.rebuild_book(self.book)
        self.assertEqual(self.snapshot(), before)


class MaxRuleTest(LedgerFixture):
    def setUp(self):
        self.link()

    def test_moving_more_than_the_plan_saves_what_moved(self):
        self.plan(SEPT, "400")
        self.post(date(2026, 9, 5), self.savings, self.checking, "600")
        self.assertEqual(self.fund_balance(), D("600"))

    def test_moving_less_than_the_plan_saves_the_plan(self):
        self.plan(SEPT, "400")
        self.post(date(2026, 9, 5), self.savings, self.checking, "100")
        self.assertEqual(self.fund_balance(), D("400"))

    def test_assigning_on_top_of_a_transfer_adds_in_full(self):
        self.plan(SEPT, "100")
        self.post(date(2026, 9, 5), self.savings, self.checking, "300")
        with transaction.atomic():
            GoalService(self.book).add_to_allocation(self.goal, SEPT, D("200"))
        self.assertEqual(self.fund_balance(), D("500"))

    def test_money_leaving_the_account_comes_out(self):
        self.post(date(2026, 9, 5), self.savings, self.checking, "600")
        self.post(date(2026, 9, 9), self.checking, self.savings, "250")
        self.assertEqual(self.fund_balance(), D("350"))


class FollowsTheLinkedAccountTest(LedgerFixture):
    def setUp(self):
        self.link()
        self.entry = self.post(date(2026, 9, 5), self.savings, self.checking, "600")

    def test_editing_the_amount(self):
        for line in self.entry.lines.all():
            line.dr_amount = D("700") if line.dr_amount else D("0")
            line.cr_amount = D("700") if line.cr_amount else D("0")
            line.save()
        self.assertEqual(self.fund_balance(), D("700"))

    def test_re_dating_it_into_another_month(self):
        self.entry.entry_date = date(2026, 10, 3)
        self.entry.save()
        self.assertIsNone(self.saving_entry(SEPT))
        self.assertEqual(self.saving_entry(date(2026, 10, 1)).lines.get(account=self.goal.account).cr_amount, D("600"))

    def test_voiding_and_restoring_it(self):
        voiding.void(entries=[self.entry])
        self.assertEqual(self.fund_balance(), D("0"))
        voiding.restore(entries=[self.entry])
        self.assertEqual(self.fund_balance(), D("600"))

    def test_deleting_it(self):
        self.entry.delete()
        self.assertEqual(self.fund_balance(), D("0"))

    def test_unlinking_the_account_before_it(self):
        GoalAccountLink.objects.filter(goal=self.goal).delete()
        self.assertEqual(self.fund_balance(), D("0"))

    def test_a_batch_runs_each_sync_once(self):
        with goal_ledger.batch():
            self.post(date(2026, 9, 6), self.savings, self.checking, "50")
            self.post(date(2026, 9, 7), self.savings, self.checking, "50")
            self.assertEqual(self.fund_balance(), D("600"))  # not yet
        self.assertEqual(self.fund_balance(), D("700"))


class StartingBalanceTest(LedgerFixture):
    def test_counted_balance_is_equity_to_equity(self):
        self.post(date(2026, 8, 3), self.savings, self.checking, "1000")
        self.link(include=True)
        row = GoalSaving.objects.get(goal=self.goal, kind=GoalSaving.KIND_STARTING)
        accounts = {
            line.account.account_group.account_type for line in row.entry.lines.select_related("account__account_group")
        }
        self.assertEqual(accounts, {"goal"})
        self.assertEqual(self.fund_balance(), D("1000"))
        data = ReportService(self.book).get_income_statement_data(AUG, date(2026, 9, 30))
        self.assertEqual(data["total_expenses"], D("0"))

    def test_editing_history_before_the_start_moves_it(self):
        entry = self.post(date(2026, 8, 3), self.savings, self.checking, "1000")
        self.link(include=True)
        entry.entry_date = date(2026, 9, 3)  # now inside the link's range: a move, not a balance
        entry.save()
        self.assertFalse(GoalSaving.objects.filter(goal=self.goal, kind=GoalSaving.KIND_STARTING).exists())
        self.assertEqual(self.fund_balance(), D("1000"))


class GuardTest(LedgerFixture):
    def setUp(self):
        self.plan(SEPT, "400")
        self.entry = self.saving_entry()

    def test_the_transactions_page_cannot_delete_or_void_it(self):
        with self.assertRaises(EditRefused):
            delete_transaction(self.entry, book=self.book)
        with self.assertRaises(EditRefused):
            set_status(self.entry, JournalEntry.STATUS_VOID, book=self.book)

    def test_voiding_refuses_it(self):
        with self.assertRaises(voiding.VoidRefused):
            voiding.void(entries=[self.entry])


class DeleteGoalTest(LedgerFixture):
    def test_deleting_a_goal_takes_its_entries_and_accounts(self):
        self.plan(SEPT, "400")
        saving_account_id = Goal.objects.get(pk=self.goal.pk).saving_account_id
        self.assertIsNone(GoalService(self.book).delete_blocked_reason(self.goal))
        GoalService(self.book).delete(self.goal)
        self.assertFalse(JournalEntry.objects.filter(source=JournalEntry.SOURCE_GOAL).exists())
        self.assertFalse(Account.objects.filter(pk=saving_account_id).exists())
