"""
Link token creation: what Plaid Link is opened with.

The product launches in Canada, so a link token that only offers US banks, or a
Canadian institution looked up as American, means a Canadian user can't connect
a bank at all.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import translation

from apps.plaid import services


def _request_kwargs(**settings_overrides):
    with override_settings(**settings_overrides):
        request = services.link_token_request(user_id=7)
    return request.to_dict()


@override_settings(PLAID_WEBHOOK_URL="https://example.com/plaid/webhook/", PLAID_REDIRECT_URI="")
class LinkTokenRequestTest(TestCase):
    def test_canada_is_offered_by_default(self):
        body = _request_kwargs()
        self.assertEqual(body["country_codes"], ["CA", "US"])

    def test_country_codes_follow_the_setting(self):
        body = _request_kwargs(PLAID_COUNTRY_CODES=["ca"])
        self.assertEqual(body["country_codes"], ["CA"])

    def test_webhook_is_sent(self):
        """Without it Plaid never notifies the app of new transactions."""
        self.assertEqual(_request_kwargs()["webhook"], "https://example.com/plaid/webhook/")

    def test_webhook_falls_back_to_the_site_url(self):
        body = _request_kwargs(PLAID_WEBHOOK_URL="")
        self.assertTrue(body["webhook"].endswith("/plaid/webhook/"), body["webhook"])

    def test_redirect_uri_only_when_configured(self):
        self.assertNotIn("redirect_uri", _request_kwargs())
        body = _request_kwargs(PLAID_REDIRECT_URI="https://example.com/plaid/oauth/")
        self.assertEqual(body["redirect_uri"], "https://example.com/plaid/oauth/")

    def test_history_requested(self):
        body = _request_kwargs(PLAID_TRANSACTIONS_DAYS_REQUESTED=365)
        self.assertEqual(body["transactions"], {"days_requested": 365})
        self.assertEqual(body["products"], ["transactions"])

    def test_language_follows_the_user(self):
        with translation.override("fr"):
            self.assertEqual(_request_kwargs()["language"], "fr")
        with translation.override("en-us"):
            self.assertEqual(_request_kwargs()["language"], "en")

    def test_unsupported_language_falls_back(self):
        with translation.override("de"):
            self.assertEqual(_request_kwargs()["language"], "en")


class InstitutionLookupTest(TestCase):
    @patch("apps.plaid.services.get_plaid_client")
    def test_institution_lookup_includes_canada(self, get_client):
        client = MagicMock()
        client.institutions_get_by_id.return_value = {"institution": {"name": "RBC Royal Bank"}}
        get_client.return_value = client

        services.get_institution("ins_1")

        request = client.institutions_get_by_id.call_args.args[0]
        self.assertIn("CA", request.to_dict()["country_codes"])
