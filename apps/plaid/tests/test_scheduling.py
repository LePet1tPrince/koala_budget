"""The sync lock and the scheduled catch-up sync."""

from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.plaid import sync_lock
from apps.plaid.models import PlaidItem
from apps.plaid.tasks import sync_all_plaid_items, sync_plaid_transactions

from .base import PlaidBookTestCase

EMPTY_PAGE = {"added": [], "modified": [], "removed": [], "next_cursor": "c1", "has_more": False}


class SyncLockTest(PlaidBookTestCase):
    def test_claim_is_exclusive_until_released(self):
        self.assertTrue(sync_lock.claim(self.item.pk))
        self.assertFalse(sync_lock.claim(self.item.pk))
        self.assertTrue(sync_lock.release(self.item.pk))
        self.assertTrue(sync_lock.claim(self.item.pk))

    def test_an_expired_lock_can_be_taken(self):
        """A worker killed mid-sync must not hold the item forever."""
        PlaidItem.objects.filter(pk=self.item.pk).update(sync_lock_until=timezone.now() - timedelta(seconds=1))
        self.assertTrue(sync_lock.claim(self.item.pk))

    def test_a_requested_rerun_keeps_the_lock_once(self):
        sync_lock.claim(self.item.pk)
        self.assertTrue(sync_lock.request_rerun(self.item.pk))
        self.assertFalse(sync_lock.release(self.item.pk), "go again")
        self.assertFalse(sync_lock.claim(self.item.pk), "still held for the rerun")
        self.assertTrue(sync_lock.release(self.item.pk))

    def test_no_rerun_without_a_running_sync(self):
        self.assertFalse(sync_lock.request_rerun(self.item.pk))


class LockedSyncTest(PlaidBookTestCase):
    def run_sync(self, **kwargs):
        with patch("apps.plaid.tasks.sync_transactions", return_value=EMPTY_PAGE) as mock_sync:
            result = sync_plaid_transactions(self.item.pk, **kwargs)
        return result, mock_sync

    def test_sync_releases_the_lock(self):
        result, _ = self.run_sync()
        self.assertTrue(result["success"])
        self.item.refresh_from_db()
        self.assertIsNone(self.item.sync_lock_until)

    def test_a_webhook_sync_during_a_running_sync_asks_it_to_go_again(self):
        sync_lock.claim(self.item.pk)
        result, mock_sync = self.run_sync()
        self.assertEqual(result, {"success": True, "status": "rerun_requested"})
        mock_sync.assert_not_called()
        self.item.refresh_from_db()
        self.assertTrue(self.item.sync_requested)

    def test_a_scheduled_sync_skips_a_busy_item(self):
        sync_lock.claim(self.item.pk)
        result, mock_sync = self.run_sync(scheduled=True)
        self.assertEqual(result, {"success": False, "status": "busy"})
        mock_sync.assert_not_called()
        self.item.refresh_from_db()
        self.assertFalse(self.item.sync_requested)

    def test_a_rerun_requested_mid_sync_runs_once_more(self):
        calls = []

        def fake_sync(**kwargs):
            calls.append(kwargs["cursor"])
            if len(calls) == 1:
                # A webhook lands while the first pass runs.
                self.assertEqual(sync_plaid_transactions(self.item.pk)["status"], "rerun_requested")
            return {**EMPTY_PAGE, "next_cursor": f"c{len(calls)}"}

        with patch("apps.plaid.tasks.sync_transactions", side_effect=fake_sync):
            sync_plaid_transactions(self.item.pk)
        self.assertEqual(calls, ["c0", "c1"])
        self.item.refresh_from_db()
        self.assertEqual(self.item.cursor, "c2")
        self.assertIsNone(self.item.sync_lock_until)

    def test_a_failed_sync_releases_the_lock(self):
        with (
            patch("apps.plaid.tasks.sync_transactions", side_effect=RuntimeError("down")),
            self.assertRaises(RuntimeError),
            self.assertLogs("apps.plaid.tasks", level="ERROR"),
        ):
            sync_plaid_transactions(self.item.pk)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.sync_lock_until)


@override_settings(
    PLAID_SCHEDULED_SYNC_MIN_AGE_HOURS=6, PLAID_SCHEDULED_SYNC_STAGGER_SECONDS=2, PLAID_SCHEDULED_SYNC_BATCH_SIZE=10
)
class ScheduledSyncTest(PlaidBookTestCase):
    def make_item(self, plaid_id, synced_hours_ago=None, **fields):
        synced = None if synced_hours_ago is None else timezone.now() - timedelta(hours=synced_hours_ago)
        return PlaidItem.objects.create(
            book=self.book,
            plaid_item_id=plaid_id,
            access_token="t",
            institution_name="Bank",
            last_synced_at=synced,
            **fields,
        )

    def queued(self):
        with patch("apps.plaid.tasks.sync_plaid_transactions.apply_async") as apply_async:
            sync_all_plaid_items()
        return [(c.kwargs["args"][0], c.kwargs["countdown"], c.kwargs["kwargs"]) for c in apply_async.call_args_list]

    def test_skips_recently_synced_items_and_staggers_the_rest_stalest_first(self):
        PlaidItem.objects.filter(pk=self.item.pk).update(last_synced_at=timezone.now() - timedelta(hours=1))
        stale = self.make_item("item-stale", synced_hours_ago=8)
        never = self.make_item("item-never")

        self.assertEqual(
            self.queued(),
            [(never.pk, 0, {"scheduled": True}), (stale.pk, 2, {"scheduled": True})],
        )

    def test_archived_items_are_left_alone(self):
        PlaidItem.objects.filter(pk=self.item.pk).update(is_archived=True)
        self.assertEqual(self.queued(), [])

    @override_settings(PLAID_SCHEDULED_SYNC_BATCH_SIZE=2)
    def test_a_run_is_capped(self):
        for n in range(4):
            self.make_item(f"item-batch-{n}")
        self.assertEqual(len(self.queued()), 2)

    def test_the_schedule_is_registered(self):
        from django.conf import settings

        task = settings.SCHEDULED_TASKS["plaid-sync-catch-up"]
        self.assertEqual(task["task"], "apps.plaid.tasks.sync_all_plaid_items")
