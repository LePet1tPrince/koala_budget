"""
Unit tests for the read-side services the feed endpoints call: `feed_query.select_all`
and `locate`, `similar_transactions.suggestion_rows` / `latest_category_by_merchant`,
`transfer_match.suggestions` and `transfer_detection.dismiss_pair`.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.http import QueryDict
from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.bank_feed.models import BankTransaction, TransferMatchDismissal
from apps.bank_feed.services import feed_query
from apps.bank_feed.services.categorize import create_entry
from apps.bank_feed.services.errors import FeedError
from apps.bank_feed.services.similar_transactions import latest_category_by_merchant, suggestion_rows
from apps.bank_feed.services.transfer_detection import dismiss_pair
from apps.bank_feed.services.transfer_match import suggestions
from apps.teams.models import Team


def params(query=""):
    return feed_query.FeedParams.parse(QueryDict(query))


class FeedLookupServicesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.book = Team.objects.create(name="Lookup", slug="lookup-svc").default_book
        assets = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        expenses = AccountGroup.objects.create(book=cls.book, name="Spend", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.bank = Account.objects.create(book=cls.book, name="Checking", account_group=assets, has_feed=True)
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=assets, has_feed=True)
        cls.food = Account.objects.create(book=cls.book, name="Food", account_group=expenses)
        start = date(2026, 1, 1)
        cls.rows = [
            BankTransaction.objects.create(
                book=cls.book,
                account=cls.bank,
                amount=Decimal("5"),
                posted_date=start + timedelta(days=i),
                merchant_name="Cafe",
                description=f"CAFE {i}",
            )
            for i in range(12)
        ]

    def test_select_all_answers_count_and_rows_in_list_order(self):
        total, rows = feed_query.select_all(self.book, params())
        self.assertEqual(total, 12)
        self.assertEqual(rows[0]["id"], self.rows[-1].pk)  # newest first

    def test_select_all_refuses_above_the_cap(self):
        with mock.patch.object(feed_query, "MAX_IDS", 10), self.assertRaises(feed_query.SelectionTooLarge) as ctx:
            feed_query.select_all(self.book, params())
        self.assertEqual(ctx.exception.count, 12)

    def test_locate_names_the_page(self):
        oldest = self.rows[0]
        self.assertEqual(
            feed_query.locate(self.book, params("page_size=10"), row=oldest.pk),
            {"id": oldest.pk, "page": 2, "is_void": False},
        )
        self.assertEqual(
            feed_query.locate(self.book, params(), row=0),
            {"id": None, "page": None, "is_void": None},
        )

    def test_locate_by_entry_and_account(self):
        create_entry(self.rows[3], self.food)
        found = feed_query.locate(
            self.book, params(), journal_entry=self.rows[3].journal_entry_id, in_account=self.bank.pk
        )
        self.assertEqual(found["id"], self.rows[3].pk)

    def test_merchant_suggestions_and_ranked_rows(self):
        create_entry(self.rows[0], self.food)
        self.assertEqual(
            latest_category_by_merchant(self.book),
            [{"merchant_name": "Cafe", "category_id": self.food.pk, "category_name": "Food"}],
        )
        rows = suggestion_rows(self.book, [self.rows[2].pk, self.rows[1].pk])
        self.assertEqual([row["transaction_id"] for row in rows], [self.rows[2].pk, self.rows[1].pk])
        self.assertEqual(rows[0]["category_id"], self.food.pk)

    def test_transfer_suggestions_filter_by_account_after_pairing(self):
        out = BankTransaction.objects.create(
            book=self.book, account=self.bank, amount=Decimal("100"), posted_date=date(2026, 2, 1)
        )
        BankTransaction.objects.create(
            book=self.book, account=self.savings, amount=Decimal("-100"), posted_date=date(2026, 2, 2)
        )
        self.assertEqual(len(suggestions(self.book)), 1)
        self.assertEqual(len(suggestions(self.book, self.savings.pk)), 1)
        self.assertEqual(suggestions(self.book, self.food.pk), [])
        self.assertIn("proposal", suggestions(self.book)[0])
        self.assertEqual(suggestions(self.book)[0]["outflow"].pk, out.pk)

    def test_dismiss_pair_records_and_refuses_unknown_rows(self):
        a, b = self.rows[0].pk, self.rows[1].pk
        dismiss_pair(self.book, a, b)
        self.assertTrue(TransferMatchDismissal.objects.filter(book=self.book).exists())
        with self.assertRaises(FeedError) as ctx:
            dismiss_pair(self.book, a, 0)
        self.assertEqual(ctx.exception.status, 404)
