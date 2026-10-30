"""The public-token exchange: linking a bank into a book."""

from unittest.mock import patch

from apps.plaid.models import PlaidAccount, PlaidItem

from .base import PlaidBookTestCase

ACCOUNTS = [
    {
        "account_id": "acc-new-1",
        "name": "Chequing",
        "mask": "9876",
        "subtype": "checking",
        "type": "depository",
        "balances": {"iso_currency_code": "CAD"},
    }
]


@patch("apps.plaid.views.get_accounts", return_value=ACCOUNTS)
@patch("apps.plaid.views.exchange_public_token", return_value={"access_token": "access-new", "item_id": "item-new"})
class ExchangePublicTokenTest(PlaidBookTestCase):
    def post(self, **body):
        payload = {"public_token": "public-x", "institution_id": "ins_td", **body}
        return self.client.post(self.url("exchange-token/"), payload, format="json")

    @patch("apps.plaid.views.get_institution", return_value={"name": "TD Canada Trust"})
    def test_links_item_and_accounts(self, _inst, _exchange, _accounts):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.content)
        item = PlaidItem.objects.get(plaid_item_id="item-new")
        self.assertEqual(item.book, self.book)
        self.assertEqual(item.institution_name, "TD Canada Trust")
        self.assertEqual(list(item.accounts.values_list("plaid_account_id", flat=True)), ["acc-new-1"])
        self.assertIsNone(PlaidAccount.objects.get(plaid_account_id="acc-new-1").account)

    @patch("apps.plaid.views.get_institution", side_effect=RuntimeError("INSTITUTION_NOT_FOUND"))
    def test_failed_institution_lookup_uses_links_name(self, _inst, _exchange, _accounts):
        """The bank is already connected at Plaid by then; a lookup failure must not lose it."""
        response = self.post(institution_name="Desjardins")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(PlaidItem.objects.get(plaid_item_id="item-new").institution_name, "Desjardins")

    def test_requires_public_token(self, _exchange, _accounts):
        response = self.client.post(self.url("exchange-token/"), {"institution_id": "x"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_outsider_refused(self, _exchange, _accounts):
        self.client.force_authenticate(user=self.outsider)
        self.assertIn(self.post().status_code, (403, 404))
        self.assertFalse(PlaidItem.objects.filter(plaid_item_id="item-new").exists())
