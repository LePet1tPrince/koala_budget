"""Unit tests for `services/feed_accounts.py`, called without a request."""

from django.test import TestCase

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_BUDGET,
    ACCOUNT_TYPE_EXPENSE,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.errors import FeedError
from apps.bank_feed.services.feed_accounts import category_groups, create_category_account, feed_accounts
from apps.teams.models import Team


class FeedAccountsServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Svc Team", slug="svc-team")
        cls.book = cls.team.default_book
        cls.assets = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cls.expenses = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=cls.assets, has_feed=True)
        cls.hidden = Account.objects.create(
            book=cls.book, name="Hidden", account_group=cls.assets, has_feed=True, is_hidden=True
        )
        BankTransaction.objects.create(
            book=cls.book, account=cls.checking, amount=10, posted_date="2026-03-02", description="Coffee"
        )
        other = Team.objects.create(name="Other", slug="other-svc").default_book
        cls.other_group = AccountGroup.objects.create(book=other, name="Theirs", account_type=ACCOUNT_TYPE_EXPENSE)

    def test_feed_accounts_lists_visible_feed_accounts_with_activity(self):
        accounts = feed_accounts(self.book)
        self.assertEqual([a.name for a in accounts], ["Checking"])
        self.assertEqual(accounts[0].uncategorized_count, 1)
        self.assertEqual(str(accounts[0].latest_transaction_date), "2026-03-02")
        self.assertIsNone(accounts[0].last_statement_date)

    def test_category_groups_leave_out_the_budget_group_and_other_books(self):
        groups = set(category_groups(self.book))
        self.assertIn(self.expenses, groups)
        self.assertNotIn(self.other_group, groups)
        self.assertFalse(any(g.account_type == ACCOUNT_TYPE_BUDGET for g in groups))

    def test_create_puts_an_asset_account_on_a_feed(self):
        account = create_category_account(self.book, "Savings", self.assets.pk)
        self.assertTrue(account.has_feed)
        self.assertEqual(account.book, self.book)

    def test_create_leaves_a_category_off_the_feed(self):
        self.assertFalse(create_category_account(self.book, "Dining", self.expenses.pk).has_feed)

    def test_create_refuses_a_name_in_use_whatever_its_case(self):
        with self.assertRaisesMessage(FeedError, 'An account named "checking" already exists'):
            create_category_account(self.book, "checking", self.expenses.pk)

    def test_create_refuses_missing_fields(self):
        for name, group, message in (("", self.expenses.pk, "name is required"), ("X", None, "account_group_id")):
            with self.subTest(message=message), self.assertRaisesMessage(FeedError, message) as ctx:
                create_category_account(self.book, name, group)
            self.assertEqual(ctx.exception.status, 400)

    def test_create_refuses_another_books_group_as_not_found(self):
        with self.assertRaises(FeedError) as ctx:
            create_category_account(self.book, "Theirs too", self.other_group.pk)
        self.assertEqual(ctx.exception.status, 404)
