"""The public-token exchange: linking a bank into a book."""

from unittest.mock import patch

from apps.audit.models import AuditEvent
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

EXCHANGE = {"access_token": "access-new", "item_id": "item-new"}


@patch("apps.plaid.services.remove_item")
@patch("apps.plaid.services.get_accounts", return_value=ACCOUNTS)
@patch("apps.plaid.services.exchange_public_token", return_value=EXCHANGE)
class ExchangePublicTokenTest(PlaidBookTestCase):
    def post(self, **body):
        payload = {"public_token": "public-x", "institution_id": "ins_td", **body}
        return self.client.post(self.url("exchange-token/"), payload, format="json")

    @patch("apps.plaid.services.get_institution", return_value={"name": "TD Canada Trust"})
    def test_links_item_and_accounts(self, _inst, _exchange, _accounts, remove):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.content)
        item = PlaidItem.objects.get(plaid_item_id="item-new")
        self.assertEqual(item.book, self.book)
        self.assertEqual(item.institution_name, "TD Canada Trust")
        self.assertEqual(item.institution_id, "ins_td")
        self.assertEqual(item.access_token, "access-new")
        self.assertEqual(list(item.accounts.values_list("plaid_account_id", flat=True)), ["acc-new-1"])
        account = PlaidAccount.objects.get(plaid_account_id="acc-new-1")
        self.assertIsNone(account.account)
        self.assertEqual(account.iso_currency_code, "CAD")
        self.assertFalse(account.is_foreign_currency)
        event = AuditEvent.objects.get(event_type=AuditEvent.PLAID_ITEM_LINKED)
        self.assertEqual(event.metadata["accounts"], 1)
        remove.assert_not_called()

    @patch("apps.plaid.services.get_institution", side_effect=RuntimeError("INSTITUTION_NOT_FOUND"))
    def test_failed_institution_lookup_uses_links_name(self, _inst, _exchange, _accounts, _remove):
        """The bank is already connected at Plaid by then; a lookup failure must not lose it."""
        with self.assertLogs("apps.plaid.linking", level="WARNING"):
            response = self.post(institution_name="Desjardins")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(PlaidItem.objects.get(plaid_item_id="item-new").institution_name, "Desjardins")

    @patch("apps.plaid.services.get_institution", return_value={"name": "TD"})
    def test_a_failure_after_the_exchange_records_nothing_and_removes_the_item_at_plaid(
        self, _inst, _exchange, accounts, remove
    ):
        """Left behind, the new item would be unrecorded here but still billed and syncing at Plaid."""
        accounts.side_effect = RuntimeError("accounts/get failed")
        with self.assertLogs("apps.plaid.views", level="ERROR"):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertFalse(PlaidItem.objects.filter(plaid_item_id="item-new").exists())
        remove.assert_called_once_with("access-new")

    def test_relinking_the_same_login_is_refused_before_the_exchange(self, exchange, _accounts, _remove):
        PlaidItem.objects.filter(pk=self.item.pk).update(institution_id="ins_rbc")
        response = self.post(institution_id="ins_rbc", accounts=[{"id": "x", "name": "Chequing", "mask": "1234"}])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["item_id"], self.item.pk)
        exchange.assert_not_called()

    @patch("apps.plaid.services.get_institution", return_value={"name": "RBC"})
    def test_another_login_at_the_same_bank_is_allowed(self, _inst, _exchange, _accounts, _remove):
        """A partner's own RBC login has different accounts."""
        PlaidItem.objects.filter(pk=self.item.pk).update(institution_id="ins_rbc")
        response = self.post(institution_id="ins_rbc", accounts=[{"id": "y", "name": "Joint", "mask": "4321"}])
        self.assertEqual(response.status_code, 200, response.content)

    def test_requires_public_token(self, _exchange, _accounts, _remove):
        response = self.client.post(self.url("exchange-token/"), {"institution_id": "x"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_outsider_refused(self, _exchange, _accounts, _remove):
        self.client.force_authenticate(user=self.outsider)
        self.assertIn(self.post().status_code, (403, 404))
        self.assertFalse(PlaidItem.objects.filter(plaid_item_id="item-new").exists())


@patch("apps.plaid.services.get_institution", return_value={"name": "TD"})
@patch("apps.plaid.services.get_accounts", return_value=ACCOUNTS)
@patch("apps.plaid.services.exchange_public_token", return_value=EXCHANGE)
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
