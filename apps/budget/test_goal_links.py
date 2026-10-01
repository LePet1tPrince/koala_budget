"""
Goal-linked accounts (docs/goal-linked-accounts-plan.md): the flows of §3, the
link service's refusals, and the goal's numbers through `with_progress`.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team

from . import goal_links
from .goal_links import LinkError, LinkRow
from .linked import monthly_linked
from .models import Goal, GoalAccountLink, GoalAllocation
from .services import GoalService
from .unassigned import compute_unassigned

AUG = date(2026, 8, 1)
SEPT = date(2026, 9, 1)
OCT = date(2026, 10, 1)
TODAY = date(2026, 9, 30)
D = Decimal


class LinkedFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Linked Team", slug="linked-team")
        cls.book = cls.team.default_book
        assets = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        debts = AccountGroup.objects.create(book=cls.book, name="Cards", account_type="liability")
        equity = AccountGroup.objects.create(book=cls.book, name="Opening", account_type="goal")
        income = AccountGroup.objects.create(book=cls.book, name="Work", account_type="income")
        expense = AccountGroup.objects.create(book=cls.book, name="Living", account_type="expense")
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=assets)
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=assets)
        cls.savings2 = Account.objects.create(book=cls.book, name="Savings Two", account_group=assets)
        cls.vault = Account.objects.create(book=cls.book, name="Vault", account_group=assets)
        cls.card = Account.objects.create(book=cls.book, name="Visa", account_group=debts)
        cls.opening = Account.objects.create(book=cls.book, name="Opening Balance", account_group=equity)
        cls.interest = Account.objects.create(book=cls.book, name="Interest", account_group=income)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=expense)

        cls.post(date(2026, 8, 2), cls.checking, cls.opening, "10000")
        cls.post(date(2026, 8, 3), cls.savings, cls.opening, "1000")
        cls.goal = Goal.objects.create(book=cls.book, name="Rainy Day", target_amount=D("5000"))
        cls.other_goal = Goal.objects.create(book=cls.book, name="Trip", target_amount=D("3000"))

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="entry", status="posted")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=D(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=D(amount))
        return entry

    @classmethod
    def split(cls, day, lines):
        """`lines`: (account, dr, cr) tuples."""
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="split", status="posted")
        for account, dr, cr in lines:
            JournalLine.objects.create(
                book=cls.book, journal_entry=entry, account=account, dr_amount=D(dr), cr_amount=D(cr)
            )
        return entry

    def link(self, account=None, goal=None, start=SEPT, include=False):
        return GoalAccountLink.objects.create(
            book=self.book,
            goal=goal or self.goal,
            account=account or self.savings,
            start_date=start,
            include_starting_balance=include,
        )

    def set_outflow(self, outflow, goal=None):
        goal = goal or self.goal
        goal.outflow = outflow
        goal.save()

    def numbers(self, goal=None, month=SEPT):
        goal = goal or self.goal
        return Goal.objects.filter(pk=goal.pk).with_progress(month).values("allocated", "spent", "left").get()

    def unassigned(self, month=SEPT):
        return compute_unassigned(self.book, month).amount


class InflowTest(LinkedFixture):
    """Money arriving in a linked account adds to the goal (§3, left column)."""

    def setUp(self):
        self.link()
        self.before = self.unassigned()

    def test_transfer_in(self):
        self.post(date(2026, 9, 5), self.savings, self.checking, "500")
        self.assertEqual(self.numbers()["allocated"], D("500"))
        self.assertEqual(self.unassigned(), self.before - D("500"))

    def test_income_lands_in_the_goal(self):
        self.post(date(2026, 9, 5), self.savings, self.interest, "10")
        self.assertEqual(self.numbers()["allocated"], D("10"))
        # Net worth +10, goal +10.
        self.assertEqual(self.unassigned(), self.before)

    def test_adjustment(self):
        self.post(date(2026, 9, 5), self.savings, self.opening, "25")
        self.assertEqual(self.numbers()["allocated"], D("25"))
        self.post(date(2026, 9, 6), self.opening, self.savings, "5")
        self.assertEqual(self.numbers()["allocated"], D("20"))
        self.assertEqual(self.unassigned(), self.before)

    def test_refund_goes_back_to_its_envelope(self):
        self.post(date(2026, 9, 5), self.savings, self.groceries, "30")
        self.assertEqual(self.numbers()["allocated"], D("0"))

    def test_card_payment_into_savings_counts(self):
        # A liability on the other side is one of your accounts: a transfer.
        self.post(date(2026, 9, 5), self.savings, self.card, "40")
        self.assertEqual(self.numbers()["allocated"], D("40"))

    def test_outside_the_range(self):
        self.post(date(2026, 8, 31), self.savings, self.checking, "500")
        self.assertEqual(self.numbers()["allocated"], D("0"))
        link = GoalAccountLink.objects.get()
        link.end_date = date(2026, 9, 10)
        link.save()
        self.post(date(2026, 9, 11), self.savings, self.checking, "70")
        self.post(date(2026, 9, 10), self.savings, self.checking, "3")
        self.assertEqual(self.numbers()["allocated"], D("3"))

    def test_after_the_viewed_month(self):
        self.post(date(2026, 10, 2), self.savings, self.checking, "500")
        self.assertEqual(compute_unassigned(self.book, SEPT).goals, D("0"))
        self.assertEqual(compute_unassigned(self.book, OCT).goals, D("500"))

    def test_void_and_archived_dont_count(self):
        entry = self.post(date(2026, 9, 5), self.savings, self.checking, "500")
        entry.status = JournalEntry.STATUS_VOID
        entry.save()
        self.assertEqual(self.numbers()["allocated"], D("0"))
        entry = self.post(date(2026, 9, 6), self.savings, self.checking, "80")
        BankTransaction.objects.create(
            book=self.book,
            account=self.savings,
            posted_date=date(2026, 9, 6),
            amount=D("-80"),
            description="transfer",
            journal_entry=entry,
            is_archived=True,
        )
        self.assertEqual(self.numbers()["allocated"], D("0"))

    def test_deleting_the_entry_removes_it(self):
        entry = self.post(date(2026, 9, 5), self.savings, self.checking, "500")
        entry.delete()
        self.assertEqual(self.numbers()["allocated"], D("0"))


class OutflowTest(LinkedFixture):
    """Money leaving for your other accounts follows the goal's setting."""

    def setUp(self):
        self.link()
        self.post(date(2026, 9, 2), self.savings, self.checking, "1000")

    def test_withdraw(self):
        before = self.unassigned()
        self.post(date(2026, 9, 5), self.checking, self.savings, "200")
        self.assertEqual(self.numbers(), {"allocated": D("800"), "spent": D("0"), "left": D("800")})
        self.assertEqual(self.unassigned(), before + D("200"))

    def test_spend(self):
        self.set_outflow(Goal.OUTFLOW_SPEND)
        before = self.unassigned()
        self.post(date(2026, 9, 5), self.checking, self.savings, "200")
        self.assertEqual(self.numbers(), {"allocated": D("1000"), "spent": D("200"), "left": D("800")})
        self.assertEqual(self.unassigned(), before + D("200"))

    def test_ignore(self):
        self.set_outflow(Goal.OUTFLOW_IGNORE)
        before = self.unassigned()
        self.post(date(2026, 9, 5), self.checking, self.savings, "200")
        self.assertEqual(self.numbers(), {"allocated": D("1000"), "spent": D("0"), "left": D("1000")})
        self.assertEqual(self.unassigned(), before)

    def test_withdraw_and_spend_agree_on_unassigned(self):
        self.post(date(2026, 9, 5), self.card, self.savings, "300")
        withdrawn = self.unassigned()
        self.set_outflow(Goal.OUTFLOW_SPEND)
        self.assertEqual(self.unassigned(), withdrawn)

    def test_expense_paid_from_the_account_is_not_counted(self):
        for outflow in (Goal.OUTFLOW_WITHDRAW, Goal.OUTFLOW_SPEND, Goal.OUTFLOW_IGNORE):
            self.set_outflow(outflow)
            self.post(date(2026, 9, 5), self.groceries, self.savings, "100")
            self.assertEqual(self.numbers()["left"], D("1000"), outflow)

    def test_goal_spending_from_the_account(self):
        before = self.unassigned()
        self.post(date(2026, 9, 5), self.goal.account, self.savings, "400")
        self.assertEqual(self.numbers(), {"allocated": D("1000"), "spent": D("400"), "left": D("600")})
        self.assertEqual(self.unassigned(), before)

    def test_card_paid_after_goal_spending(self):
        """§2 D6: only "leave the goal alone" counts the purchase once."""
        self.post(date(2026, 9, 5), self.goal.account, self.card, "300")
        self.post(date(2026, 9, 20), self.card, self.savings, "300")
        expected = {Goal.OUTFLOW_WITHDRAW: "400", Goal.OUTFLOW_SPEND: "400", Goal.OUTFLOW_IGNORE: "700"}
        for outflow, left in expected.items():
            self.set_outflow(outflow)
            self.assertEqual(self.numbers()["left"], D(left), outflow)

    def test_income_reversal_and_negative_adjustment_always_come_out(self):
        self.set_outflow(Goal.OUTFLOW_IGNORE)
        self.post(date(2026, 9, 5), self.interest, self.savings, "4")
        self.post(date(2026, 9, 6), self.opening, self.savings, "6")
        self.assertEqual(self.numbers()["allocated"], D("990"))


