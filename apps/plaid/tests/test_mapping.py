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
