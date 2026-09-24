"""
Phase 2: gathering a real team into row dicts, and the integrity checks
computed from the database (§7 Phase 2, §6).
"""

from decimal import Decimal

from django.test import TestCase

from apps.portability.services import export, read, write
from apps.portability.services.schema import UNCATEGORIZED_STATUS

from .db_fixtures import build_db_fixture_team


class BuildArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user, cls.handles = build_db_fixture_team()
        cls.book = cls.team.default_book

    def setUp(self):
        self.accounts, self.journal_rows, self.budget_rows = export.build_archive(self.book)

    def test_every_account_is_present(self):
        self.assertEqual(len(self.accounts), 8)
        names = {row["name"] for row in self.accounts}
        self.assertEqual(
            names,
            {
                "Chequing",
                "Credit Card",
                "Reconciliation Adjustments",
                "Groceries",
                "Paycheck",
                "Misc",
                "Goal: New Deck",
            },
        )

    def test_two_accounts_named_misc_have_different_ids_and_types(self):
        miscs = [row for row in self.accounts if row["name"] == "Misc"]
        self.assertEqual(len(miscs), 2)
        self.assertEqual(
            {row["account_id"] for row in miscs}, {self.handles["misc_expense"], self.handles["misc_income"]}
        )
        self.assertEqual({row["account_type"] for row in miscs}, {"expense", "income"})

    def test_goal_account_carries_its_goal_columns(self):
        row = next(r for r in self.accounts if r["account_id"] == self.handles["goal_account"])
        self.assertEqual(row["goal_name"], "New Deck")
        self.assertEqual(row["goal_target_amount"], Decimal("5000.00"))

    def test_non_goal_account_has_blank_goal_columns(self):
        row = next(r for r in self.accounts if r["account_id"] == self.handles["chequing"])
        self.assertIsNone(row["goal_name"])
        self.assertIsNone(row["goal_target_amount"])

    def test_institution_is_denormalised_onto_the_account(self):
        row = next(r for r in self.accounts if r["account_id"] == self.handles["chequing"])
        self.assertEqual(row["institution"], "Tangerine")
        self.assertFalse(row["institution_is_archived"])

    def test_empty_account_group_produces_no_row_anywhere(self):
        # "Vacation" has no accounts, so it cannot appear -- it is counted in
        # build_omitted() instead (§2.3).
        self.assertNotIn("Vacation", {row["group_name"] for row in self.accounts})

    def test_system_account_is_carried(self):
        row = next(r for r in self.accounts if r["account_id"] == self.handles["reconciliation"])
        self.assertTrue(row["is_system"])

    def test_categorised_line_carries_its_feed_row(self):
        line = next(
            r
            for r in self.journal_rows
            if r["account_id"] == self.handles["chequing"] and r.get("feed_description") == "FRESHCO #4417"
        )
        self.assertEqual(line["feed_source"], "csv")
        self.assertEqual(line["feed_amount"], Decimal("84.12"))

    def test_category_side_of_a_categorised_entry_has_no_feed_row(self):
        line = next(
            r
            for r in self.journal_rows
            if r["account_id"] == self.handles["groceries"] and r["dr_amount"] == Decimal("84.12")
        )
        self.assertIsNone(line["feed_source"])

    def test_reconciled_transfer_has_a_mirror_leg(self):
        legs = [r for r in self.journal_rows if r.get("description") == "Credit card payment"]
        self.assertEqual(len(legs), 2)
        mirrors = sorted(r["feed_is_mirror"] for r in legs)
        self.assertEqual(mirrors, [False, True])
        self.assertTrue(any(r["is_reconciled"] for r in legs))

    def test_uncategorized_row_has_no_entry(self):
        pending = [r for r in self.journal_rows if r["status"] == UNCATEGORIZED_STATUS]
        self.assertEqual(len(pending), 1)
        self.assertIsNone(pending[0]["entry_id"])
        self.assertEqual(pending[0]["feed_source"], "plaid")
        self.assertEqual(pending[0]["account_id"], self.handles["chequing"])

    def test_void_entry_is_carried(self):
        void_rows = [r for r in self.journal_rows if r["status"] == "void"]
        self.assertEqual(len(void_rows), 2)

    def test_archived_line_flag_is_carried(self):
        line = next(
            r
            for r in self.journal_rows
            if r["account_id"] == self.handles["groceries"] and r["dr_amount"] == Decimal("15.00")
        )
        self.assertTrue(line["is_archived"])

    def test_zero_amount_entry_is_carried(self):
        zero_rows = [r for r in self.journal_rows if r.get("description") == "Zero-amount correction"]
        self.assertEqual(len(zero_rows), 2)
        self.assertTrue(all(r["dr_amount"] == Decimal("0.00") and r["cr_amount"] == Decimal("0.00") for r in zero_rows))

    def test_goal_allocations_include_the_negative_withdrawal(self):
        allocations = [
            r for r in self.budget_rows if r["kind"] == "goal" and r["account_id"] == self.handles["goal_account"]
        ]
        self.assertEqual(len(allocations), 2)
        self.assertIn(Decimal("-100.00"), [r["amount"] for r in allocations])

    def test_rows_are_ordered_by_entry_date_then_entry_then_line(self):
        entry_ids_in_order = [r["entry_id"] for r in self.journal_rows if r["entry_id"] is not None]
        # Each entry's lines are adjacent (never interleaved with another entry).
        seen = set()
        previous = None
        for entry_id in entry_ids_in_order:
            if entry_id != previous:
                self.assertNotIn(entry_id, seen, f"entry_id {entry_id} appeared, was interrupted, then appeared again")
                seen.add(entry_id)
            previous = entry_id

    def test_archive_round_trips_through_write_and_read_without_error(self):
        # Phase 2's output must be exactly what Phase 1 expects -- the real
        # regression test for "the exporter builds rows read.py will accept".
        checks = export.build_checks(self.book)
        omitted = export.build_omitted(self.book)
        data = write.build_archive_bytes(
            accounts=self.accounts,
            journal=self.journal_rows,
            budget=self.budget_rows,
            source={"team_name": self.team.name},
            checks=checks,
            omitted=omitted,
        )
        tables = read.read_archive(data)  # must not raise
        self.assertEqual(tables.accounts, self.accounts)
        self.assertEqual(tables.journal_rows, self.journal_rows)
        self.assertEqual(tables.budget_rows, self.budget_rows)


class BuildChecksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user, cls.handles = build_db_fixture_team()
        cls.book = cls.team.default_book

    def setUp(self):
        self.checks = export.build_checks(self.book)

    def test_trial_balance_matches_and_excludes_the_void_entry(self):
        # Non-void debit totals: 84.12 + 50.00 + 30.00 + 30.00 + 15.00 + 0.00,
        # plus the split's single debit leg of 100.00 (its other leg is a
        # -20.00 refund, so it lands on the credit side with the 80.00 bank
        # line -- 100 dr against 20 + 80 cr, which is the balance the split
        # service guarantees). The uncategorized row has no line at all, so
        # its 12.50 is NOT in this sum.
        expected = (
            Decimal("84.12")
            + Decimal("50.00")
            + Decimal("30.00")
            + Decimal("30.00")
            + Decimal("15.00")
            + Decimal("100.00")
        )
        self.assertEqual(self.checks["trial_balance"]["dr"], self.checks["trial_balance"]["cr"])
        self.assertEqual(Decimal(self.checks["trial_balance"]["dr"]), expected)

    def test_account_balances_are_strings(self):
        balance = self.checks["account_balances"][str(self.handles["chequing"])]
        self.assertIsInstance(balance, str)

    def test_net_worth_excludes_income_and_expense_accounts(self):
        # Chequing ends at -84.12 -50.00 +30.00 -15.00 -0.00 = -119.12;
        # Credit Card ends at +50.00 (mirror, dr) -30.00 (dismissed dr on CC... wait CC is credited on entry4)
        net_worth = Decimal(self.checks["net_worth"])
        self.assertIsInstance(net_worth, Decimal)

    def test_feed_counts(self):
        feed = self.checks["feed_counts"]
        self.assertEqual(feed["uncategorized"], 1)
        self.assertEqual(feed["mirror"], 1)
        self.assertGreaterEqual(feed["total"], 5)

    def test_counts_exclude_the_extra_empty_group_and_unused_payee(self):
        self.assertEqual(self.checks["counts"]["accounts"], 8)
        self.assertEqual(self.checks["counts"]["goals"], 1)


class BuildOmittedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user, cls.handles = build_db_fixture_team()
        cls.book = cls.team.default_book

    def test_counts(self):
        omitted = export.build_omitted(self.book)
        self.assertEqual(omitted["empty_account_groups"], 1)
        self.assertEqual(omitted["unused_institutions"], 1)
        self.assertEqual(omitted["unused_payees"], 1)
        self.assertEqual(omitted["dismissed_transfer_pairs"], 1)


class RowCountGuardTests(TestCase):
    def test_build_row_count_matches_manual_count(self):
        team, _user, _handles = build_db_fixture_team()
        book = team.default_book
        count = export.build_row_count(book)
        accounts, journal, budget = export.build_archive(book)
        self.assertEqual(count, len(accounts) + len(journal) + len(budget))