class BetweenAccountsTest(LinkedFixture):
    def test_two_accounts_of_the_same_goal(self):
        self.link()
        self.link(account=self.savings2)
        self.post(date(2026, 9, 2), self.savings, self.checking, "500")
        for outflow in (Goal.OUTFLOW_WITHDRAW, Goal.OUTFLOW_SPEND, Goal.OUTFLOW_IGNORE):
            self.set_outflow(outflow)
            self.post(date(2026, 9, 5), self.savings2, self.savings, "100")
            self.assertEqual(self.numbers(), {"allocated": D("500"), "spent": D("0"), "left": D("500")}, outflow)

    def test_account_of_another_goal_is_always_a_reallocation(self):
        self.link()
        self.link(account=self.vault, goal=self.other_goal)
        self.post(date(2026, 9, 2), self.savings, self.checking, "500")
        before = self.unassigned()
        for outflow in (Goal.OUTFLOW_SPEND, Goal.OUTFLOW_IGNORE, Goal.OUTFLOW_WITHDRAW):
            self.set_outflow(outflow)
            self.post(date(2026, 9, 5), self.vault, self.savings, "100")
        self.assertEqual(self.numbers(), {"allocated": D("200"), "spent": D("0"), "left": D("200")})
        self.assertEqual(self.numbers(self.other_goal)["allocated"], D("300"))
        self.assertEqual(self.unassigned(), before)


