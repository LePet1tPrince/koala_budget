"""The Plaid SDK wrappers in apps.plaid.services, against a mocked client."""

import json
from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from plaid import ApiException

from apps.plaid import services


class PlaidClientTest(SimpleTestCase):
    @override_settings(PLAID_ENV="sandbox")
    def test_an_environment_name_resolves_to_its_host(self):
        self.assertEqual(services.plaid_host(), "https://sandbox.plaid.com")

    @override_settings(PLAID_ENV="Production")
    def test_production(self):
        self.assertEqual(services.plaid_host(), "https://production.plaid.com")

    @override_settings(PLAID_ENV="https://sandbox.plaid.com")
    def test_a_url_is_used_as_given(self):
        self.assertEqual(services.plaid_host(), "https://sandbox.plaid.com")

    @override_settings(PLAID_ENV="development")
    def test_a_retired_environment_is_refused(self):
        with self.assertRaises(ImproperlyConfigured):
            services.plaid_host()

    @override_settings(PLAID_ENV="sandbox", PLAID_CLIENT_ID="cid", PLAID_SECRET="sec")
    def test_client_is_configured(self):
        client = services.get_plaid_client()
        self.assertEqual(client.api_client.configuration.host, "https://sandbox.plaid.com")


class ErrorCodeTest(SimpleTestCase):
    def exc(self, body):
        exc = ApiException(status=400)
        exc.body = body
        return exc

    def test_reads_the_error_code(self):
        self.assertEqual(services.plaid_error_code(self.exc(json.dumps({"error_code": "X"}))), "X")

    def test_tolerates_anything_else(self):
        self.assertIsNone(services.plaid_error_code(self.exc("not json")))
        self.assertIsNone(services.plaid_error_code(self.exc(json.dumps([1]))))
        self.assertIsNone(services.plaid_error_code(self.exc(None)))
        self.assertIsNone(services.plaid_error_code(RuntimeError("x")))


@patch("apps.plaid.services.get_plaid_client")
class WrapperTest(SimpleTestCase):
    def mock_client(self, get_client):
        client = MagicMock()
        get_client.return_value = client
        return client

    def test_exchange(self, get_client):
        client = self.mock_client(get_client)
        client.item_public_token_exchange.return_value = {"access_token": "a", "item_id": "i"}
        self.assertEqual(services.exchange_public_token("p"), {"access_token": "a", "item_id": "i"})
        self.assertEqual(client.item_public_token_exchange.call_args.args[0].public_token, "p")

    def test_accounts(self, get_client):
        client = self.mock_client(get_client)
        client.accounts_get.return_value = {"accounts": [{"account_id": "x"}]}
        self.assertEqual(services.get_accounts("a"), [{"account_id": "x"}])

    def test_remove(self, get_client):
        client = self.mock_client(get_client)
        services.remove_item("a")
        self.assertEqual(client.item_remove.call_args.args[0].access_token, "a")

    def test_webhook_key(self, get_client):
        client = self.mock_client(get_client)
        client.webhook_verification_key_get.return_value = {"key": {"kid": "k", "x": "1"}}
        self.assertEqual(services.get_webhook_verification_key("k"), {"kid": "k", "x": "1"})

    def test_sync_sends_the_cursor_only_when_there_is_one(self, get_client):
        client = self.mock_client(get_client)
        client.transactions_sync.return_value = {"added": [1], "next_cursor": "c1", "has_more": True}
        result = services.sync_transactions("a", cursor=None)
        self.assertNotIn("cursor", client.transactions_sync.call_args.args[0].to_dict())
        self.assertEqual(result, {"added": [1], "modified": [], "removed": [], "next_cursor": "c1", "has_more": True})
        services.sync_transactions("a", cursor="c1")
        self.assertEqual(client.transactions_sync.call_args.args[0].to_dict()["cursor"], "c1")

    def test_create_link_tokens(self, get_client):
        client = self.mock_client(get_client)
        client.link_token_create.return_value = {"link_token": "lt"}
        with override_settings(PLAID_WEBHOOK_URL="https://example.com/plaid/webhook/"):
            self.assertEqual(services.create_link_token(1), "lt")
            item = MagicMock(access_token="a", new_accounts_available=False)
            self.assertEqual(services.create_update_link_token(item, 1), "lt")
