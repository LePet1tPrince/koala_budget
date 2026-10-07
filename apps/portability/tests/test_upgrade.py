"""
The format_version upgrade chain (§3.7, §7 Phase 1).

Version 2 added statements. A version-1 archive must still import -- without
statements, which it never carried -- and anything older than version 1 is
refused by name.
"""

from django.test import SimpleTestCase

from apps.portability.services import upgrade
from apps.portability.services.schema import FORMAT_VERSION, DocumentError


class UpgradeChainTests(SimpleTestCase):
    def test_current_version_is_a_no_op(self):
        tables = {"accounts": []}
        result = upgrade.upgrade_to_current(tables, from_version=FORMAT_VERSION)
        self.assertIs(result, tables)

    def test_version_zero_is_refused(self):
        with self.assertRaises(DocumentError) as ctx:
            upgrade.upgrade_to_current({}, from_version=0)
        self.assertIn("format version 0", str(ctx.exception))

    def test_chain_covers_every_version_since_1(self):
        # A reviewer's tripwire: bumping FORMAT_VERSION without a step here
        # would refuse every export made before the bump.
        self.assertEqual(sorted(upgrade.CHAIN), list(range(1, FORMAT_VERSION)))

    def test_v2_goals_arrive_open(self):
        tables = {"accounts": [{"goal_name": "Car"}], "journal_rows": [], "budget_rows": [], "reconciliations": []}
        result = upgrade.upgrade_to_current(tables, from_version=2)
        self.assertIsNone(result["accounts"][0]["goal_closed_at"])

    def test_v3_categories_arrive_shown(self):
        tables = {"accounts": [{"name": "Dining"}], "journal_rows": [], "budget_rows": [], "reconciliations": []}
        result = upgrade.upgrade_to_current(tables, from_version=3)
        self.assertFalse(result["accounts"][0]["hidden_from_budget"])

    def test_v5_accounts_arrive_shown(self):
        tables = {"accounts": [{"name": "Chequing"}], "journal_rows": [], "budget_rows": [], "reconciliations": []}
        result = upgrade.upgrade_to_current(tables, from_version=5)
        self.assertFalse(result["accounts"][0]["is_hidden"])

    def test_v1_gains_an_empty_statement_table_and_unlinked_lines(self):
        tables = {"accounts": [], "journal_rows": [{"entry_id": 1}], "budget_rows": [], "reconciliations": []}
        result = upgrade.upgrade_to_current(tables, from_version=1)
        self.assertEqual(result["reconciliations"], [])
        self.assertIsNone(result["journal_rows"][0]["reconciliation_id"])


class VoidUpgradeTests(SimpleTestCase):
    """Version 6 has one void state: an archived row's entry is voided, and so is every row on a void entry."""

    def _row(self, entry_id, status="posted", feed_source=None, archived=False):
        return {
            "entry_id": entry_id,
            "status": status,
            "feed_source": feed_source,
            "feed_is_archived": archived,
            "feed_archived_at": None,
            "entry_is_archived": False,
            "entry_archived_at": None,
            "is_archived": False,
            "archived_at": None,
        }

    def _upgrade(self, rows):
        tables = {"accounts": [], "journal_rows": rows, "budget_rows": [], "reconciliations": [], "goal_links": []}
        return upgrade.upgrade_6_to_7(tables)

    def test_an_archived_row_voids_its_entry_and_its_sibling_rows(self):
        rows = [
            self._row(1, feed_source="plaid", archived=True),
            self._row(1, feed_source="system"),  # the transfer's mirror leg
            self._row(2, feed_source="csv"),
        ]
        result = self._upgrade(rows)
        by_entry = [(r["entry_id"], r["status"], r["feed_is_void"]) for r in result["journal_rows"]]
        self.assertEqual(by_entry, [(1, "void", True), (1, "void", True), (2, "posted", False)])
        self.assertEqual(result["void_upgrade"], {"entry_ids": {1}, "rows": 1})

    def test_rows_on_an_already_void_entry_are_voided_without_counting_the_entry(self):
        result = self._upgrade([self._row(3, status="void", feed_source="csv")])
        self.assertTrue(result["journal_rows"][0]["feed_is_void"])
        self.assertEqual(result["void_upgrade"], {"entry_ids": set(), "rows": 1})

    def test_retired_columns_are_dropped(self):
        row = self._upgrade([self._row(4)])["journal_rows"][0]
        for retired in ("entry_is_archived", "entry_archived_at", "is_archived", "archived_at", "feed_is_archived"):
            self.assertNotIn(retired, row)

    def test_an_archived_uncategorized_row_stays_void_on_its_own(self):
        row = self._row(None, status="uncategorized", feed_source="csv", archived=True)
        result = self._upgrade([row])
        self.assertTrue(result["journal_rows"][0]["feed_is_void"])
        self.assertEqual(result["void_upgrade"]["entry_ids"], set())


class GoalLinksUpgradeTests(SimpleTestCase):
    def test_v4_gains_no_links_and_default_goal_settings(self):
        tables = {
            "accounts": [{"name": "Goal: Car"}],
            "journal_rows": [],
            "budget_rows": [],
            "reconciliations": [],
        }
        result = upgrade.upgrade_to_current(tables, from_version=4)
        self.assertEqual(result["goal_links"], [])
        self.assertIsNone(result["accounts"][0]["goal_outflow"])
        self.assertIsNone(result["accounts"][0]["goal_monthly_contribution"])