class SplitTest(LinkedFixture):
    def setUp(self):
        self.link()

    def test_bank_line_takes_only_the_legs_that_count(self):
        self.split(
            date(2026, 9, 5),
            [(self.savings, "0", "150"), (self.groceries, "100", "0"), (self.checking, "50", "0")],
        )
        self.assertEqual(self.numbers()["allocated"], D("-50"))

    def test_a_leg_takes_its_own_amount(self):
        self.split(
            date(2026, 9, 5),
            [
                (self.checking, "2000", "0"),
                (self.savings, "500", "0"),
                (self.groceries, "500", "0"),
                (self.interest, "0", "3000"),
            ],
        )
        self.assertEqual(self.numbers()["allocated"], D("500"))

    def test_both_sides_split_pro_rata(self):
        # savings dr 100 + groceries dr 200 / checking cr 150 + interest cr 150:
        # savings' other side is entirely countable.
        self.split(
            date(2026, 9, 5),
            [
                (self.savings, "100", "0"),
                (self.groceries, "200", "0"),
                (self.checking, "0", "150"),
                (self.interest, "0", "150"),
            ],
        )
        self.assertEqual(self.numbers()["allocated"], D("100"))


class StartingBalanceTest(LinkedFixture):
    def test_counts_the_balance_before_the_start_date(self):
        self.link(include=True)
        self.assertEqual(self.numbers()["allocated"], D("1000"))
        self.assertEqual(self.numbers(month=AUG)["allocated"], D("1000"))
        self.assertEqual(compute_unassigned(self.book, AUG).goals, D("0"))
        self.assertEqual(compute_unassigned(self.book, SEPT).goals, D("1000"))

    def test_follows_an_edit_before_the_start(self):
        self.link(include=True)
        self.post(date(2026, 8, 20), self.groceries, self.savings, "100")
        self.assertEqual(self.numbers()["allocated"], D("900"))

    def test_retroactive_start(self):
        self.post(date(2026, 8, 20), self.savings, self.checking, "250")
        self.link(start=date(2026, 8, 10), include=True)
        # 1,000 before Aug 10, then the 250 transfer.
        self.assertEqual(self.numbers()["allocated"], D("1250"))


