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
        account = PlaidAccount.objects.get(plaid_account_id="acc-new-1")
        self.assertIsNone(account.account)
        self.assertEqual(account.iso_currency_code, "CAD")
        self.assertFalse(account.is_foreign_currency)

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


@patch("apps.plaid.views.get_institution", return_value={"name": "TD"})
@patch("apps.plaid.views.get_accounts", return_value=ACCOUNTS)
@patch("apps.plaid.views.exchange_public_token", return_value={"access_token": "access-new", "item_id": "item-new"})
class ExchangeResponseTest(PlaidBookTestCase):
    def test_response_carries_the_accounts_to_map(self, *_mocks):
        """The account mapper is built from this list; the schema used to drop it."""
        response = self.client.post(
            self.url("exchange-token/"), {"public_token": "p", "institution_id": "ins_td"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["item_id"], PlaidItem.objects.get(plaid_item_id="item-new").pk)
        self.assertEqual([a["plaid_account_id"] for a in body["accounts"]], ["acc-new-1"])

    def test_schema_declares_the_accounts(self, *_mocks):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        props = schema["components"]["schemas"]["ExchangePublicTokenResponse"]["properties"]
        self.assertIn("accounts", props)
        self.assertIn("item_id", props)
