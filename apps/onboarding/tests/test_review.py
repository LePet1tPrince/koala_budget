"""
Tests for the chart-of-accounts review step.

The security-relevant property here is that the client posts *edits*, not a chart
of accounts: the server rebuilds the chart from the stored answers and applies the
edits to its own set. Several tests below exist to prove the things a wholesale
list would have allowed are simply not expressible.
"""

from django.test import SimpleTestCase

from apps.onboarding.services.builder import build_template
from apps.onboarding.services.review import (
    Edits,
    ReviewError,
    apply_edits,
    grouped_for_review,
    parse_edits,
)

ANSWERS = {
    "income_sources": ["employment"],
    "household_shape": ["solo"],
    "budget_future_income": "no",
    "housing": ["rent"],
    "kids": ["no"],
    "transport": ["transit"],
    "debts": ["none"],
    "savings": ["tfsa"],
    "extras": ["none"],
}


def _names(template):
    return [a["name"] for a in template["accounts"]]


class ParseEditsTest(SimpleTestCase):
    def test_reads_a_well_formed_payload(self):
        edits = parse_edits(
            {"removed": ["Rent"], "renamed": {"Groceries": "Food"}, "added": [{"group": "Income", "name": "Tips"}]}
        )

        self.assertEqual(edits.removed, ("Rent",))
        self.assertEqual(edits.renamed, (("Groceries", "Food"),))
        self.assertEqual(edits.added, (("Income", "Tips"),))

    def test_garbage_yields_no_edits_rather_than_raising(self):
        """A malformed payload gets the unedited chart, not a 500."""
        for payload in (None, [], "nope", 42, {"removed": "Rent"}, {"added": [{"group": 1}]}):
            with self.subTest(payload=payload):
                self.assertTrue(parse_edits(payload).is_empty)

    def test_non_string_entries_are_dropped(self):
        edits = parse_edits({"removed": ["Rent", 7, None], "renamed": {"Groceries": 5}})

        self.assertEqual(edits.removed, ("Rent",))
        self.assertEqual(edits.renamed, ())


class ApplyEditsTest(SimpleTestCase):
    def setUp(self):
        self.template = build_template(ANSWERS)

    def test_no_edits_changes_nothing(self):
        self.assertEqual(apply_edits(self.template, Edits()), self.template)

    def test_removal_drops_the_account(self):
        result = apply_edits(self.template, Edits(removed=("Rent",)))

        self.assertNotIn("Rent", _names(result))
        self.assertIn("Tenant Insurance", _names(result))

    def test_rename_keeps_the_account_in_its_group(self):
        result = apply_edits(self.template, Edits(renamed=(("Groceries", "Food & Drink"),)))

        renamed = next(a for a in result["accounts"] if a["name"] == "Food & Drink")
        original = next(a for a in self.template["accounts"] if a["name"] == "Groceries")
        self.assertEqual(renamed["group"], original["group"])
        self.assertNotIn("Groceries", _names(result))

    def test_addition_lands_in_the_named_group(self):
        result = apply_edits(self.template, Edits(added=(("Variable Expenses", "Concerts"),)))

        added = next(a for a in result["accounts"] if a["name"] == "Concerts")
        self.assertEqual(added["group"], "Variable Expenses")
        self.assertFalse(added["is_system"])

    def test_added_asset_accounts_get_a_feed(self):
        """Matches the accounts board: a bank reports assets and liabilities."""
        result = apply_edits(self.template, Edits(added=(("Bank Accounts", "Joint Chequing"),)))

        self.assertTrue(next(a for a in result["accounts"] if a["name"] == "Joint Chequing")["has_feed"])

    def test_added_expense_accounts_do_not(self):
        result = apply_edits(self.template, Edits(added=(("Variable Expenses", "Concerts"),)))

        self.assertFalse(next(a for a in result["accounts"] if a["name"] == "Concerts")["has_feed"])

    def test_emptying_a_group_drops_the_group(self):
        """A group with nothing in it would be clutter on the accounts board."""
        result = apply_edits(self.template, Edits(removed=("TFSA",)))

        self.assertNotIn("Investment Accounts", [g["name"] for g in result["account_groups"]])

    def test_edits_do_not_mutate_the_input(self):
        before = _names(self.template)
        apply_edits(self.template, Edits(removed=("Rent",), renamed=(("Groceries", "Food"),)))

        self.assertEqual(_names(self.template), before)


class EditsCannotBreakTheChartTest(SimpleTestCase):
    """What the edit-diff shape is for: the things it refuses."""

    def setUp(self):
        self.template = build_template(ANSWERS)

    def test_the_system_account_cannot_be_removed(self):
        """Reconciliation and opening balances post against it."""
        system = next(a for a in self.template["accounts"] if a["is_system"])

        with self.assertRaises(ReviewError):
            apply_edits(self.template, Edits(removed=(system["name"],)))

    def test_an_account_cannot_be_added_to_an_unknown_group(self):
        with self.assertRaises(ReviewError):
            apply_edits(self.template, Edits(added=(("Offshore Holdings", "Shell Co"),)))

    def test_a_blank_name_is_refused(self):
        with self.assertRaises(ReviewError):
            apply_edits(self.template, Edits(renamed=(("Groceries", "   "),)))

    def test_an_over_long_name_is_refused(self):
        with self.assertRaises(ReviewError):
            apply_edits(self.template, Edits(added=(("Variable Expenses", "x" * 201),)))

    def test_a_rename_that_collides_within_a_type_is_refused(self):
        with self.assertRaises(ReviewError):
            apply_edits(self.template, Edits(renamed=(("Groceries", "Dining Out"),)))

    def test_a_collision_is_caught_case_insensitively(self):
        with self.assertRaises(ReviewError):
            apply_edits(self.template, Edits(added=(("Variable Expenses", "groceries"),)))

    def test_the_same_name_in_a_different_type_is_allowed(self):
        """Uniqueness is per account type, matching AccountForm and the board."""
        result = apply_edits(self.template, Edits(added=(("Income", "Groceries"),)))

        self.assertEqual(_names(result).count("Groceries"), 2)

    def test_a_rename_freeing_a_name_lets_it_be_reused(self):
        result = apply_edits(
            self.template,
            Edits(renamed=(("Groceries", "Food"),), added=(("Variable Expenses", "Groceries"),)),
        )

        self.assertIn("Food", _names(result))
        self.assertEqual(_names(result).count("Groceries"), 1)


class GroupedForReviewTest(SimpleTestCase):
    def setUp(self):
        self.sections = grouped_for_review(build_template(ANSWERS))

    def test_sections_are_ordered_assets_first(self):
        self.assertEqual([s["type"] for s in self.sections], ["asset", "liability", "income", "expense"])

    def test_every_section_explains_its_type(self):
        """Most users meet double-entry vocabulary for the first time here."""
        for section in self.sections:
            with self.subTest(section=section["type"]):
                self.assertTrue(section["blurb"])

    def test_system_accounts_are_hidden(self):
        """They cannot be removed and explaining them here costs more than it's worth."""
        shown = {name for s in self.sections for g in s["groups"] for name in g["accounts"]}

        self.assertNotIn("Reconciliation Adjustments", shown)

    def test_no_empty_groups_are_shown(self):
        for section in self.sections:
            for group in section["groups"]:
                with self.subTest(group=group["name"]):
                    self.assertTrue(group["accounts"])

    def test_counts_match_the_accounts_listed(self):
        for section in self.sections:
            with self.subTest(section=section["type"]):
                self.assertEqual(section["count"], sum(len(g["accounts"]) for g in section["groups"]))