class MonthlyTest(LinkedFixture):
    def test_monthly_breakdown(self):
        self.link(include=True)
        self.set_outflow(Goal.OUTFLOW_SPEND)
        self.post(date(2026, 9, 5), self.savings, self.checking, "300")
        self.post(date(2026, 10, 5), self.checking, self.savings, "50")
        result = monthly_linked([self.goal.pk])[self.goal.pk]
        self.assertEqual(result[SEPT], {"linked": D("1300"), "spent": D("0")})
        self.assertEqual(result[OCT], {"linked": D("0"), "spent": D("50")})

    def test_with_progress_month_split(self):
        self.link()
        GoalAllocation.objects.create(book=self.book, goal=self.goal, month=AUG, amount=D("100"))
        self.post(date(2026, 9, 5), self.savings, self.checking, "300")
        goal = Goal.objects.filter(pk=self.goal.pk).with_progress(SEPT).get()
        self.assertEqual(goal.saved_previous, D("100"))
        self.assertEqual(goal.saved_this_month, D("300"))


class ManualAllocationTest(LinkedFixture):
    def test_assign_and_withdraw_leave_accounts_alone(self):
        self.link()
        service = GoalService(self.book)
        service.add_to_allocation(self.goal, SEPT, D("200"))
        service.add_to_allocation(self.goal, SEPT, D("-50"))
        self.assertEqual(self.numbers()["allocated"], D("150"))
        self.assertEqual(self.savings.balance, D("1000"))


class CloseTest(LinkedFixture):
    def test_close_ends_links_then_releases_the_final_left(self):
        self.link(start=date(2026, 9, 1))
        self.post(date(2026, 9, 5), self.savings, self.checking, "300")
        result = GoalService(self.book).close(self.goal, SEPT)
        self.assertEqual(result["released"], D("300"))
        link = GoalAccountLink.objects.get()
        self.assertEqual(link.end_date, timezone.localdate())
        self.assertEqual(self.numbers()["left"], D("0"))


