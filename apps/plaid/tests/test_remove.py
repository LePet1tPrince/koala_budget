"""Disconnecting a bank (POST items/{id}/remove/)."""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from plaid import ApiException

from apps.audit.models import AuditEvent
from apps.bank_feed.models import BankTransaction
from apps.plaid.models import PlaidAccount, PlaidItem, PlaidTransaction

from .base import PlaidBookTestCase


class RemoveItemTest(PlaidBookTestCase):
    def setUp(self):
        super().setUp()
        self.row = BankTransaction.objects.create(
            book=self.book,
            account=self.checking,
            amount=Decimal("10.00"),
            posted_date=date(2026, 10, 1),
            description="TIM HORTONS",
            source=BankTransaction.SOURCE_PLAID,
        )
        PlaidTransaction.objects.create(
            book=self.book, plaid_transaction_id="tx-1", bank_transaction=self.row, plaid_account=self.plaid_checking
        )

    def remove(self):
        return self.client.post(self.url(f"items/{self.item.pk}/remove/"))

    @patch("apps.plaid.services.remove_item")
    def test_removes_at_plaid_and_here_but_keeps_the_feed_rows(self, remove_item):
        response = self.remove()
        self.assertEqual(response.status_code, 204)
        remove_item.assert_called_once_with("access-sandbox-1")
        self.assertFalse(PlaidItem.objects.filter(pk=self.item.pk).exists())
        self.assertFalse(PlaidAccount.objects.filter(pk=self.plaid_checking.pk).exists())
        self.assertTrue(BankTransaction.objects.filter(pk=self.row.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.PLAID_ITEM_REMOVED, book=self.book).exists())

    @patch("apps.plaid.services.remove_item")
    def test_an_item_already_gone_at_plaid_is_still_removed_here(self, remove_item):
        exc = ApiException(status=400)
        exc.body = json.dumps({"error_code": "ITEM_NOT_FOUND"})
        remove_item.side_effect = exc
        self.assertEqual(self.remove().status_code, 204)
        self.assertFalse(PlaidItem.objects.filter(pk=self.item.pk).exists())

    @patch("apps.plaid.services.remove_item", side_effect=RuntimeError("down"))
    def test_a_plaid_outage_still_disconnects_here(self, _remove_item):
        with self.assertLogs("apps.plaid.linking", level="ERROR"):
            self.assertEqual(self.remove().status_code, 204)
        self.assertFalse(PlaidItem.objects.filter(pk=self.item.pk).exists())

    @patch("apps.plaid.services.remove_item")
    def test_a_member_cannot_disconnect(self, remove_item):
        self.client.force_authenticate(user=self.member)
        self.assertEqual(self.remove().status_code, 403)
        remove_item.assert_not_called()
        self.assertTrue(PlaidItem.objects.filter(pk=self.item.pk).exists())

    @patch("apps.plaid.services.remove_item")
    def test_the_ledger_account_can_be_deleted_once_disconnected(self, _remove_item):
        """PlaidAccount PROTECTs its ledger account; disconnecting lets it go."""
        self.remove()
        BankTransaction.objects.filter(pk=self.row.pk).delete()
        self.checking.delete()
