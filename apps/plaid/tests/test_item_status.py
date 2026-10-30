"""Item error states: ITEM webhooks, sync errors, and Link's update mode."""

import json
from unittest.mock import MagicMock, patch

from django.test import override_settings
from plaid import ApiException

from apps.audit.models import AuditEvent
from apps.plaid import services
from apps.plaid.models import PlaidAccount, PlaidItem
from apps.plaid.tasks import sync_plaid_transactions

from .base import PlaidBookTestCase


def plaid_error(code, message="Sign in again"):
    exc = ApiException(status=400)
    exc.body = json.dumps({"error_code": code, "display_message": message})
    return exc


class ItemWebhookTest(PlaidBookTestCase):
    def webhook(self, code, **payload):
        return self.client.post(
            "/plaid/webhook/",
            {"webhook_type": "ITEM", "webhook_code": code, "item_id": self.item.plaid_item_id, **payload},
            format="json",
        )

    def test_login_required_error(self):
        response = self.webhook("ERROR", error={"error_code": "ITEM_LOGIN_REQUIRED", "display_message": "Sign in"})
        self.assertEqual(response.json()["status"], "recorded")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_LOGIN_REQUIRED)
        self.assertEqual(self.item.error_code, "ITEM_LOGIN_REQUIRED")
        self.assertEqual(self.item.error_message, "Sign in")
        self.assertTrue(self.item.needs_attention)
        event = AuditEvent.objects.get(event_type=AuditEvent.PLAID_ITEM_STATUS_CHANGED)
        self.assertEqual(event.metadata["to"], PlaidItem.STATUS_LOGIN_REQUIRED)
        self.assertEqual(event.book, self.book)

    def test_an_unknown_error_code_changes_nothing(self):
        with self.assertLogs("apps.plaid.item_status", level="WARNING"):
            self.webhook("ERROR", error={"error_code": "SOMETHING_NEW"})
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_HEALTHY)

    def test_pending_expiration_records_when(self):
        self.webhook("PENDING_EXPIRATION", consent_expiration_time="2026-11-15T13:25:17Z")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_PENDING_EXPIRATION)
        self.assertEqual(self.item.consent_expiration_time.isoformat(), "2026-11-15T13:25:17+00:00")

    def test_pending_disconnect(self):
        self.webhook("PENDING_DISCONNECT", reason="INSTITUTION_MIGRATION")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_PENDING_DISCONNECT)

    def test_permission_revoked(self):
        self.webhook("USER_PERMISSION_REVOKED")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_REVOKED)

    def test_new_accounts_available(self):
        self.webhook("NEW_ACCOUNTS_AVAILABLE")
        self.item.refresh_from_db()
        self.assertTrue(self.item.new_accounts_available)
        self.assertEqual(self.item.status, PlaidItem.STATUS_HEALTHY)
        self.assertTrue(self.item.needs_attention)

    @patch("apps.plaid.tasks.sync_plaid_transactions.delay")
    def test_login_repaired_clears_the_error_and_syncs(self, mock_delay):
        PlaidItem.objects.filter(pk=self.item.pk).update(status=PlaidItem.STATUS_LOGIN_REQUIRED)
        response = self.webhook("LOGIN_REPAIRED")
        self.assertEqual(response.json()["status"], "sync_queued")
        mock_delay.assert_called_once_with(self.item.pk)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_HEALTHY)


class SyncErrorTest(PlaidBookTestCase):
    def test_login_required_during_sync_is_recorded_not_raised(self):
        """Raising would retry into the same refusal; the user has to reconnect first."""
        with patch("apps.plaid.tasks.sync_transactions", side_effect=plaid_error("ITEM_LOGIN_REQUIRED")):
            result = sync_plaid_transactions(self.item.pk)
        self.assertEqual(result, {"success": False, "error_code": "ITEM_LOGIN_REQUIRED"})
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_LOGIN_REQUIRED)
        self.assertEqual(self.item.cursor, "c0")
        self.assertIsNone(self.item.sync_lock_until)
        failed = AuditEvent.objects.get(event_type=AuditEvent.PLAID_SYNC_FAILED)
        self.assertEqual(failed.metadata["error_code"], "ITEM_LOGIN_REQUIRED")

    def test_a_transient_error_leaves_the_status(self):
        with patch("apps.plaid.tasks.sync_transactions", side_effect=plaid_error("PRODUCT_NOT_READY")):
            result = sync_plaid_transactions(self.item.pk)
        self.assertFalse(result["success"])
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_HEALTHY)

    def test_an_unexpected_api_error_still_raises(self):
        with (
            patch("apps.plaid.tasks.sync_transactions", side_effect=plaid_error("INTERNAL_SERVER_ERROR")),
            self.assertRaises(ApiException),
            self.assertLogs("apps.plaid.tasks", level="ERROR"),
        ):
            sync_plaid_transactions(self.item.pk)

    def test_a_successful_sync_clears_an_error(self):
        PlaidItem.objects.filter(pk=self.item.pk).update(status=PlaidItem.STATUS_ERROR, error_code="NO_ACCOUNTS")
        page = {"added": [], "modified": [], "removed": [], "next_cursor": "c1", "has_more": False}
        with patch("apps.plaid.tasks.sync_transactions", return_value=page):
            sync_plaid_transactions(self.item.pk)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_HEALTHY)
        self.assertEqual(self.item.error_code, "")

    def test_a_successful_sync_keeps_an_expiry_warning(self):
        PlaidItem.objects.filter(pk=self.item.pk).update(status=PlaidItem.STATUS_PENDING_EXPIRATION)
        page = {"added": [], "modified": [], "removed": [], "next_cursor": "c1", "has_more": False}
        with patch("apps.plaid.tasks.sync_transactions", return_value=page):
            sync_plaid_transactions(self.item.pk)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_PENDING_EXPIRATION)

    def test_the_schedule_skips_items_waiting_for_the_user(self):
        from apps.plaid.tasks import sync_all_plaid_items

        PlaidItem.objects.filter(pk=self.item.pk).update(status=PlaidItem.STATUS_LOGIN_REQUIRED)
        with patch("apps.plaid.tasks.sync_plaid_transactions.apply_async") as apply_async:
            sync_all_plaid_items()
        apply_async.assert_not_called()


