"""
What the import will write, before it writes anything.

`build` is pure, so these are the tests that can afford to be exhaustive: the
double-entry rules, the budget top-up that makes YNAB's `Available` reproducible,
and the reconciliation that gates the whole thing.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.ynab_import.services.analyse import KIND_EXPENSE, NOT_INCOME
from apps.ynab_import.services.build import (
    ASSET,
    BuildError,
    assert_sound,
    budget_amount,
    build,
    category_key,
    default_choices,
    parse_choices,
)
from apps.ynab_import.services.reconcile import reconcile

from .fixtures import sample_analysis, tiny_analysis

ZERO = Decimal("0")


class TinyBuildTest(SimpleTestCase):
    def setUp(self):
        self.analysis = tiny_analysis()
        self.plan = build(self.analysis)
        self.accounts = {account.key: account for account in self.plan.accounts}

    def entries_on(self, name, account_type=ASSET):
        key = (account_type, name)
        return [entry for entry in self.plan.entries if any(line.account == key for line in entry.lines)]

    def test_every_entry_balances(self):
        self.assertTrue(all(entry.balances for entry in self.plan.entries))

    def test_every_row_becomes_exactly_one_entry_or_opening(self):
        self.assertEqual(len(self.plan.entries) + len(self.plan.openings), self.analysis.entry_count)

    def test_an_expense_debits_the_category_and_credits_the_account(self):
        entry = next(e for e in self.plan.entries if e.description == "Weekly shop")
        lines = {line.account: line for line in entry.lines}
        self.assertEqual(lines[("asset", "Chequing")].cr, Decimal("80.00"))
        self.assertEqual(lines[("expense", "Groceries")].dr, Decimal("80.00"))

    def test_income_is_credited_to_an_account_named_after_the_payee(self):
        entry = next(e for e in self.plan.entries if e.description == "Pay day")
        lines = {line.account: line for line in entry.lines}
        self.assertEqual(lines[("asset", "Chequing")].dr, Decimal("2000.00"))
        self.assertEqual(lines[("income", "Employer")].cr, Decimal("2000.00"))

    def test_a_split_is_one_entry_with_a_line_per_leg(self):
        entry = next(e for e in self.plan.entries if len(e.lines) == 3)
        lines = {line.account: line for line in entry.lines}
        self.assertEqual(lines[("liability", "Visa")].cr, Decimal("10.00"))
        self.assertEqual(lines[("expense", "Groceries")].dr, Decimal("6.00"))
        self.assertEqual(lines[("expense", "Fun")].dr, Decimal("4.00"))

    def test_a_transfer_moves_money_without_touching_a_category(self):
        entry = next(e for e in self.plan.entries if e.description == "To savings")
        self.assertEqual(len(entry.lines), 2)
        lines = {line.account: line for line in entry.lines}
        self.assertEqual(lines[("asset", "Chequing")].cr, Decimal("300.00"))
        self.assertEqual(lines[("asset", "Savings")].dr, Decimal("300.00"))
        self.assertFalse(any(line.account[0] == "expense" for line in entry.lines))

    def test_a_categorised_transfer_funds_a_goal(self):
        goal = next(g for g in self.plan.goals if g.name == "House")
        self.assertEqual(goal.allocations, ((date(2024, 1, 1), Decimal("300.00")),))
        # The target is what has been saved, and the goal is left incomplete so it
        # stays editable rather than reading as finished.
        self.assertEqual(goal.target_amount, Decimal("300.00"))

    def test_each_leg_of_a_transfer_keeps_its_own_reconciliation_state(self):
        entry = next(e for e in self.plan.entries if e.description == "To savings")
        flags = {line.account[1]: line.is_reconciled for line in entry.lines}
        self.assertTrue(flags["Chequing"])
        self.assertFalse(flags["Savings"])

    def test_untracked_growth_on_a_tracking_account_becomes_investment_income(self):
        entry = next(e for e in self.plan.entries if e.description == "Monthly interest")
        lines = {line.account: line for line in entry.lines}
        self.assertEqual(lines[("income", "Investment Income")].cr, Decimal("1.25"))

    def test_starting_balances_are_signed_for_their_account_type(self):
        openings = {opening.account: opening for opening in self.plan.openings}
        self.assertEqual(openings[("asset", "Chequing")].amount, Decimal("500.00"))
        # A credit card's negative YNAB balance is a positive amount owed.
        self.assertEqual(openings[("liability", "Visa")].amount, Decimal("120.00"))
        self.assertEqual(openings[("asset", "Chequing")].as_of, date(2024, 1, 1))

    def test_credit_card_payment_categories_are_not_accounts(self):
        self.assertNotIn(("expense", "Visa"), self.accounts)

    def test_net_worth_is_the_sum_of_the_accounts(self):
        # 2,120 chequing + 301.25 savings - 130 owed on the card.
        self.assertEqual(self.plan.stats["net_worth"], "2291.25")


class ChoicesTest(SimpleTestCase):
    def setUp(self):
        self.analysis = tiny_analysis()

    def test_an_account_can_be_retyped_and_renamed(self):
        choices = parse_choices(
            self.analysis,
            {"accounts": {"Savings": {"name": "Rainy Day", "account_type": "liability", "group": "Loans"}}},
        )
        plan = build(self.analysis, choices)
        names = {account.name for account in plan.accounts}
        self.assertIn("Rainy Day", names)
        self.assertNotIn("Savings", names)
        self.assertEqual(next(a for a in plan.accounts if a.name == "Rainy Day").account_type, "liability")

    def test_a_dropped_account_takes_its_rows_with_it(self):
        choices = parse_choices(self.analysis, {"accounts": {"Savings": {"skip": True}}})
        plan = build(self.analysis, choices)
        self.assertNotIn(("asset", "Savings"), {account.key for account in plan.accounts})
        # The transfer's other side still has to go somewhere, or the entry would not
        # balance: it lands on the equity offset.
        entry = next(e for e in plan.entries if e.description == "To savings")
        self.assertEqual(
            {line.account for line in entry.lines},
            {("asset", "Chequing"), ("goal", "Reconciliation Adjustments")},
        )

    def test_a_payee_marked_not_income_posts_to_equity(self):
        choices = parse_choices(self.analysis, {"income": {"Employer": {"kind": NOT_INCOME}}})
        plan = build(self.analysis, choices)
        entry = next(e for e in plan.entries if e.description == "Pay day")
        self.assertIn(("goal", "Reconciliation Adjustments"), {line.account for line in entry.lines})
        self.assertNotIn(("income", "Employer"), {account.key for account in plan.accounts})

    def test_a_savings_category_can_be_made_a_spending_category(self):
        choices = parse_choices(
            self.analysis, {"categories": {category_key("Savings", "House"): {"kind": KIND_EXPENSE}}}
        )
        plan = build(self.analysis, choices)
        self.assertEqual(plan.goals, [])
        # It is still a transfer: a move between the user's own accounts cannot post
        # to a spending category without misstating net worth.
        entry = next(e for e in plan.entries if e.description == "To savings")
        self.assertEqual(len(entry.lines), 2)

    def test_a_payload_naming_things_the_export_does_not_have_is_ignored(self):
        choices = parse_choices(
            self.analysis,
            {"accounts": {"Nonexistent": {"skip": True}}, "income": {"Nobody": {"kind": "income"}}, "categories": 7},
        )
        self.assertEqual(choices.accounts.keys(), default_choices(self.analysis).accounts.keys())

    def test_an_invalid_account_type_falls_back_rather_than_being_accepted(self):
        choices = parse_choices(self.analysis, {"accounts": {"Chequing": {"account_type": "income"}}})
        self.assertEqual(choices.accounts["Chequing"].account_type, ASSET)


class BudgetTest(SimpleTestCase):
    def test_the_top_up_is_the_reset_ynab_performed(self):
        # x + max(0, -x) is exactly YNAB's "reset a negative Available to zero".
        self.assertEqual(budget_amount(Decimal("20"), Decimal("-4")), Decimal("24"))
        self.assertEqual(budget_amount(Decimal("20"), Decimal("5")), Decimal("20"))
        self.assertEqual(budget_amount(Decimal("20"), None), Decimal("20"))

    def test_income_budgets_are_back_filled_from_actual_income(self):
        plan = build(tiny_analysis())
        rows = {(spec.category, spec.month): spec.amount for spec in plan.budgets if spec.category[0] == "income"}
        # January's pay, and nothing invented for a month with no income.
        self.assertEqual(rows[(("income", "Employer"), date(2024, 1, 1))], Decimal("2000.00"))
        self.assertNotIn((("income", "Employer"), date(2024, 2, 1)), rows)

    def test_goal_categories_get_no_budget_rows(self):
        plan = build(tiny_analysis())
        self.assertNotIn(("expense", "House"), {spec.category for spec in plan.budgets})


class SoundnessTest(SimpleTestCase):
    """
    The invariants `build` refuses to return without.

    Checked directly rather than through a contrived export: what matters is that a
    plan which has lost a row, or carries an entry that does not balance, cannot be
    handed to `apply` -- however it came to be that way.
    """

    def setUp(self):
        self.analysis = tiny_analysis()
        self.plan = build(self.analysis)
        self.everything = set(range(len(self.analysis.register)))

    def test_a_row_that_reaches_no_entry_is_refused(self):
        with self.assertRaisesMessage(BuildError, "reached no transaction"):
            assert_sound(self.plan, self.analysis, self.everything - {0})

    def test_an_entry_that_does_not_balance_is_refused(self):
        broken = self.plan.entries[0]
        self.plan.entries[0] = replace(broken, lines=broken.lines[:1])
        with self.assertRaisesMessage(BuildError, "do not balance"):
            assert_sound(self.plan, self.analysis, self.everything)

    def test_a_line_pointing_at_an_account_that_was_never_created_is_refused(self):
        self.plan.accounts = [a for a in self.plan.accounts if a.key != ("expense", "Groceries")]
        with self.assertRaisesMessage(BuildError, "did not create"):
            assert_sound(self.plan, self.analysis, self.everything)


class SampleBuildTest(SimpleTestCase):
    """The real export, end to end -- still without touching a database."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.analysis = sample_analysis()
        cls.plan = build(cls.analysis)

    def test_every_row_is_imported(self):
        # Every one of the 7,572 rows is accounted for: 6,623 transactions, 13
        # opening balances, and 8 `Starting Balance` rows for accounts that were
        # added empty and so carry no entry.
        self.assertEqual(
            len(self.plan.entries) + len(self.plan.openings) + self.plan.stats["zero_openings"],
            self.analysis.entry_count,
        )
        self.assertEqual(len(self.plan.entries), 6623)
        self.assertEqual(self.plan.stats["lines"], 13335)

    def test_every_entry_balances(self):
        self.assertTrue(all(entry.balances for entry in self.plan.entries))

    def test_goals_from_the_savings_categories(self):
        # `House` is missing on purpose: this budget saved for a house and then
        # bought one, so as much came back out of that category as ever went in. A
        # goal reading "$20,464 still to save" for money that was spent on purpose
        # would be worse than no goal.
        self.assertEqual({goal.name for goal in self.plan.goals}, {"Retirement", "RESP", "Emergency Fund"})
        self.assertEqual(self.plan.stats["spent_goals"], 1)
        self.assertTrue(all(goal.target_amount > ZERO for goal in self.plan.goals))

    def test_reconciliation_passes(self):
        result = reconcile(self.analysis, self.plan)
        for check in result.checks:
            self.assertTrue(check.passed, f"{check.label}: {check.samples[:3]}")
        self.assertTrue(result.passed)

    def test_available_matches_ynab_in_every_month(self):
        check = next(c for c in reconcile(self.analysis, self.plan).checks if c.name == "available")
        self.assertEqual(check.mismatched, 0)
        # Every month of every category that became a budget category, not a sample.
        self.assertGreater(check.checked, 2000)

    def test_hidden_categories_are_parked_at_the_bottom(self):
        hidden = next(group for group in self.plan.groups if group.name == "Hidden Categories")
        others = [g.sort_order for g in self.plan.groups if g.account_type == "expense" and g.name != hidden.name]
        self.assertGreater(hidden.sort_order, max(others))

    def test_the_summary_says_what_was_inferred(self):
        joined = " ".join(self.plan.notes)
        self.assertIn("YNAB's Assigned column", joined)
        self.assertIn("savings categor", joined)
        self.assertIn("currency", joined)
