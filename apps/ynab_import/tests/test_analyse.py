"""
The inferences, measured against the sample export.

`docs/ynab-import-plan.md` asserts a figure for each of these, derived from the
sample by `docs/reference/checks/verify_ynab_assumptions.py`. Restating them here
turns those measurements into a test: if a change to the grouping or the pairing
quietly loses a transaction, one of these numbers moves.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from apps.ynab_import.services.analyse import (
    ASSET,
    INCOME,
    KIND_EXPENSE,
    KIND_GOAL,
    KIND_INVESTMENT,
    LIABILITY,
    NOT_INCOME,
    analyse,
    credit_card_accounts,
    group_splits,
    pair_transfers,
)
from apps.ynab_import.services.parse import parse_plan, parse_register

from .fixtures import TINY_PLAN, TINY_REGISTER, sample_analysis, tiny_analysis


class SampleStructureTest(SimpleTestCase):
    """The counts the plan document asserts, re-derived from the export itself."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.analysis = sample_analysis()

    def test_every_transfer_leg_pairs_off(self):
        self.assertEqual(self.analysis.transfer_pairs, 839)
        self.assertEqual(self.analysis.unmatched_transfers, [])

    def test_split_legs_group_into_parents(self):
        self.assertEqual(len(self.analysis.split_groups), 83)

    def test_starting_balance_rows(self):
        self.assertEqual(len(self.analysis.opening_rows), 21)

    def test_every_row_is_accounted_for(self):
        # 83 splits + 836 standalone transfer pairs + 21 opening + 5,704 plain. The
        # three pairs with one leg inside a split merge into that split's entry
        # rather than becoming entries of their own.
        self.assertEqual(self.analysis.entry_count, 6644)

    def test_accounts_and_their_types(self):
        self.assertEqual(len(self.analysis.accounts), 36)
        self.assertEqual(sum(1 for a in self.analysis.accounts if a.account_type == LIABILITY), 6)
        self.assertEqual(sum(1 for a in self.analysis.accounts if a.account_type == ASSET), 30)

    def test_on_budget_and_tracking(self):
        self.assertEqual(sum(1 for a in self.analysis.accounts if a.on_budget), 22)
        self.assertEqual(sum(1 for a in self.analysis.accounts if not a.on_budget), 14)

    def test_credit_cards_come_from_the_plan(self):
        cards = credit_card_accounts(self.analysis.plan)
        self.assertEqual(len(cards), 6)
        liabilities = {a.name for a in self.analysis.accounts if a.account_type == LIABILITY}
        self.assertEqual(cards, liabilities)

    def test_categories_drop_the_payment_envelopes(self):
        # 51 categories in the Plan, 6 of them credit-card payment envelopes that
        # never appear in the register and have nothing to map onto.
        self.assertEqual(len(self.analysis.categories), 45)
        self.assertFalse(any(c.group == "Credit Card Payments" for c in self.analysis.categories))

    def test_savings_categories_become_goals_except_the_carve_out(self):
        goals = {c.name for c in self.analysis.categories if c.kind == KIND_GOAL}
        self.assertEqual(goals, {"House", "Retirement", "RESP", "Emergency Fund"})

        # A valuation change wearing a savings label, and a spending category wearing
        # one: neither is a goal.
        kinds = {(c.group, c.name): c.kind for c in self.analysis.categories}
        self.assertEqual(kinds[("Savings", "Investment Gain/Loss")], KIND_INVESTMENT)
        self.assertEqual(kinds[("Savings", "Savings Expenses")], KIND_EXPENSE)

    def test_income_payees_and_the_bookkeeping_ones(self):
        payees = {f.payee: f for f in self.analysis.income_payees}
        self.assertEqual(payees["BBC Income"].count, 351)
        self.assertEqual(payees["BBC Income"].kind, INCOME)
        self.assertEqual(payees["reconcile"].kind, NOT_INCOME)
        self.assertEqual(payees["Reconciliation Balance Adjustment"].kind, NOT_INCOME)
        # `Starting Balance` is an opening balance, already claimed by that pass, so
        # the mapping screen never asks about it.
        self.assertNotIn("Starting Balance", payees)

    def test_payees(self):
        self.assertEqual(len(self.analysis.payees), 1123)
        self.assertFalse(any(name.startswith("Transfer : ") for name in self.analysis.payees))

    def test_plan_ordering_is_the_users_own(self):
        # The Plan lists its groups in one identical order in all 58 months, so that
        # order can be trusted as the arrangement the user chose.
        groups = [c.group for c in self.analysis.categories]
        first_seen = list(dict.fromkeys(groups))
        self.assertEqual(first_seen, ["Monthly", "Cumulative", "Tax Deductible", "Savings", "Hidden Categories"])


