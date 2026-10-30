"""Mapping a Plaid account to a ledger account (PATCH plaid/api/accounts/<id>/)."""

from apps.accounts.models import Account
from apps.plaid.models import PlaidAccount

from .base import PlaidBookTestCase


class PlaidAccountMappingTest(PlaidBookTestCase):
    def setUp(self):
        super().setUp()
        self.unmapped = PlaidAccount.objects.create(
            book=self.book,
            item=self.item,
            plaid_account_id="acc-savings",
            name="Savings",
            mask="5555",
            subtype="savings",
            type="depository",
        )

    def patch(self, account_id):
        return self.client.patch(self.url(f"accounts/{self.unmapped.pk}/"), {"account": account_id}, format="json")

    def test_maps_to_an_asset_and_turns_its_feed_on(self):
        Account.objects.filter(pk=self.savings.pk).update(has_feed=False)
        response = self.patch(self.savings.pk)
        self.assertEqual(response.status_code, 200, response.content)
        self.unmapped.refresh_from_db()
        self.assertEqual(self.unmapped.account, self.savings)
        self.savings.refresh_from_db()
        self.assertTrue(self.savings.has_feed)

    def test_refuses_an_expense_category(self):
        response = self.patch(self.groceries.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("asset or liability", str(response.data))

    def test_refuses_an_account_another_bank_account_feeds(self):
        """Two Plaid accounts feeding one ledger account would import every transaction twice."""
        response = self.patch(self.checking.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("already fed", str(response.data))

    def test_remapping_to_the_same_account_is_fine(self):
        response = self.client.patch(
            self.url(f"accounts/{self.plaid_checking.pk}/"), {"account": self.checking.pk}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)


class BackfillOnMappingTest(PlaidBookTestCase):
    """An account mapped after its transactions were skipped gets its history."""

    def setUp(self):
        super().setUp()
        self.savings_plaid = PlaidAccount.objects.create(
            book=self.book, item=self.item, plaid_account_id="acc-savings", name="Savings", subtype="savings", type="d"
        )

    def tx(self, tx_id, account_id):
        from datetime import date
        from decimal import Decimal

        return {
            "transaction_id": tx_id,
            "account_id": account_id,
            "amount": Decimal("5"),
            "date": date(2026, 9, 1),
            "name": "X",
        }

    def sync(self, *pages):
        from unittest.mock import patch

        from apps.plaid.tasks import sync_plaid_transactions

        with patch("apps.plaid.tasks.sync_transactions", side_effect=list(pages)) as mock_sync:
            sync_plaid_transactions(self.item.pk)
        return mock_sync

    def page(self, added, cursor):
        return {"added": added, "modified": [], "removed": [], "next_cursor": cursor, "has_more": False}

    def test_mapping_rereads_the_history_and_imports_the_skipped_rows(self):
        from unittest.mock import patch

        from apps.bank_feed.models import BankTransaction

        both = [self.tx("tx-chq", "acc-checking"), self.tx("tx-sav", "acc-savings")]
        self.sync(self.page(both, "c1"))
        self.assertEqual(BankTransaction.objects.filter(account=self.savings).count(), 0)

        with (
            patch("apps.plaid.tasks.sync_plaid_transactions.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.patch(
                self.url(f"accounts/{self.savings_plaid.pk}/"), {"account": self.savings.pk}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(self.item.pk)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.cursor)

        mock_sync = self.sync(self.page(both, "c2"))
        self.assertIsNone(mock_sync.call_args.kwargs["cursor"])
        self.assertEqual(BankTransaction.objects.filter(account=self.savings).count(), 1)
        self.assertEqual(BankTransaction.objects.filter(account=self.checking).count(), 1, "not imported twice")

    def test_ignoring_an_account_does_not_backfill(self):
        from unittest.mock import patch

        with (
            patch("apps.plaid.tasks.sync_plaid_transactions.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.patch(
                self.url(f"accounts/{self.savings_plaid.pk}/"), {"is_ignored": True}, format="json"
            )
        self.assertEqual(response.status_code, 200)
        delay.assert_not_called()
        self.savings_plaid.refresh_from_db()
        self.assertTrue(self.savings_plaid.is_ignored)
        self.assertEqual(self.client.get(self.url(f"items/{self.item.pk}/")).json()["unmapped_accounts"], 0)

    def test_unmapped_accounts_are_counted(self):
        self.assertEqual(self.client.get(self.url(f"items/{self.item.pk}/")).json()["unmapped_accounts"], 1)

    def test_refresh_is_no_longer_refused_for_an_unmapped_account(self):
        from unittest.mock import patch

        with patch("apps.plaid.tasks.sync_plaid_transactions.delay") as delay:
            delay.return_value.id = "task-1"  # a bare MagicMock id never finishes JSON-encoding
            response = self.client.post(self.url(f"items/{self.item.pk}/sync/"))
        self.assertEqual(response.status_code, 200)
        delay.assert_called_once()

    def test_a_reset_during_a_running_sync_survives_it(self):
        from apps.plaid.models import PlaidItem

        def reset_mid_sync(**kwargs):
            PlaidItem.objects.filter(pk=self.item.pk).update(cursor=None)
            return self.page([], "c9")

        from unittest.mock import patch

        from apps.plaid.tasks import sync_plaid_transactions

        with patch("apps.plaid.tasks.sync_transactions", side_effect=reset_mid_sync):
            sync_plaid_transactions(self.item.pk)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.cursor)


class PlaidAccountReadOnlyFieldsTest(PlaidBookTestCase):
    def test_plaids_own_fields_cannot_be_rewritten(self):
        response = self.client.patch(
            self.url(f"accounts/{self.plaid_checking.pk}/"),
            {"plaid_account_id": "acc-hijacked", "name": "Renamed", "mask": "0000"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.plaid_checking.refresh_from_db()
        self.assertEqual(
            (self.plaid_checking.plaid_account_id, self.plaid_checking.name, self.plaid_checking.mask),
            ("acc-checking", "Chequing", "1234"),
        )
