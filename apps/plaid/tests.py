"""
Tests for the Plaid app: webhook receiver and the transaction sync task.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.bank_feed.models import BankTransaction
from apps.books.context import get_current_book
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team

from .models import PlaidAccount, PlaidItem
from .tasks import sync_plaid_transactions


class PlaidWebhookTest(TestCase):
    """Tests for the global Plaid webhook endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.item = PlaidItem.objects.create(
            book=cls.book,
            plaid_item_id="item-abc",
            access_token="access-token",
            institution_name="Test Bank",
        )

    @patch("apps.plaid.tasks.sync_plaid_transactions.delay")
    def test_sync_updates_available_queues_sync(self, mock_delay):
        response = self.client.post(
            "/plaid/webhook/",
            {
                "webhook_type": "TRANSACTIONS",
                "webhook_code": "SYNC_UPDATES_AVAILABLE",
                "item_id": "item-abc",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "sync_queued")
        mock_delay.assert_called_once_with(self.item.id)

    @patch("apps.plaid.tasks.sync_plaid_transactions.delay")
    def test_unknown_item_is_ignored(self, mock_delay):
        response = self.client.post(
            "/plaid/webhook/",
            {
                "webhook_type": "TRANSACTIONS",
                "webhook_code": "SYNC_UPDATES_AVAILABLE",
                "item_id": "item-unknown",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ignored")
        mock_delay.assert_not_called()

    @patch("apps.plaid.tasks.sync_plaid_transactions.delay")
    def test_unrelated_webhook_is_ignored(self, mock_delay):
        response = self.client.post(
            "/plaid/webhook/",
            {"webhook_type": "ITEM", "webhook_code": "ERROR", "item_id": "item-abc"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ignored")
        mock_delay.assert_not_called()

    def test_malformed_payload_returns_200(self):
        """Plaid retries on non-2xx, so garbage payloads must still return 200."""
        response = self.client.post("/plaid/webhook/", "not json", content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_get_not_allowed(self):
        response = self.client.get("/plaid/webhook/")
        self.assertEqual(response.status_code, 405)


class PlaidSyncTaskTest(TestCase):
    """
    `sync_plaid_transactions` against a mocked `/transactions/sync`.

    The task is the only writer of Plaid rows into the feed, so these pin the
    rules that keep a user's books intact: a categorized row is never rewritten
    or deleted by the bank, a duplicate delivery never doubles a row, and a
    failed sync never advances the cursor.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Sync Team", slug="sync-team")
        cls.book = cls.team.default_book
        group = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=group, has_feed=True)
        expense_group = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=expense_group)

    def setUp(self):
        self.item = PlaidItem.objects.create(
            book=self.book, plaid_item_id="item-sync", access_token="token", institution_name="Bank", cursor="c0"
        )
        PlaidAccount.objects.create(
            book=self.book,
            item=self.item,
            account=self.checking,
            plaid_account_id="acc-1",
            name="Checking",
            subtype="checking",
            type="depository",
        )

    def tx(self, tx_id="tx-1", amount="12.50", **extra):
        return {
            "transaction_id": tx_id,
            "account_id": "acc-1",
            "amount": Decimal(amount),
            "date": date(2026, 3, 4),
            "name": "COFFEE SHOP",
            "merchant_name": "Coffee",
            "personal_finance_category": {"primary": "FOOD", "detailed": "FOOD_COFFEE", "confidence_level": "HIGH"},
            **extra,
        }

    def page(self, added=(), modified=(), removed=(), next_cursor="c1", has_more=False):
        return {
            "added": list(added),
            "modified": list(modified),
            "removed": list(removed),
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    def run_sync(self, *pages):
        with patch("apps.plaid.tasks.sync_transactions", side_effect=list(pages)) as mock_sync:
            result = sync_plaid_transactions(self.item.id)
        self.item.refresh_from_db()
        return result, mock_sync

    def categorize(self, bank_tx):
        entry = JournalEntry.objects.create(book=self.book, entry_date=bank_tx.posted_date, description="x")
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.groceries, dr_amount=bank_tx.amount
        )
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=self.checking, cr_amount=bank_tx.amount)
        bank_tx.journal_entry = entry
        bank_tx.save()

    def test_added_rows_land_in_the_feed_and_the_cursor_advances(self):
        result, _ = self.run_sync(self.page(added=[self.tx()]))

        self.assertEqual(result, {"success": True, "added": 1, "modified": 0, "removed": 0})
        bank_tx = BankTransaction.objects.get(book=self.book)
        self.assertEqual(bank_tx.account, self.checking)
        self.assertEqual(bank_tx.amount, Decimal("12.50"))
        self.assertEqual(bank_tx.source, BankTransaction.SOURCE_PLAID)
        self.assertIsNone(bank_tx.journal_entry)
        self.assertEqual(bank_tx.plaid_transaction.personal_finance_category, "FOOD")
        self.assertEqual(self.item.cursor, "c1")
        self.assertIsNotNone(self.item.last_synced_at)
        events = set(AuditEvent.objects.filter(book=self.book).values_list("event_type", flat=True))
        self.assertTrue({AuditEvent.PLAID_SYNC_STARTED, AuditEvent.PLAID_SYNC_COMPLETED} <= events)

    def test_pages_are_followed_until_has_more_is_false(self):
        result, mock_sync = self.run_sync(
            self.page(added=[self.tx("tx-1")], next_cursor="c1", has_more=True),
            self.page(added=[self.tx("tx-2")], next_cursor="c2"),
        )
        self.assertEqual(result["added"], 2)
        self.assertEqual([call.kwargs["cursor"] for call in mock_sync.call_args_list], ["c0", "c1"])
        self.assertEqual(self.item.cursor, "c2")

    def test_a_redelivered_transaction_is_not_added_twice(self):
        self.run_sync(self.page(added=[self.tx()]))
        self.run_sync(self.page(added=[self.tx()]))
        self.assertEqual(BankTransaction.objects.filter(book=self.book).count(), 1)

    def test_a_row_on_an_unmapped_account_is_skipped(self):
        self.run_sync(self.page(added=[self.tx(account_id="acc-unknown")]))
        self.assertFalse(BankTransaction.objects.filter(book=self.book).exists())

    def test_modified_rewrites_an_uncategorized_row(self):
        self.run_sync(self.page(added=[self.tx()]))
        self.run_sync(self.page(modified=[self.tx(amount="15.00", name="COFFEE SHOP #2")], next_cursor="c2"))
        bank_tx = BankTransaction.objects.get(book=self.book)
        self.assertEqual(bank_tx.amount, Decimal("15.00"))
        self.assertEqual(bank_tx.description, "COFFEE SHOP #2")

    def test_modified_leaves_a_categorized_row_alone(self):
        self.run_sync(self.page(added=[self.tx()]))
        self.categorize(BankTransaction.objects.get(book=self.book))
        self.run_sync(self.page(modified=[self.tx(amount="99.00")], next_cursor="c2"))
        self.assertEqual(BankTransaction.objects.get(book=self.book).amount, Decimal("12.50"))

    def test_modified_for_an_unknown_row_adds_it(self):
        self.run_sync(self.page(modified=[self.tx("tx-new")]))
        self.assertTrue(BankTransaction.objects.filter(book=self.book, plaid_transaction__isnull=False).exists())

    def test_removed_deletes_an_uncategorized_row(self):
        self.run_sync(self.page(added=[self.tx()]))
        self.run_sync(self.page(removed=[{"transaction_id": "tx-1"}], next_cursor="c2"))
        self.assertFalse(BankTransaction.objects.filter(book=self.book).exists())

    def test_removed_keeps_a_categorized_row(self):
        self.run_sync(self.page(added=[self.tx()]))
        self.categorize(BankTransaction.objects.get(book=self.book))
        self.run_sync(self.page(removed=[{"transaction_id": "tx-1"}], next_cursor="c2"))
        self.assertTrue(BankTransaction.objects.filter(book=self.book).exists())

    def test_a_failed_sync_is_logged_and_keeps_the_cursor(self):
        with (
            patch("apps.plaid.tasks.sync_transactions", side_effect=RuntimeError("plaid down")),
            self.assertRaises(RuntimeError),
            self.assertLogs("apps.plaid.tasks", level="ERROR"),
        ):
            sync_plaid_transactions(self.item.id)
        self.item.refresh_from_db()
        self.assertEqual(self.item.cursor, "c0")
        self.assertTrue(AuditEvent.objects.filter(book=self.book, event_type=AuditEvent.PLAID_SYNC_FAILED).exists())
        self.assertIsNone(get_current_book())

    def test_an_unknown_item_reports_rather_than_raises(self):
        self.assertEqual(sync_plaid_transactions(999999), {"success": False, "error": "PlaidItem not found"})

    def test_the_book_context_is_cleared_after_a_sync(self):
        self.run_sync(self.page())
        self.assertIsNone(get_current_book())
