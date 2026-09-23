"""
Round-trip fidelity: write the fixture tables, read them back, and get
exactly what was written (§7 Phase 5's headline test, exercised early since
Phase 1 has both halves of the pipe already).
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from django.test import SimpleTestCase

from apps.portability.services import read, write
from apps.portability.tests.fixtures import build_fixture_tables


class RoundTripTests(SimpleTestCase):
    def setUp(self):
        self.accounts, self.journal_rows, self.budget_rows = build_fixture_tables()
        self.data = write.build_archive_bytes(
            accounts=self.accounts,
            journal=self.journal_rows,
            budget=self.budget_rows,
            source={"team_name": "Fixture Team", "app_version": "test", "currency": "CAD"},
            checks={"trial_balance": {"dr": "169.12", "cr": "169.12"}},
            omitted={"empty_account_groups": 0, "unused_payees": 0},
            exported_at=datetime(2026, 1, 25, 9, 0, tzinfo=UTC),
        )
        self.tables = read.read_archive(self.data)

    def test_accounts_round_trip_exactly(self):
        self.assertEqual(self.tables.accounts, self.accounts)

    def test_journal_rows_round_trip_exactly(self):
        self.assertEqual(self.tables.journal_rows, self.journal_rows)

    def test_budget_rows_round_trip_exactly(self):
        self.assertEqual(self.tables.budget_rows, self.budget_rows)

    def test_no_hash_warnings_on_an_untouched_archive(self):
        self.assertEqual(self.tables.hash_warnings, [])

    def test_manifest_format_and_version(self):
        self.assertEqual(self.tables.manifest.format, "koala-budget-export")
        self.assertEqual(self.tables.manifest.format_version, 2)

    def test_manifest_file_row_counts(self):
        self.assertEqual(self.tables.manifest.files["accounts.csv"]["rows"], len(self.accounts))
        self.assertEqual(self.tables.manifest.files["journal.csv"]["rows"], len(self.journal_rows))
        self.assertEqual(self.tables.manifest.files["budget.csv"]["rows"], len(self.budget_rows))

    # --- the specific corners named in §7 Phase 1, checked by name so a
    # regression in one shows up as *which* corner broke, not just "the
    # fixture stopped matching" ------------------------------------------

    def test_void_entry_is_carried_and_still_balances(self):
        void_rows = [r for r in self.tables.journal_rows if r["entry_id"] == 300]
        self.assertEqual(len(void_rows), 2)
        self.assertTrue(all(r["status"] == "void" for r in void_rows))
        self.assertEqual(sum(r["dr_amount"] for r in void_rows), sum(r["cr_amount"] for r in void_rows))

    def test_archived_line_is_distinct_from_archived_entry_and_archived_feed_row(self):
        line = next(r for r in self.tables.journal_rows if r["entry_id"] == 400 and r["account_id"] == 4)
        self.assertTrue(line["is_archived"])  # the JournalLine's own flag
        self.assertFalse(line["entry_is_archived"])  # the JournalEntry is not archived
        other_line = next(r for r in self.tables.journal_rows if r["entry_id"] == 400 and r["account_id"] == 1)
        self.assertFalse(other_line["feed_is_archived"])  # nor is its feed row

    def test_reconciled_transfer_has_two_feed_legs_one_marked_mirror(self):
        legs = [r for r in self.tables.journal_rows if r["entry_id"] == 200]
        self.assertEqual(len(legs), 2)
        self.assertTrue(all(r["feed_source"] for r in legs), "both legs of this transfer have a feed row")
        mirrors = [r["feed_is_mirror"] for r in legs]
        self.assertEqual(sorted(mirrors), [False, True])
        self.assertTrue(any(r["is_reconciled"] for r in legs))

    def test_zero_amount_entry_balances_trivially(self):
        rows = [r for r in self.tables.journal_rows if r["entry_id"] == 500]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["dr_amount"] == Decimal("0.00") and r["cr_amount"] == Decimal("0.00") for r in rows))

    def test_uncategorized_row_has_no_entry_and_is_excluded_from_entry_grouping(self):
        pending = [r for r in self.tables.journal_rows if r["status"] == "uncategorized"]
        self.assertEqual(len(pending), 1)
        self.assertIsNone(pending[0]["entry_id"])
        self.assertEqual(pending[0]["feed_source"], "plaid")

    def test_system_account_is_carried(self):
        system_accounts = [a for a in self.tables.accounts if a["is_system"]]
        self.assertEqual(len(system_accounts), 1)
        self.assertEqual(system_accounts[0]["name"], "Reconciliation Adjustments")

    def test_goal_with_negative_allocation_round_trips(self):
        goal_account = next(a for a in self.tables.accounts if a["goal_name"] == "New Deck")
        self.assertEqual(goal_account["goal_target_amount"], Decimal("5000.00"))
        goal_account_id = goal_account["account_id"]
        allocations = [r for r in self.tables.budget_rows if r["kind"] == "goal" and r["account_id"] == goal_account_id]
        self.assertEqual(len(allocations), 2)
        amounts = sorted(r["amount"] for r in allocations)
        self.assertEqual(amounts, [Decimal("-100.00"), Decimal("300.00")])

    def test_two_accounts_share_a_name_across_types_without_colliding(self):
        miscs = [a for a in self.tables.accounts if a["name"] == "Misc"]
        self.assertEqual(len(miscs), 2)
        self.assertEqual({a["account_id"] for a in miscs}, {10, 11})
        self.assertEqual({a["account_type"] for a in miscs}, {"expense", "income"})

    def test_split_keeps_all_three_lines_on_one_entry(self):
        rows = [r for r in self.tables.journal_rows if r["entry_id"] == 700]
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["description"] for r in rows}, {"Costco run"})

    def test_split_balances_with_legs_on_opposite_sides(self):
        rows = [r for r in self.tables.journal_rows if r["entry_id"] == 700]
        dr = sum(r["dr_amount"] for r in rows)
        cr = sum(r["cr_amount"] for r in rows)
        self.assertEqual(dr, cr)
        self.assertEqual(dr, Decimal("100.00"))  # 100 dr vs 20 + 80 cr

    def test_only_the_splits_bank_line_carries_the_feed_row(self):
        # The feed row belongs to the account the bank reported, not to each
        # leg -- so exactly one of the three rows has feed_* columns.
        rows = [r for r in self.tables.journal_rows if r["entry_id"] == 700]
        with_feed = [r for r in rows if r["feed_source"] is not None]
        self.assertEqual(len(with_feed), 1)
        self.assertEqual(with_feed[0]["account_name"], "Chequing")
        self.assertEqual(with_feed[0]["feed_amount"], Decimal("80.00"))

    def test_a_splits_legs_are_not_mirrors(self):
        # A split has no counterpart leg to mirror; nothing in it may claim to
        # be one, or the feed would show a phantom row for the whole amount.
        rows = [r for r in self.tables.journal_rows if r["entry_id"] == 700]
        self.assertTrue(all(r["feed_is_mirror"] is False for r in rows))


class AccentedPayeeUtf8Tests(SimpleTestCase):
    """UTF-8-with-BOM round trip, since a payee name is exactly where this bites."""

    def test_accented_payee_survives_the_bom(self):
        accounts = [
            {
                "account_id": 1,
                "name": "Chequing",
                "account_type": "asset",
                "group_name": "Chequing",
                "group_description": "",
                "group_is_system": False,
                "group_sort_order": 0,
                "group_is_archived": False,
                "group_archived_at": None,
                "institution": "Caisse Populaire Désjardins",
                "institution_is_archived": False,
                "institution_archived_at": None,
                "has_feed": True,
                "is_system": False,
                "sort_order": 0,
                "is_archived": False,
                "archived_at": None,
                "goal_name": None,
                "goal_description": "",
                "goal_target_amount": None,
                "goal_target_date": None,
                "goal_is_complete": None,
                "goal_is_archived": None,
                "goal_archived_at": None,
                "goal_order": None,
            },
            {
                "account_id": 2,
                "name": "Café expenses",
                "account_type": "expense",
                "group_name": "Household",
                "group_description": "",
                "group_is_system": False,
                "group_sort_order": 0,
                "group_is_archived": False,
                "group_archived_at": None,
                "institution": None,
                "institution_is_archived": None,
                "institution_archived_at": None,
                "has_feed": False,
                "is_system": False,
                "sort_order": 0,
                "is_archived": False,
                "archived_at": None,
                "goal_name": None,
                "goal_description": "",
                "goal_target_amount": None,
                "goal_target_date": None,
                "goal_is_complete": None,
                "goal_is_archived": None,
                "goal_archived_at": None,
                "goal_order": None,
            },
        ]
        journal_rows = [
            {
                "entry_id": 1,
                "entry_date": date(2026, 1, 1),
                "payee": "François Café & Bar",
                "description": "Café crème",
                "source": "manual",
                "status": "posted",
                "account_id": 2,
                "account_name": "Café expenses",
                "entry_is_archived": False,
                "entry_archived_at": None,
                "dr_amount": Decimal("5.50"),
                "cr_amount": Decimal("0.00"),
                "is_cleared": False,
                "is_reconciled": False,
                "is_archived": False,
                "archived_at": None,
                "reconciliation_id": None,
                "feed_source": None,
                "feed_amount": None,
                "feed_posted_date": None,
                "feed_description": "",
                "feed_merchant": None,
                "feed_is_mirror": False,
                "feed_is_archived": False,
                "feed_archived_at": None,
            },
            {
                "entry_id": 1,
                "entry_date": date(2026, 1, 1),
                "payee": "François Café & Bar",
                "description": "Café crème",
                "source": "manual",
                "status": "posted",
                "account_id": 1,
                "account_name": "Chequing",
                "entry_is_archived": False,
                "entry_archived_at": None,
                "dr_amount": Decimal("0.00"),
                "cr_amount": Decimal("5.50"),
                "is_cleared": False,
                "is_reconciled": False,
                "is_archived": False,
                "archived_at": None,
                "reconciliation_id": None,
                "feed_source": None,
                "feed_amount": None,
                "feed_posted_date": None,
                "feed_description": "",
                "feed_merchant": None,
                "feed_is_mirror": False,
                "feed_is_archived": False,
                "feed_archived_at": None,
            },
        ]
        data = write.build_archive_bytes(
            accounts=accounts, journal=journal_rows, budget=[], source={}, checks={}, omitted={}
        )
        tables = read.read_archive(data)
        self.assertEqual(tables.accounts, accounts)
        self.assertEqual(tables.journal_rows, journal_rows)
        self.assertEqual(
            {r["payee"] for r in tables.journal_rows},
            {"François Café & Bar"},
        )
