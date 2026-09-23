"""
Tests for editing a transaction from the Transactions page.

Two things are being protected here. First, that an edit lands on the line the
user meant -- `resolve_sides` is what stands between "change the category" and
"move money between the wrong two accounts". Second, that the Bank Feed and the
ledger keep telling the same story: most rows on the Transactions page are backed
by a `BankTransaction`, and an editor that updates only the journal entry is
worse than no editor at all.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
    Payee,
)
from apps.audit.models import AuditEvent, AuditLog
from apps.bank_feed.models import BankTransaction
from apps.budget.models import Budget
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

from .models import JournalEntry, JournalLine
from .services.sides import UnsupportedEntry, resolve_sides
from .services.simple_edit import (
    UNSET,
    EditRefused,
    TransactionEdits,
    apply_edits,
    apply_edits_bulk,
    delete_transaction,
    set_status,
)


class TransactionEditTestCase(TestCase):
    """Shared chart of accounts and entry builders."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Edit Team", slug="edit-team")
        cls.user = CustomUser.objects.create_user(username="edituser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.member = CustomUser.objects.create_user(username="plainmember", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

        cls.other_team = Team.objects.create(name="Other Team", slug="other-edit-team")
        cls.outsider = CustomUser.objects.create_user(username="outsider", password="pass")
        cls.other_team.members.add(cls.outsider, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.liability_group = AccountGroup.objects.create(
            team=cls.team, name="Credit Cards", account_type=ACCOUNT_TYPE_LIABILITY
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME)
        cls.equity_group = AccountGroup.objects.create(
            team=cls.team, name="Equity Adjustments", account_type=ACCOUNT_TYPE_EQUITY, is_system=True
        )

        cls.chequing = Account.objects.create(
            team=cls.team, name="Chequing", account_group=cls.asset_group, has_feed=True
        )
        cls.savings = Account.objects.create(
            team=cls.team, name="Savings", account_group=cls.asset_group, has_feed=True
        )
        cls.cash = Account.objects.create(team=cls.team, name="Cash", account_group=cls.asset_group, has_feed=False)
        cls.visa = Account.objects.create(team=cls.team, name="Visa", account_group=cls.liability_group, has_feed=True)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)
        cls.household = Account.objects.create(team=cls.team, name="Household Goods", account_group=cls.expense_group)
        cls.dining = Account.objects.create(team=cls.team, name="Dining", account_group=cls.expense_group)
        cls.salary = Account.objects.create(team=cls.team, name="Salary", account_group=cls.income_group)
        cls.opening = Account.objects.create(
            team=cls.team, name="Reconciliation Adjustments", account_group=cls.equity_group, is_system=True
        )

        other_group = AccountGroup.objects.create(
            team=cls.other_team, name="Their Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.foreign_account = Account.objects.create(
            team=cls.other_team, name="Their Groceries", account_group=other_group
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # --- builders --------------------------------------------------------

    def make_entry(self, *, lines, entry_date=date(2026, 9, 14), description="Costco", status=None, payee=None):
        """
        An entry from explicit `(account, dr, cr)` triples.

        Deliberately not routed through the writer under test: these fixtures have
        to be able to express shapes the writer would refuse.
        """
        entry = JournalEntry.objects.create(
            team=self.team,
            entry_date=entry_date,
            description=description,
            payee=payee,
            source=JournalEntry.SOURCE_BANK_MATCH,
            status=status or JournalEntry.STATUS_POSTED,
        )
        for account, dr, cr, *rest in lines:
            JournalLine.objects.create(
                journal_entry=entry,
                team=self.team,
                account=account,
                dr_amount=Decimal(dr),
                cr_amount=Decimal(cr),
                is_reconciled=rest[0] if rest else False,
            )
        return entry

    def make_plain(self, *, account=None, category=None, amount="40.00", reconciled=False, **kwargs):
        """An outflow: money leaves `account` and lands in `category`."""
        account = account or self.chequing
        category = category or self.groceries
        return self.make_entry(
            lines=[(account, "0", amount, reconciled), (category, amount, "0")],
            **kwargs,
        )

    def make_split(self, *, account=None, legs=None, reconciled=False, **kwargs):
        """One line on the account carrying the total, one counter line per leg."""
        account = account or self.chequing
        legs = legs or [(self.groceries, Decimal("160.00")), (self.household, Decimal("50.40"))]
        total = sum(amount for _, amount in legs)
        lines = [(account, "0", str(total), reconciled)]
        lines += [(category, str(amount), "0") for category, amount in legs]
        return self.make_entry(lines=lines, **kwargs)

    def assertBalanced(self, entry):
        entry.refresh_from_db()
        self.assertEqual(
            entry.total_debits,
            entry.total_credits,
            f"Entry {entry.id} does not balance: {entry.total_debits} != {entry.total_credits}",
        )

    def legs_of(self, entry, home):
        """`{account name: signed amount}` for every line but the home account's."""
        return {
            line.account.name: line.dr_amount - line.cr_amount
            for line in entry.lines.all()
            if line.account_id != home.id
        }


class ResolveSidesTest(TransactionEditTestCase):
    """Which line is the account, and which are the categories."""

    def test_plain_expense_resolves_bank_account_as_home(self):
        entry = self.make_plain()
        sides = resolve_sides(entry)

        self.assertEqual(sides.account, self.chequing)
        self.assertEqual([leg.account for leg in sides.legs], [self.groceries])
        self.assertFalse(sides.is_split)
        self.assertTrue(sides.normal)
        self.assertEqual(sides.total, Decimal("40.00"))

    def test_income_resolves_bank_account_as_home(self):
        entry = self.make_entry(lines=[(self.chequing, "2000", "0"), (self.salary, "0", "2000")])
        sides = resolve_sides(entry)

        self.assertEqual(sides.account, self.chequing)
        self.assertEqual(sides.inflow, Decimal("2000"))
        # An inflow is a negative total in the feed's signed convention.
        self.assertEqual(sides.total, Decimal("-2000"))

    def test_credit_card_purchase_resolves_the_liability_as_home(self):
        entry = self.make_plain(account=self.visa, category=self.dining)
        self.assertEqual(resolve_sides(entry).account, self.visa)

    def test_opening_balance_resolves_the_asset_not_the_equity_account(self):
        entry = self.make_entry(lines=[(self.chequing, "5000", "0"), (self.opening, "0", "5000")])
        sides = resolve_sides(entry)

        self.assertEqual(sides.account, self.chequing)
        self.assertEqual([leg.account for leg in sides.legs], [self.opening])

    def test_split_resolves_the_one_line_side_as_home(self):
        entry = self.make_split()
        sides = resolve_sides(entry)

        self.assertEqual(sides.account, self.chequing)
        self.assertTrue(sides.is_split)
        self.assertEqual({leg.account for leg in sides.legs}, {self.groceries, self.household})

    def test_feed_row_wins_over_the_shape_rules(self):
        """A transfer's two legs share one entry; the primary's account is home."""
        entry = self.make_entry(lines=[(self.chequing, "0", "500"), (self.savings, "500", "0")])
        BankTransaction.objects.create(
            team=self.team,
            account=self.savings,
            amount=Decimal("-500"),
            posted_date=entry.entry_date,
            description=entry.description,
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )
        sides = resolve_sides(entry)

        self.assertEqual(sides.account, self.savings)
        self.assertEqual([leg.account for leg in sides.legs], [self.chequing])

    def test_transfer_without_a_feed_row_takes_the_credit_side(self):
        """Money leaving an account is how a user describes a transfer."""
        entry = self.make_entry(lines=[(self.chequing, "0", "500"), (self.savings, "500", "0")])
        self.assertEqual(resolve_sides(entry).account, self.chequing)

    def test_mirror_leg_is_not_mistaken_for_the_primary(self):
        entry = self.make_entry(lines=[(self.chequing, "0", "500"), (self.savings, "500", "0")])
        primary = BankTransaction.objects.create(
            team=self.team,
            account=self.chequing,
            amount=Decimal("500"),
            posted_date=entry.entry_date,
            description="Transfer",
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )
        mirror = BankTransaction.objects.create(
            team=self.team,
            account=self.savings,
            amount=Decimal("-500"),
            posted_date=entry.entry_date,
            description="Transfer",
            source=BankTransaction.SOURCE_SYSTEM,
            journal_entry=entry,
            is_transfer_mirror=True,
        )
        sides = resolve_sides(entry)

        self.assertEqual(sides.bank_tx, primary)
        self.assertEqual([m.id for m in sides.mirror_txs], [mirror.id])
        self.assertEqual(sides.account, self.chequing)

    def test_expense_to_expense_pair_is_flagged_abnormal_but_still_resolves(self):
        entry = self.make_entry(lines=[(self.groceries, "0", "25"), (self.dining, "25", "0")])
        sides = resolve_sides(entry)

        self.assertFalse(sides.normal)
        self.assertIsNotNone(sides.home_line)

    def test_zero_amount_entry_still_resolves_to_two_distinct_lines(self):
        entry = self.make_entry(lines=[(self.chequing, "0", "0"), (self.groceries, "0", "0")])
        sides = resolve_sides(entry)

        self.assertEqual(sides.account, self.chequing)
        self.assertEqual(len(sides.legs), 1)
        self.assertNotEqual(sides.home_line.id, sides.legs[0].id)

    def test_single_line_entry_is_refused(self):
        entry = self.make_entry(lines=[(self.chequing, "10", "0")])
        with self.assertRaises(UnsupportedEntry):
            resolve_sides(entry)

    def test_many_lines_on_both_sides_is_refused(self):
        entry = self.make_entry(
            lines=[
                (self.chequing, "0", "60"),
                (self.savings, "0", "40"),
                (self.groceries, "60", "0"),
                (self.dining, "40", "0"),
            ]
        )
        with self.assertRaises(UnsupportedEntry):
            resolve_sides(entry)


class ApplyEditsTest(TransactionEditTestCase):
    """Field-by-field edits on a plain transaction."""

    def edit(self, entry, **kwargs):
        return apply_edits(entry, TransactionEdits(**kwargs), team=self.team)

    def test_change_category(self):
        entry = self.make_plain()
        self.edit(entry, category_id=self.dining.id)

        self.assertEqual(self.legs_of(entry, self.chequing), {"Dining": Decimal("40.00")})
        self.assertBalanced(entry)

    def test_change_description_and_payee(self):
        entry = self.make_plain()
        self.edit(entry, description="Weekly shop", payee_name="Costco")
        entry.refresh_from_db()

        self.assertEqual(entry.description, "Weekly shop")
        self.assertEqual(entry.payee.name, "Costco")

    def test_blank_payee_clears_it(self):
        payee = Payee.objects.create(team=self.team, name="Costco")
        entry = self.make_plain(payee=payee)
        self.edit(entry, payee_name="")
        entry.refresh_from_db()

        self.assertIsNone(entry.payee)

    def test_payee_is_reused_not_duplicated(self):
        Payee.objects.create(team=self.team, name="Costco")
        entry = self.make_plain()
        self.edit(entry, payee_name="Costco")

        self.assertEqual(Payee.objects.filter(team=self.team, name="Costco").count(), 1)

    def test_change_amount_moves_both_sides(self):
        entry = self.make_plain(amount="40.00")
        self.edit(entry, outflow=Decimal("55.25"), inflow=Decimal("0"))

        sides = resolve_sides(entry)
        self.assertEqual(sides.outflow, Decimal("55.25"))
        self.assertEqual(self.legs_of(entry, self.chequing), {"Groceries": Decimal("55.25")})
        self.assertBalanced(entry)

    def test_flipping_outflow_to_inflow_swaps_the_sides(self):
        entry = self.make_plain(amount="40.00")
        self.edit(entry, outflow=Decimal("0"), inflow=Decimal("40.00"))

        sides = resolve_sides(entry)
        self.assertEqual(sides.inflow, Decimal("40.00"))
        self.assertEqual(sides.outflow, Decimal("0"))
        self.assertEqual(self.legs_of(entry, self.chequing), {"Groceries": Decimal("-40.00")})
        self.assertBalanced(entry)

    def test_change_account(self):
        entry = self.make_plain()
        self.edit(entry, account_id=self.visa.id)

        sides = resolve_sides(entry)
        self.assertEqual(sides.account, self.visa)
        self.assertEqual(self.legs_of(entry, self.visa), {"Groceries": Decimal("40.00")})
        self.assertBalanced(entry)

    def test_home_line_survives_every_edit(self):
        """
        Its pk and its reconciliation flags are user state; recreating the line
        would silently unreconcile a transaction confirmed against a statement.
        """
        entry = self.make_plain()
        home = resolve_sides(entry).home_line
        home.is_cleared = True
        home.save()

        self.edit(entry, description="Renamed", category_id=self.dining.id, outflow=Decimal("41.00"))

        after = resolve_sides(entry).home_line
        self.assertEqual(after.id, home.id)
        self.assertTrue(after.is_cleared)

    def test_date_change_relinks_the_budget(self):
        september = Budget.objects.create(
            team=self.team, category=self.groceries, month=date(2026, 9, 1), budget_amount=Decimal("500")
        )
        october = Budget.objects.create(
            team=self.team, category=self.groceries, month=date(2026, 10, 1), budget_amount=Decimal("500")
        )
        entry = self.make_plain(entry_date=date(2026, 9, 14))
        self.assertEqual(entry.lines.get(account=self.groceries).budget_id, september.id)

        self.edit(entry, date=date(2026, 10, 3))

        entry.refresh_from_db()
        self.assertEqual(entry.entry_date, date(2026, 10, 3))
        self.assertEqual(entry.lines.get(account=self.groceries).budget_id, october.id)

    def test_categorizing_to_the_account_itself_is_refused(self):
        entry = self.make_plain()
        with self.assertRaises(EditRefused):
            self.edit(entry, category_id=self.chequing.id)

    def test_both_inflow_and_outflow_is_refused(self):
        entry = self.make_plain()
        with self.assertRaises(EditRefused):
            self.edit(entry, inflow=Decimal("10"), outflow=Decimal("10"))

    def test_zero_amount_is_refused(self):
        entry = self.make_plain()
        with self.assertRaises(EditRefused):
            self.edit(entry, inflow=Decimal("0"), outflow=Decimal("0"))

    def test_another_teams_category_reads_as_missing(self):
        entry = self.make_plain()
        with self.assertRaises(EditRefused):
            self.edit(entry, category_id=self.foreign_account.id)
        self.assertEqual(self.legs_of(entry, self.chequing), {"Groceries": Decimal("40.00")})

    def test_unset_fields_are_left_alone(self):
        payee = Payee.objects.create(team=self.team, name="Costco")
        entry = self.make_plain(payee=payee, description="Original")
        self.edit(entry, category_id=self.dining.id)
        entry.refresh_from_db()

        self.assertEqual(entry.description, "Original")
        self.assertEqual(entry.payee, payee)
        self.assertEqual(entry.entry_date, date(2026, 9, 14))
        self.assertIs(TransactionEdits().date, UNSET)


class SplitEditTest(TransactionEditTestCase):
    """Editing a transaction apportioned across several categories."""

    def edit(self, entry, **kwargs):
        return apply_edits(entry, TransactionEdits(**kwargs), team=self.team)

    def test_reapportion_a_split(self):
        entry = self.make_split()
        self.edit(entry, legs=[(self.groceries, Decimal("120.00")), (self.household, Decimal("90.40"))])

        self.assertEqual(
            self.legs_of(entry, self.chequing),
            {"Groceries": Decimal("120.00"), "Household Goods": Decimal("90.40")},
        )
        self.assertBalanced(entry)

    def test_add_a_leg(self):
        entry = self.make_split()
        self.edit(
            entry,
            legs=[
                (self.groceries, Decimal("100.00")),
                (self.household, Decimal("50.40")),
                (self.dining, Decimal("60.00")),
            ],
        )

        self.assertEqual(len(self.legs_of(entry, self.chequing)), 3)
        self.assertBalanced(entry)

    def test_legs_must_add_up_to_the_total(self):
        entry = self.make_split()
        with self.assertRaises(EditRefused):
            self.edit(entry, legs=[(self.groceries, Decimal("1.00")), (self.household, Decimal("2.00"))])
        self.assertEqual(len(self.legs_of(entry, self.chequing)), 2)

    def test_a_split_needs_two_legs(self):
        entry = self.make_split()
        with self.assertRaises(EditRefused):
            self.edit(entry, legs=[(self.groceries, Decimal("210.40"))])

    def test_splitting_a_plain_transaction(self):
        entry = self.make_plain(amount="100.00")
        self.edit(entry, legs=[(self.groceries, Decimal("60.00")), (self.dining, Decimal("40.00"))])

        self.assertTrue(resolve_sides(entry).is_split)
        self.assertBalanced(entry)

    def test_a_single_category_on_a_split_is_refused_without_remove_split(self):
        """Folding a split into one category would destroy the apportionment."""
        entry = self.make_split()
        with self.assertRaises(EditRefused):
            self.edit(entry, category_id=self.dining.id)
        self.assertEqual(len(self.legs_of(entry, self.chequing)), 2)

    def test_remove_split_collapses_onto_the_named_category(self):
        entry = self.make_split()
        self.edit(entry, category_id=self.dining.id, remove_split=True)

        self.assertEqual(self.legs_of(entry, self.chequing), {"Dining": Decimal("210.40")})
        self.assertFalse(resolve_sides(entry).is_split)
        self.assertBalanced(entry)

    def test_remove_split_without_a_category_collapses_onto_the_largest_leg(self):
        entry = self.make_split()
        self.edit(entry, remove_split=True)

        self.assertEqual(self.legs_of(entry, self.chequing), {"Groceries": Decimal("210.40")})

    def test_changing_a_splits_total_alone_is_refused(self):
        """There is no honest way to guess how the user wants the change shared."""
        entry = self.make_split()
        with self.assertRaises(EditRefused):
            self.edit(entry, outflow=Decimal("300.00"), inflow=Decimal("0"))

    def test_a_splits_total_may_change_alongside_its_legs(self):
        entry = self.make_split()
        self.edit(
            entry,
            outflow=Decimal("300.00"),
            inflow=Decimal("0"),
            legs=[(self.groceries, Decimal("200.00")), (self.household, Decimal("100.00"))],
        )

        self.assertEqual(resolve_sides(entry).total, Decimal("300.00"))
        self.assertBalanced(entry)

    def test_a_refund_leg_inside_an_outflow(self):
        entry = self.make_plain(amount="80.00")
        self.edit(entry, legs=[(self.groceries, Decimal("100.00")), (self.household, Decimal("-20.00"))])

        self.assertEqual(
            self.legs_of(entry, self.chequing),
            {"Groceries": Decimal("100.00"), "Household Goods": Decimal("-20.00")},
        )
        self.assertBalanced(entry)

    def test_editing_a_split_does_not_grow_a_mirror_leg(self):
        entry = self.make_split()
        BankTransaction.objects.create(
            team=self.team,
            account=self.chequing,
            amount=Decimal("210.40"),
            posted_date=entry.entry_date,
            description="Costco",
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )
        # A leg on another feed account is the shape that used to spawn a mirror.
        self.edit(entry, legs=[(self.groceries, Decimal("160.00")), (self.savings, Decimal("50.40"))])

        self.assertEqual(BankTransaction.objects.filter(journal_entry=entry).count(), 1)


class BankSyncTest(TransactionEditTestCase):
    """The feed row and the ledger must not drift apart."""

    def attach(self, entry, *, account, amount, source=BankTransaction.SOURCE_CSV):
        return BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal(amount),
            posted_date=entry.entry_date,
            description=entry.description,
            source=source,
            journal_entry=entry,
        )

    def test_edits_follow_through_to_the_feed_row(self):
        entry = self.make_plain(amount="40.00")
        tx = self.attach(entry, account=self.chequing, amount="40.00")

        apply_edits(
            entry,
            TransactionEdits(
                date=date(2026, 10, 1),
                description="Weekly shop",
                payee_name="Costco",
                outflow=Decimal("55.25"),
                inflow=Decimal("0"),
            ),
            team=self.team,
        )

        tx.refresh_from_db()
        self.assertEqual(tx.posted_date, date(2026, 10, 1))
        self.assertEqual(tx.description, "Weekly shop")
        self.assertEqual(tx.merchant_name, "Costco")
        self.assertEqual(tx.amount, Decimal("55.25"))

    def test_an_inflow_is_a_negative_feed_amount(self):
        entry = self.make_plain(amount="40.00")
        tx = self.attach(entry, account=self.chequing, amount="40.00")

        apply_edits(entry, TransactionEdits(inflow=Decimal("40.00"), outflow=Decimal("0")), team=self.team)

        tx.refresh_from_db()
        self.assertEqual(tx.amount, Decimal("-40.00"))

    def test_moving_the_account_moves_the_feed_row(self):
        entry = self.make_plain()
        tx = self.attach(entry, account=self.chequing, amount="40.00")

        apply_edits(entry, TransactionEdits(account_id=self.visa.id), team=self.team)

        tx.refresh_from_db()
        self.assertEqual(tx.account, self.visa)
        self.assertEqual(resolve_sides(entry).account, self.visa)

    def test_moving_to_an_account_with_no_feed_is_refused(self):
        entry = self.make_plain()
        self.attach(entry, account=self.chequing, amount="40.00")

        with self.assertRaises(EditRefused):
            apply_edits(entry, TransactionEdits(account_id=self.cash.id), team=self.team)

    def test_a_manual_entry_may_move_to_an_account_with_no_feed(self):
        entry = self.make_plain()
        apply_edits(entry, TransactionEdits(account_id=self.cash.id), team=self.team)

        self.assertEqual(resolve_sides(entry).account, self.cash)

    def test_categorizing_to_another_feed_account_creates_the_mirror_leg(self):
        entry = self.make_plain(category=self.groceries)
        self.attach(entry, account=self.chequing, amount="40.00")

        apply_edits(entry, TransactionEdits(category_id=self.savings.id), team=self.team)

        mirror = BankTransaction.objects.get(journal_entry=entry, is_transfer_mirror=True)
        self.assertEqual(mirror.account, self.savings)
        self.assertEqual(mirror.amount, Decimal("-40.00"))

    def test_the_mirror_leg_follows_a_date_change(self):
        entry = self.make_plain(category=self.savings)
        self.attach(entry, account=self.chequing, amount="40.00")
        apply_edits(entry, TransactionEdits(category_id=self.savings.id), team=self.team)

        apply_edits(entry, TransactionEdits(date=date(2026, 11, 2)), team=self.team)

        mirror = BankTransaction.objects.get(journal_entry=entry, is_transfer_mirror=True)
        self.assertEqual(mirror.posted_date, date(2026, 11, 2))

    def test_categorizing_away_from_a_transfer_removes_the_mirror_leg(self):
        entry = self.make_plain(category=self.savings)
        self.attach(entry, account=self.chequing, amount="40.00")
        apply_edits(entry, TransactionEdits(category_id=self.savings.id), team=self.team)

        apply_edits(entry, TransactionEdits(category_id=self.groceries.id), team=self.team)

        self.assertFalse(BankTransaction.objects.filter(journal_entry=entry, is_transfer_mirror=True).exists())


class GuardsTest(TransactionEditTestCase):
    """What the editor refuses, and what it deliberately allows."""

    def test_a_void_entry_cannot_be_edited(self):
        entry = self.make_plain(status=JournalEntry.STATUS_VOID)
        with self.assertRaises(EditRefused):
            apply_edits(entry, TransactionEdits(description="nope"), team=self.team)

    def test_a_reconciled_transactions_amount_is_locked(self):
        entry = self.make_plain(reconciled=True)
        with self.assertRaises(EditRefused):
            apply_edits(entry, TransactionEdits(outflow=Decimal("99"), inflow=Decimal("0")), team=self.team)

    def test_a_reconciled_transactions_account_is_locked(self):
        entry = self.make_plain(reconciled=True)
        with self.assertRaises(EditRefused):
            apply_edits(entry, TransactionEdits(account_id=self.visa.id), team=self.team)

    def test_a_reconciled_transaction_may_still_be_recategorized(self):
        """Reconciliation is a fact about the bank line, not about the category."""
        entry = self.make_plain(reconciled=True)
        apply_edits(entry, TransactionEdits(category_id=self.dining.id), team=self.team)

        self.assertEqual(self.legs_of(entry, self.chequing), {"Dining": Decimal("40.00")})
        self.assertTrue(resolve_sides(entry).home_line.is_reconciled)

    def test_a_reconciled_split_may_still_be_reapportioned(self):
        entry = self.make_split(reconciled=True)
        apply_edits(
            entry,
            TransactionEdits(legs=[(self.groceries, Decimal("100.00")), (self.household, Decimal("110.40"))]),
            team=self.team,
        )

        self.assertEqual(self.legs_of(entry, self.chequing)["Groceries"], Decimal("100.00"))
        self.assertTrue(resolve_sides(entry).home_line.is_reconciled)

    def test_plaid_sets_the_date(self):
        entry = self.make_plain()
        BankTransaction.objects.create(
            team=self.team,
            account=self.chequing,
            amount=Decimal("40.00"),
            posted_date=entry.entry_date,
            description=entry.description,
            source=BankTransaction.SOURCE_PLAID,
            journal_entry=entry,
        )
        with self.assertRaises(EditRefused):
            apply_edits(entry, TransactionEdits(date=date(2026, 10, 1)), team=self.team)

    def test_plaid_sets_the_amount(self):
        entry = self.make_plain()
        BankTransaction.objects.create(
            team=self.team,
            account=self.chequing,
            amount=Decimal("40.00"),
            posted_date=entry.entry_date,
            description=entry.description,
            source=BankTransaction.SOURCE_PLAID,
            journal_entry=entry,
        )
        with self.assertRaises(EditRefused):
            apply_edits(entry, TransactionEdits(outflow=Decimal("99"), inflow=Decimal("0")), team=self.team)

    def test_a_plaid_rows_category_is_still_editable(self):
        entry = self.make_plain()
        BankTransaction.objects.create(
            team=self.team,
            account=self.chequing,
            amount=Decimal("40.00"),
            posted_date=entry.entry_date,
            description=entry.description,
            source=BankTransaction.SOURCE_PLAID,
            journal_entry=entry,
        )
        apply_edits(entry, TransactionEdits(category_id=self.dining.id, payee_name="Costco"), team=self.team)

        self.assertEqual(self.legs_of(entry, self.chequing), {"Dining": Decimal("40.00")})


class BatchTest(TransactionEditTestCase):
    """The same edits object applied to many entries, all or none."""

    def test_the_same_edit_lands_on_every_entry(self):
        entries = [self.make_plain(description=f"Row {n}") for n in range(3)]
        apply_edits_bulk(entries, TransactionEdits(category_id=self.dining.id), team=self.team)

        for entry in entries:
            self.assertEqual(self.legs_of(entry, self.chequing), {"Dining": Decimal("40.00")})

    def test_one_bad_row_writes_nothing(self):
        good = self.make_plain(description="Fine")
        bad = self.make_plain(description="Void", status=JournalEntry.STATUS_VOID)

        with self.assertRaises(EditRefused):
            apply_edits_bulk([good, bad], TransactionEdits(category_id=self.dining.id), team=self.team)

        self.assertEqual(self.legs_of(good, self.chequing), {"Groceries": Decimal("40.00")})

    def test_a_refusal_on_the_second_row_rolls_back_the_first(self):
        """
        The pre-scan catches most refusals, but not every one: legs are checked
        against each entry's own total, which the scan does not know. The atomic
        block is what stops a batch being half-applied.
        """
        first = self.make_plain(amount="100.00", description="First")
        second = self.make_plain(amount="250.00", description="Second")
        legs = [(self.groceries, Decimal("60.00")), (self.dining, Decimal("40.00"))]

        with self.assertRaises(EditRefused):
            apply_edits_bulk([first, second], TransactionEdits(legs=legs), team=self.team)

        self.assertEqual(self.legs_of(first, self.chequing), {"Groceries": Decimal("100.00")})
        self.assertEqual(self.legs_of(second, self.chequing), {"Groceries": Decimal("250.00")})


class DeleteAndStatusTest(TransactionEditTestCase):
    def test_a_manual_transaction_is_deleted_outright(self):
        entry = self.make_plain()
        delete_transaction(entry, team=self.team)

        self.assertFalse(JournalEntry.objects.filter(id=entry.id).exists())

    def test_a_bank_backed_transaction_returns_to_the_feed_uncategorized(self):
        entry = self.make_plain()
        tx = BankTransaction.objects.create(
            team=self.team,
            account=self.chequing,
            amount=Decimal("40.00"),
            posted_date=entry.entry_date,
            description=entry.description,
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )
        delete_transaction(entry, team=self.team)

        tx.refresh_from_db()
        self.assertIsNone(tx.journal_entry_id)
        self.assertFalse(JournalEntry.objects.filter(id=entry.id).exists())

    def test_deleting_a_transfer_takes_its_mirror_leg_with_it(self):
        entry = self.make_plain(category=self.savings)
        BankTransaction.objects.create(
            team=self.team,
            account=self.chequing,
            amount=Decimal("40.00"),
            posted_date=entry.entry_date,
            description=entry.description,
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )
        apply_edits(entry, TransactionEdits(category_id=self.savings.id), team=self.team)
        self.assertTrue(BankTransaction.objects.filter(journal_entry=entry, is_transfer_mirror=True).exists())

        delete_transaction(entry, team=self.team)

        self.assertFalse(BankTransaction.objects.filter(is_transfer_mirror=True).exists())

    def test_a_reconciled_transaction_cannot_be_deleted(self):
        entry = self.make_plain(reconciled=True)
        with self.assertRaises(EditRefused):
            delete_transaction(entry, team=self.team)
        self.assertTrue(JournalEntry.objects.filter(id=entry.id).exists())

    def test_void_and_restore(self):
        entry = self.make_plain()
        set_status(entry, JournalEntry.STATUS_VOID, team=self.team)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.STATUS_VOID)

        set_status(entry, JournalEntry.STATUS_POSTED, team=self.team)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.STATUS_POSTED)

    def test_only_void_and_posted_are_reachable(self):
        entry = self.make_plain()
        with self.assertRaises(EditRefused):
            set_status(entry, JournalEntry.STATUS_DRAFT, team=self.team)


