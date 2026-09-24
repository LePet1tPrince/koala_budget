"""
Phase 3: deleting a team's books (§4.2, §4.3, §7 Phase 3).
"""

from django.test import TestCase

from apps.accounts.models import Account, AccountGroup, Institution, Payee
from apps.bank_feed.models import BankTransaction, TransferMatchDismissal
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.journal.models import JournalEntry, JournalLine
from apps.plaid.models import PlaidAccount, PlaidItem
from apps.portability.services.wipe import wipe_book

from .db_fixtures import build_db_fixture_team, make_team


class WipeTeamTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user, cls.handles = build_db_fixture_team()
        cls.book = cls.team.default_book
        # A Plaid connection, to prove the wipe disconnects it (§4.2 step 3).
        item = PlaidItem.objects.create(
            book=cls.book, plaid_item_id="item-1", access_token="secret", institution_name="Tangerine"
        )
        PlaidAccount.objects.create(
            book=cls.book,
            plaid_account_id="plaid-acct-1",
            item=item,
            account_id=cls.handles["chequing"],
            name="Chequing",
            subtype="checking",
            type="depository",
        )
        # A second, untouched team -- proves the wipe is team-scoped.
        cls.other_team, cls.other_user, cls.other_handles = build_db_fixture_team("Other Team", "other-team")
        cls.other_book = cls.other_team.default_book

    def test_wipe_deletes_everything_for_the_team(self):
        wipe_book(self.book)
        self.assertFalse(Account.objects.filter(book=self.book).exists())
        self.assertFalse(AccountGroup.objects.filter(book=self.book).exists())
        self.assertFalse(Institution.objects.filter(book=self.book).exists())
        self.assertFalse(Payee.objects.filter(book=self.book).exists())
        self.assertFalse(JournalEntry.objects.filter(book=self.book).exists())
        self.assertFalse(JournalLine.objects.filter(book=self.book).exists())
        self.assertFalse(Budget.objects.filter(book=self.book).exists())
        self.assertFalse(Goal.objects.filter(book=self.book).exists())
        self.assertFalse(GoalAllocation.objects.filter(book=self.book).exists())
        self.assertFalse(BankTransaction.objects.filter(book=self.book).exists())
        self.assertFalse(TransferMatchDismissal.objects.filter(book=self.book).exists())

    def test_wipe_disconnects_plaid(self):
        wipe_book(self.book)
        self.assertFalse(PlaidAccount.objects.filter(book=self.book).exists())
        self.assertFalse(PlaidItem.objects.filter(book=self.book).exists())

    def test_wipe_leaves_other_teams_untouched(self):
        wipe_book(self.book)
        self.assertTrue(Account.objects.filter(book=self.other_book).exists())
        self.assertTrue(JournalEntry.objects.filter(book=self.other_book).exists())
        self.assertTrue(Payee.objects.filter(book=self.other_book).exists())

    def test_wipe_counts_are_exact(self):
        expected_lines = JournalLine.objects.filter(book=self.book).count()
        expected_entries = JournalEntry.objects.filter(book=self.book).count()
        expected_accounts = Account.objects.filter(book=self.book).count()
        expected_groups = AccountGroup.objects.filter(book=self.book).count()
        expected_payees = Payee.objects.filter(book=self.book).count()
        expected_institutions = Institution.objects.filter(book=self.book).count()
        expected_bank_tx = BankTransaction.objects.filter(book=self.book).count()
        expected_budgets = Budget.objects.filter(book=self.book).count()
        expected_goals = Goal.objects.filter(book=self.book).count()
        expected_allocations = GoalAllocation.objects.filter(book=self.book).count()
        expected_plaid_accounts = PlaidAccount.objects.filter(book=self.book).count()
        expected_plaid_items = PlaidItem.objects.filter(book=self.book).count()

        counts = wipe_book(self.book)

        self.assertEqual(counts.lines, expected_lines)
        self.assertEqual(counts.entries, expected_entries)
        self.assertEqual(counts.accounts, expected_accounts)
        self.assertEqual(counts.account_groups, expected_groups)
        self.assertEqual(counts.payees, expected_payees)
        self.assertEqual(counts.institutions, expected_institutions)
        self.assertEqual(counts.bank_transactions, expected_bank_tx)
        self.assertEqual(counts.budgets, expected_budgets)
        self.assertEqual(counts.goals, expected_goals)
        self.assertEqual(counts.goal_allocations, expected_allocations)
        self.assertEqual(counts.plaid_accounts, expected_plaid_accounts)
        self.assertEqual(counts.plaid_items, expected_plaid_items)

    def test_wipe_on_an_already_empty_team_is_a_no_op(self):
        team, _user = make_team("Empty", "empty")
        book = team.default_book
        counts = wipe_book(book)
        self.assertEqual(counts.accounts, 0)
        self.assertEqual(counts.entries, 0)
