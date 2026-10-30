"""Plaid-Verification: a webhook is acted on only when Plaid provably sent it."""

import json
import time
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from django.core.cache import cache
from django.test import override_settings

from .base import PlaidBookTestCase
from .signing import PUBLIC_JWK, sign

BODY = json.dumps(
    {"webhook_type": "TRANSACTIONS", "webhook_code": "SYNC_UPDATES_AVAILABLE", "item_id": "item-1"}
).encode()


@override_settings(PLAID_VERIFY_WEBHOOKS=True)
@patch("apps.plaid.tasks.sync_plaid_transactions.delay")
@patch("apps.plaid.services.get_webhook_verification_key", return_value=PUBLIC_JWK)
class WebhookVerificationTest(PlaidBookTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def post(self, token=None, body=BODY):
        headers = {"HTTP_PLAID_VERIFICATION": token} if token else {}
        return self.client.generic("POST", "/plaid/webhook/", body, content_type="application/json", **headers)

    def test_a_signed_webhook_is_acted_on(self, get_key, delay):
        response = self.post(sign(BODY))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "sync_queued")
        delay.assert_called_once_with(self.item.pk)
        get_key.assert_called_once_with("test-key-1")

    def test_the_key_is_cached(self, get_key, delay):
        self.post(sign(BODY))
        self.post(sign(BODY))
        self.assertEqual(get_key.call_count, 1)

    def refused(self, response, delay):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "unverified")
        delay.assert_not_called()

    def test_no_header_is_refused(self, _key, delay):
        with self.assertLogs("apps.plaid.views", level="WARNING"):
            self.refused(self.post(), delay)

    def test_garbage_is_refused(self, _key, delay):
        with self.assertLogs("apps.plaid.views", level="WARNING"):
            self.refused(self.post("not-a-jwt"), delay)

    def test_another_signer_is_refused(self, _key, delay):
        with self.assertLogs("apps.plaid.views", level="WARNING"):
            self.refused(self.post(sign(BODY, key=ec.generate_private_key(ec.SECP256R1()))), delay)

    def test_a_tampered_body_is_refused(self, _key, delay):
        token = sign(BODY)
        tampered = BODY.replace(b"item-1", b"item-2")
        with self.assertLogs("apps.plaid.views", level="WARNING"):
            self.refused(self.post(token, body=tampered), delay)

    def test_a_replayed_token_is_refused(self, _key, delay):
        with self.assertLogs("apps.plaid.views", level="WARNING"):
            self.refused(self.post(sign(BODY, iat=int(time.time()) - 600)), delay)

    def test_an_expired_key_is_refused(self, get_key, delay):
        get_key.return_value = {**PUBLIC_JWK, "expired_at": int(time.time()) - 1}
        with self.assertLogs("apps.plaid.views", level="WARNING"):
            self.refused(self.post(sign(BODY)), delay)

    def test_hs256_is_refused(self, _key, delay):
        """An attacker can't downgrade to a symmetric algorithm keyed on the public key."""
        import jwt

        token = jwt.encode({"iat": int(time.time())}, "secret", algorithm="HS256", headers={"kid": "test-key-1"})
        with self.assertLogs("apps.plaid.views", level="WARNING"):
            self.refused(self.post(token), delay)

    def test_a_key_lookup_failure_is_refused(self, get_key, delay):
        get_key.side_effect = RuntimeError("plaid down")
        with self.assertLogs("apps.plaid.views", level="WARNING"):
            self.refused(self.post(sign(BODY)), delay)

    @override_settings(PLAID_VERIFY_WEBHOOKS=False)
    def test_verification_can_be_switched_off_for_development(self, _key, delay):
        self.assertEqual(self.post().json()["status"], "sync_queued")