class PairingTest(SimpleTestCase):
    def test_two_identical_transfers_on_one_day_pair_one_to_one(self):
        rows = parse_register(
            b'"Account","Flag","Date","Payee","Category Group/Category","Category Group","Category",'
            b'"Memo","Outflow","Inflow","Cleared"\n'
            b'"A","","01-01-2024","Transfer : B","","","","",50.00$,0.00$,"Cleared"\n'
            b'"B","","01-01-2024","Transfer : A","","","","",0.00$,50.00$,"Cleared"\n'
            b'"A","","01-01-2024","Transfer : B","","","","",50.00$,0.00$,"Cleared"\n'
            b'"B","","01-01-2024","Transfer : A","","","","",0.00$,50.00$,"Cleared"\n'
        )
        mates, unmatched = pair_transfers(rows)
        self.assertEqual(len(mates), 4)
        self.assertEqual(unmatched, [])
        self.assertEqual({mates[0], mates[2]}, {1, 3})

    def test_a_leg_with_no_other_side_is_reported(self):
        rows = parse_register(
            b'"Account","Flag","Date","Payee","Category Group/Category","Category Group","Category",'
            b'"Memo","Outflow","Inflow","Cleared"\n'
            b'"A","","01-01-2024","Transfer : Gone","","","","",50.00$,0.00$,"Cleared"\n'
        )
        _mates, unmatched = pair_transfers(rows)
        self.assertEqual(unmatched, [0])


class SplitGroupingTest(SimpleTestCase):
    HEADER = (
        '"Account","Flag","Date","Payee","Category Group/Category","Category Group","Category",'
        '"Memo","Outflow","Inflow","Cleared"\n'
    )

    def test_two_different_splits_on_the_same_account_and_day(self):
        rows = parse_register(
            (
                self.HEADER
                + '"A","","01-01-2024","X","","","","Split (1/2)",1.00$,0.00$,"Cleared"\n'
                + '"A","","01-01-2024","X","","","","Split (2/2)",2.00$,0.00$,"Cleared"\n'
                + '"A","","01-01-2024","Y","","","","Split (1/2)",3.00$,0.00$,"Cleared"\n'
                + '"A","","01-01-2024","Y","","","","Split (2/2)",4.00$,0.00$,"Cleared"\n'
            ).encode()
        )
        self.assertEqual(group_splits(rows), [[0, 1], [2, 3]])

    def test_legs_that_are_not_contiguous(self):
        rows = parse_register(
            (
                self.HEADER
                + '"A","","01-01-2024","X","","","","Split (1/2)",1.00$,0.00$,"Cleared"\n'
                + '"A","","01-01-2024","Unrelated","","","","",9.00$,0.00$,"Cleared"\n'
                + '"A","","01-01-2024","X","","","","Split (2/2)",2.00$,0.00$,"Cleared"\n'
            ).encode()
        )
        self.assertEqual(group_splits(rows), [[0, 2]])

    def test_an_orphan_leg_is_warned_about_not_dropped(self):
        rows = parse_register(
            (self.HEADER + '"A","","01-01-2024","X","","","","Split (2/2)",1.00$,0.00$,"Cleared"\n').encode()
        )
        warnings = []
        self.assertEqual(group_splits(rows, warnings), [])
        self.assertEqual(len(warnings), 1)


class TinyExportTest(SimpleTestCase):
    def setUp(self):
        self.analysis = tiny_analysis()

    def test_types(self):
        types = {a.name: a.account_type for a in self.analysis.accounts}
        self.assertEqual(types, {"Chequing": ASSET, "Savings": ASSET, "Visa": LIABILITY})

    def test_tracking_account_has_no_categorised_row(self):
        tracking = {a.name for a in self.analysis.accounts if not a.on_budget}
        self.assertEqual(tracking, {"Savings"})

    def test_closing_balances(self):
        balances = {a.name: a.closing_balance for a in self.analysis.accounts}
        self.assertEqual(balances["Chequing"], Decimal("2120.00"))
        self.assertEqual(balances["Savings"], Decimal("301.25"))
        self.assertEqual(balances["Visa"], Decimal("-130.00"))

    def test_the_house_transfer_makes_a_goal(self):
        house = next(c for c in self.analysis.categories if c.name == "House")
        self.assertEqual(house.kind, KIND_GOAL)
        self.assertEqual(house.saved, Decimal("300.00"))


class MonthFirstExportTest(SimpleTestCase):
    def test_a_us_export_reads_correctly(self):
        register = TINY_REGISTER.replace("01-01-2024", "01/01/2024").replace("05-01-2024", "01/05/2024")
        register = register.replace("06-01-2024", "01/06/2024").replace("07-01-2024", "01/07/2024")
        register = register.replace("08-01-2024", "01/08/2024").replace("09-01-2024", "01/09/2024")
        analysis = analyse(parse_register(register.encode()), parse_plan(TINY_PLAN.encode()))
        self.assertEqual(len(analysis.accounts), 3)
        self.assertEqual(analysis.transfer_pairs, 1)