class AuditTest(TransactionEditTestCase):
    """The history tab has to show a field diff, not a delete and a create."""

    def test_editing_the_home_line_produces_an_update_not_a_recreate(self):
        entry = self.make_plain()
        AuditLog.objects.filter(journal_entry_id=entry.id).delete()

        apply_edits(entry, TransactionEdits(outflow=Decimal("55.25"), inflow=Decimal("0")), team=self.team)

        updates = AuditLog.objects.filter(
            journal_entry_id=entry.id, source_model="JournalLine", action=AuditLog.ACTION_UPDATE
        )
        self.assertTrue(updates.exists(), "the home line's amount change should read as an update")
        self.assertIn("cr_amount", updates.first().changes)

    def test_a_description_change_is_recorded_against_the_entry(self):
        entry = self.make_plain()
        AuditLog.objects.filter(journal_entry_id=entry.id).delete()

        apply_edits(entry, TransactionEdits(description="Weekly shop"), team=self.team)

        log = AuditLog.objects.filter(
            journal_entry_id=entry.id, source_model="JournalEntry", action=AuditLog.ACTION_UPDATE
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["description"]["after"], "Weekly shop")


class TransactionEditApiTest(TransactionEditTestCase):
    """The endpoints the modal talks to."""

    def url(self, suffix=""):
        return f"/a/{self.team.slug}/journal/api/transactions/{suffix}"

    # --- retrieve --------------------------------------------------------

    def test_detail_reads_as_account_and_category(self):
        entry = self.make_plain(payee=Payee.objects.create(team=self.team, name="Costco"))
        response = self.client.get(self.url(f"{entry.id}/"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["account"]["name"], "Chequing")
        self.assertEqual(body["category"]["name"], "Groceries")
        self.assertEqual(body["outflow"], "40.00")
        self.assertEqual(body["inflow"], "0.00")
        self.assertEqual(body["payee_name"], "Costco")
        self.assertFalse(body["is_split"])
        self.assertEqual(body["splits"], [])

    def test_detail_of_a_split_carries_its_legs(self):
        entry = self.make_split()
        body = self.client.get(self.url(f"{entry.id}/")).json()

        self.assertTrue(body["is_split"])
        self.assertIsNone(body["category"])
        # Numbers, not strings -- the same shape `SplitLegSerializer` emits on the
        # Bank Feed, because `SplitEditor` reads both and must not have to guess.
        self.assertEqual(
            {leg["category_name"]: leg["amount"] for leg in body["splits"]},
            {"Groceries": 160.0, "Household Goods": 50.4},
        )

    def test_capabilities_match_what_the_writer_would_accept(self):
        entry = self.make_plain(reconciled=True)
        BankTransaction.objects.create(
            team=self.team,
            account=self.chequing,
            amount=Decimal("40.00"),
            posted_date=entry.entry_date,
            description=entry.description,
            source=BankTransaction.SOURCE_PLAID,
            journal_entry=entry,
        )
        caps = self.client.get(self.url(f"{entry.id}/")).json()["capabilities"]

        self.assertFalse(caps["can_edit_date"])
        self.assertFalse(caps["can_edit_amount"])
        self.assertFalse(caps["can_edit_account"])
        self.assertFalse(caps["can_delete"])
        self.assertTrue(caps["can_edit_category"])
        self.assertTrue(caps["can_void"])
        self.assertFalse(caps["can_unvoid"])

    def test_another_teams_transaction_is_not_found(self):
        entry = self.make_plain()
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(f"/a/{self.other_team.slug}/journal/api/transactions/{entry.id}/")

        self.assertEqual(response.status_code, 404)

    def test_an_unreadable_shape_is_refused_rather_than_crashing(self):
        entry = self.make_entry(
            lines=[
                (self.chequing, "0", "60"),
                (self.savings, "0", "40"),
                (self.groceries, "60", "0"),
                (self.dining, "40", "0"),
            ]
        )
        response = self.client.get(self.url(f"{entry.id}/"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    # --- edit ------------------------------------------------------------

    def test_edit_returns_the_updated_row(self):
        entry = self.make_plain()
        response = self.client.patch(
            self.url("edit/"),
            {"ids": [entry.id], "category_id": self.dining.id, "payee": "Costco"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["id"], entry.id)
        self.assertEqual(row["payee_name"], "Costco")
        self.assertEqual(row["debit_account"], "Dining")

    def test_edit_leaves_omitted_fields_alone(self):
        entry = self.make_plain(description="Original")
        self.client.patch(self.url("edit/"), {"ids": [entry.id], "category_id": self.dining.id}, format="json")

        entry.refresh_from_db()
        self.assertEqual(entry.description, "Original")
        self.assertEqual(entry.entry_date, date(2026, 9, 14))

    def test_edit_accepts_split_legs(self):
        entry = self.make_plain(amount="100.00")
        response = self.client.patch(
            self.url("edit/"),
            {
                "ids": [entry.id],
                "splits": [
                    {"category": self.groceries.id, "amount": "60.00"},
                    {"category": self.dining.id, "amount": "40.00"},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["results"][0]["is_split"])

    def test_edit_rejects_a_category_and_splits_together(self):
        entry = self.make_plain()
        response = self.client.patch(
            self.url("edit/"),
            {
                "ids": [entry.id],
                "category_id": self.dining.id,
                "splits": [
                    {"category": self.groceries.id, "amount": "20.00"},
                    {"category": self.dining.id, "amount": "20.00"},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_refusal_is_a_400_with_a_readable_reason(self):
        entry = self.make_plain(reconciled=True)
        response = self.client.patch(self.url("edit/"), {"ids": [entry.id], "outflow": "99.00"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unreconcile", response.json()["error"])

    def test_an_unknown_id_refuses_the_whole_batch(self):
        entry = self.make_plain()
        response = self.client.patch(
            self.url("edit/"), {"ids": [entry.id, 999999], "category_id": self.dining.id}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.legs_of(entry, self.chequing), {"Groceries": Decimal("40.00")})

    def test_another_teams_id_is_refused_not_edited(self):
        mine = self.make_plain()
        theirs = JournalEntry.objects.create(
            team=self.other_team,
            entry_date=date(2026, 9, 14),
            description="Theirs",
            status=JournalEntry.STATUS_POSTED,
        )
        response = self.client.patch(
            self.url("edit/"), {"ids": [mine.id, theirs.id], "description": "mine now"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        theirs.refresh_from_db()
        self.assertEqual(theirs.description, "Theirs")

    def test_a_batch_edit_is_recorded_as_one_event(self):
        entries = [self.make_plain(description=f"Row {n}") for n in range(2)]
        self.client.patch(
            self.url("edit/"),
            {"ids": [e.id for e in entries], "category_id": self.dining.id},
            format="json",
        )

        event = AuditEvent.objects.filter(event_type=AuditEvent.BULK_EDIT).last()
        self.assertIsNotNone(event)
        self.assertEqual(event.metadata["scope"], "transactions")
        self.assertEqual(event.metadata["count"], 2)
        self.assertEqual(event.metadata["fields"], ["category_id"])

    def test_a_single_edit_is_not_recorded_as_a_bulk_event(self):
        entry = self.make_plain()
        self.client.patch(self.url("edit/"), {"ids": [entry.id], "description": "x"}, format="json")

        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEvent.BULK_EDIT).exists())

    # --- delete and status -----------------------------------------------

    def test_batch_delete(self):
        entry = self.make_plain()
        response = self.client.post(self.url("batch_delete/"), {"ids": [entry.id]}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted"], [entry.id])
        self.assertFalse(JournalEntry.objects.filter(id=entry.id).exists())

    def test_deleting_a_bank_backed_row_leaves_it_in_the_feed(self):
        entry = self.make_plain()
        tx = BankTransaction.objects.create(
            team=self.team,
            account=self.chequing,
            amount=Decimal("40.00"),
            posted_date=entry.entry_date,
            description=entry.description,
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )
        self.client.post(self.url("batch_delete/"), {"ids": [entry.id]}, format="json")

        tx.refresh_from_db()
        self.assertIsNone(tx.journal_entry_id)

    def test_delete_refuses_a_reconciled_row_and_writes_nothing(self):
        plain = self.make_plain(description="Plain")
        locked = self.make_plain(description="Locked", reconciled=True)
        response = self.client.post(self.url("batch_delete/"), {"ids": [plain.id, locked.id]}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertTrue(JournalEntry.objects.filter(id=plain.id).exists())

    def test_void_and_unvoid_round_trip(self):
        entry = self.make_plain()
        voided = self.client.post(self.url("batch_status/"), {"ids": [entry.id], "status": "void"}, format="json")
        self.assertEqual(voided.json()["results"][0]["status"], "void")

        restored = self.client.post(self.url("batch_status/"), {"ids": [entry.id], "status": "posted"}, format="json")
        self.assertEqual(restored.json()["results"][0]["status"], "posted")

    def test_status_only_accepts_void_and_posted(self):
        entry = self.make_plain()
        response = self.client.post(self.url("batch_status/"), {"ids": [entry.id], "status": "draft"}, format="json")

        self.assertEqual(response.status_code, 400)

    # --- access ----------------------------------------------------------

    def test_a_non_member_cannot_edit(self):
        entry = self.make_plain()
        self.client.force_authenticate(user=self.outsider)
        response = self.client.patch(self.url("edit/"), {"ids": [entry.id], "description": "theirs now"}, format="json")

        self.assertIn(response.status_code, (403, 404))
        entry.refresh_from_db()
        self.assertEqual(entry.description, "Costco")

    def test_an_anonymous_request_cannot_edit(self):
        entry = self.make_plain()
        self.client.force_authenticate(user=None)
        response = self.client.patch(self.url("edit/"), {"ids": [entry.id], "description": "nope"}, format="json")

        self.assertIn(response.status_code, (401, 403, 404))