class SetLinksTest(LinkedFixture):
    def rows(self, *accounts, start=SEPT, include=True):
        return [LinkRow(account=a, start_date=start, include_starting_balance=include) for a in accounts]

    def test_links_updates_and_unlinks(self):
        changes = goal_links.set_links(self.goal, self.rows(self.savings, self.savings2), today=TODAY)
        self.assertEqual(len(changes.linked), 2)
        changes = goal_links.set_links(self.goal, self.rows(self.savings, start=date(2026, 9, 2)), today=TODAY)
        self.assertEqual(len(changes.updated), 1)
        self.assertEqual(len(changes.unlinked), 1)
        # Made today, so dropped rather than ended.
        self.assertFalse(GoalAccountLink.objects.filter(account=self.savings2).exists())

    def test_an_older_link_is_ended_not_dropped(self):
        link = self.link()
        GoalAccountLink.objects.filter(pk=link.pk).update(created_at=timezone.now() - timedelta(days=3))
        goal_links.set_links(self.goal, [], today=timezone.localdate())
        link.refresh_from_db()
        self.assertEqual(link.end_date, timezone.localdate())

    def test_refusals(self):
        other_team = Team.objects.create(name="Other", slug="other-linked")
        foreign_group = AccountGroup.objects.create(book=other_team.default_book, name="Cash", account_type="asset")
        foreign = Account.objects.create(book=other_team.default_book, name="Foreign", account_group=foreign_group)
        archived = Account.objects.create(
            book=self.book, name="Old", account_group=self.savings.account_group, is_archived=True
        )
        system = Account.objects.create(
            book=self.book, name="Sys", account_group=self.savings.account_group, is_system=True
        )
        self.link(account=self.vault, goal=self.other_goal)
        cases = {
            "another book": self.rows(foreign),
            "liability": self.rows(self.card),
            "expense": self.rows(self.groceries),
            "system": self.rows(system),
            "archived": self.rows(archived),
            "future": self.rows(self.savings, start=TODAY + timedelta(days=1)),
            "taken": self.rows(self.vault),
            "twice": self.rows(self.savings, self.savings),
        }
        for name, rows in cases.items():
            with self.subTest(name), self.assertRaises(LinkError):
                goal_links.set_links(self.goal, rows, today=TODAY)
        self.assertFalse(GoalAccountLink.objects.filter(goal=self.goal).exists())

    def test_ranges_never_overlap(self):
        GoalAccountLink.objects.create(
            book=self.book, goal=self.other_goal, account=self.savings, start_date=AUG, end_date=date(2026, 9, 10)
        )
        with self.assertRaises(LinkError):
            goal_links.set_links(self.goal, self.rows(self.savings, start=date(2026, 9, 10)), today=TODAY)
        goal_links.set_links(self.goal, self.rows(self.savings, start=date(2026, 9, 11)), today=TODAY)

    def test_closed_goal(self):
        self.goal.closed_at = timezone.now()
        self.goal.save()
        with self.assertRaises(LinkError):
            goal_links.set_links(self.goal, self.rows(self.savings), today=TODAY)

    def test_preview_writes_nothing(self):
        self.post(date(2026, 9, 5), self.savings, self.checking, "300")
        result = goal_links.preview(
            self.book, self.goal, self.rows(self.savings, start=date(2026, 9, 1)), Goal.OUTFLOW_WITHDRAW, SEPT, TODAY
        )
        self.assertEqual(result["adds"], D("1300"))
        self.assertEqual(result["unassigned_after"], result["unassigned_before"] - D("1300"))
        self.assertFalse(GoalAccountLink.objects.exists())

    def test_preview_for_a_new_goal(self):
        count = Goal.objects.count()
        result = goal_links.preview(self.book, None, self.rows(self.savings), Goal.OUTFLOW_WITHDRAW, SEPT, TODAY)
        self.assertEqual(result["adds"], D("1000"))
        self.assertEqual(Goal.objects.count(), count)

    def test_eligible_accounts(self):
        self.link(account=self.vault, goal=self.other_goal)
        accounts = {a.name: a for a in goal_links.eligible_accounts(self.book, self.goal)}
        self.assertEqual(set(accounts), {"Checking", "Savings", "Savings Two", "Vault"})
        self.assertEqual(accounts["Vault"].feeds_goal_name, "Trip")
        self.assertIsNone(accounts["Savings"].feeds_goal_id)