@override_settings(PLAID_WEBHOOK_URL="https://example.com/plaid/webhook/")
class UpdateModeTest(PlaidBookTestCase):
    def test_update_mode_request_carries_the_access_token_and_no_products(self):
        body = services.update_link_token_request(self.item, user_id=1).to_dict()
        self.assertEqual(body["access_token"], "access-sandbox-1")
        self.assertNotIn("products", body)
        self.assertNotIn("update", body)
        self.assertEqual(body["webhook"], "https://example.com/plaid/webhook/")

    def test_update_mode_offers_account_selection_when_new_accounts_exist(self):
        self.item.new_accounts_available = True
        body = services.update_link_token_request(self.item, user_id=1).to_dict()
        self.assertEqual(body["update"], {"account_selection_enabled": True})

    @patch("apps.plaid.services.get_plaid_client")
    def test_link_token_endpoint(self, get_client):
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "link-update-1"}
        get_client.return_value = client
        response = self.client.post(self.url(f"items/{self.item.pk}/link-token/"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"link_token": "link-update-1"})
        self.assertEqual(client.link_token_create.call_args.args[0].to_dict()["access_token"], "access-sandbox-1")

    @patch("apps.plaid.services.get_plaid_client", side_effect=RuntimeError("down"))
    def test_link_token_endpoint_failure(self, _client):
        with self.assertLogs("apps.plaid.views", level="ERROR"):
            response = self.client.post(self.url(f"items/{self.item.pk}/link-token/"))
        self.assertEqual(response.status_code, 502)

    @patch("apps.plaid.tasks.sync_plaid_transactions.delay")
    @patch(
        "apps.plaid.views.get_accounts",
        return_value=[
            {"account_id": "acc-checking", "name": "Chequing", "mask": "1234", "subtype": "checking", "type": "x"},
            {"account_id": "acc-tfsa", "name": "TFSA", "mask": "7777", "subtype": "tfsa", "type": "investment"},
        ],
    )
    def test_refresh_adds_new_accounts_and_clears_the_status(self, _accounts, mock_delay):
        PlaidItem.objects.filter(pk=self.item.pk).update(
            status=PlaidItem.STATUS_LOGIN_REQUIRED, new_accounts_available=True
        )
        response = self.client.post(self.url(f"items/{self.item.pk}/refresh/"))
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual([a["plaid_account_id"] for a in body["new_accounts"]], ["acc-tfsa"])
        self.assertEqual(body["item"]["status"], PlaidItem.STATUS_HEALTHY)
        self.assertFalse(body["item"]["needs_attention"])
        self.assertEqual(PlaidAccount.objects.filter(item=self.item).count(), 2)
        mock_delay.assert_called_once_with(self.item.pk)

    @patch("apps.plaid.views.get_accounts", side_effect=RuntimeError("down"))
    def test_refresh_failure_keeps_the_status(self, _accounts):
        PlaidItem.objects.filter(pk=self.item.pk).update(status=PlaidItem.STATUS_LOGIN_REQUIRED)
        with self.assertLogs("apps.plaid.views", level="ERROR"):
            response = self.client.post(self.url(f"items/{self.item.pk}/refresh/"))
        self.assertEqual(response.status_code, 502)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, PlaidItem.STATUS_LOGIN_REQUIRED)

    def test_outsider_cannot_open_update_mode(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.post(self.url(f"items/{self.item.pk}/link-token/"))
        self.assertIn(response.status_code, (403, 404))
