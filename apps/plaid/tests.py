"""
Tests for the Plaid app: webhook receiver.
"""

from unittest.mock import patch

from django.test import TestCase

from apps.teams.models import Team

from .models import PlaidItem


class PlaidWebhookTest(TestCase):
    """Tests for the global Plaid webhook endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.item = PlaidItem.objects.create(
            team=cls.team,
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
