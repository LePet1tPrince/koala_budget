"""
Tests for split transactions -- one bank transaction apportioned across several
categories.

A split is one JournalEntry: a single line on the bank account carrying the
total, and one counter line per leg. That shape already exists in user data
(`apps.ynab_import` builds it), so the first tests here are written against the
bugs that shape hits in code assuming two lines -- see docs/split-transactions-plan.md
section 4.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.transfer_mirror import sync_transfer
from apps.books.context import current_book
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class SplitTestCase(TestCase):
    """Shared fixtures and helpers for every split test."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Split Team", slug="split-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="splituser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.other_team = Team.objects.create(name="Other Team", slug="other-team")
        cls.other_book = cls.other_team.default_book

        cls.asset_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.liability_group = AccountGroup.objects.create(
            book=cls.book, name="Credit Cards", account_type=ACCOUNT_TYPE_LIABILITY
        )
        cls.expense_group = AccountGroup.objects.create(
            book=cls.book, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.income_group = AccountGroup.objects.create(book=cls.book, name="Income", account_type=ACCOUNT_TYPE_INCOME)

        cls.chequing = Account.objects.create(
            book=cls.book, name="Chequing", account_group=cls.asset_group, has_feed=True
        )
        cls.savings = Account.objects.create(
            book=cls.book, name="Savings", account_group=cls.asset_group, has_feed=True
        )
        cls.groceries = Account.objects.create(
            book=cls.book, name="Groceries", account_group=cls.expense_group, has_feed=False
        )
        cls.household = Account.objects.create(
            book=cls.book, name="Household Goods", account_group=cls.expense_group, has_feed=False
        )
        cls.shopping = Account.objects.create(
            book=cls.book, name="Shopping", account_group=cls.expense_group, has_feed=False
        )
        cls.salary = Account.objects.create(
            book=cls.book, name="Salary", account_group=cls.income_group, has_feed=False
        )

        # An account belonging to somebody else, for the team-scoping test.
        other_group = AccountGroup.objects.create(
            book=cls.other_book, name="Their Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.foreign_account = Account.objects.create(
            book=cls.other_book, name="Their Groceries", account_group=other_group, has_feed=False
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # --- helpers ---------------------------------------------------------

    def make_split(self, *, account=None, legs=None, total=None, reconciled=False, description="Costco"):
        """
        Build a split the way `apps.ynab_import` does: one bank line carrying the
        total, one counter line per leg.

        `legs` is [(category_account, signed_amount)] in the feed's convention --
        positive is an outflow -- and `total` defaults to their sum.
        """
        account = account or self.chequing
        legs = legs or [(self.groceries, Decimal("160.00")), (self.household, Decimal("50.40"))]
        total = sum(amount for _, amount in legs) if total is None else total

        entry = JournalEntry.objects.create(
            book=self.book,
            entry_date=date(2026, 9, 14),
            description=description,
            source=JournalEntry.SOURCE_BANK_MATCH,
            status=JournalEntry.STATUS_POSTED,
        )
        # The bank line takes the opposite side of the total.
        JournalLine.objects.create(
            journal_entry=entry,
            book=self.book,
            account=account,
            dr_amount=-total if total < 0 else Decimal("0"),
            cr_amount=total if total > 0 else Decimal("0"),
            is_reconciled=reconciled,
        )
        # Each leg takes the same side as its own sign.
        for category, amount in legs:
            JournalLine.objects.create(
                journal_entry=entry,
                book=self.book,
                account=category,
                dr_amount=amount if amount > 0 else Decimal("0"),
                cr_amount=-amount if amount < 0 else Decimal("0"),
            )

        tx = BankTransaction.objects.create(
            book=self.book,
            account=account,
            amount=total,
            posted_date=date(2026, 9, 14),
            description=description,
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )
        return tx

    def make_plain(self, *, account=None, amount="40.00", category=None, description="Coffee"):
        """An ordinary two-line categorized transaction."""
        account = account or self.chequing
        category = category or self.groceries
        amount = Decimal(amount)
        entry = JournalEntry.objects.create(
            book=self.book,
            entry_date=date(2026, 9, 14),
            description=description,
            source=JournalEntry.SOURCE_BANK_MATCH,
            status=JournalEntry.STATUS_POSTED,
        )
        JournalLine.objects.create(
            journal_entry=entry, book=self.book, account=account, dr_amount=Decimal("0"), cr_amount=amount
        )
        JournalLine.objects.create(
            journal_entry=entry, book=self.book, account=category, dr_amount=amount, cr_amount=Decimal("0")
        )
        return BankTransaction.objects.create(
            book=self.book,
            account=account,
            amount=amount,
            posted_date=date(2026, 9, 14),
            description=description,
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )

    def assertBalanced(self, entry, msg=""):
        entry.refresh_from_db()
        self.assertEqual(
            entry.total_debits,
            entry.total_credits,
            f"Journal entry {entry.id} does not balance: "
            f"debits {entry.total_debits} != credits {entry.total_credits}. {msg}",
        )

    def feed_url(self, suffix=""):
        return f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/{suffix}"


class SplitRegressionTest(SplitTestCase):
    """
    The five ways splits break today (plan section 4).

    These are written before the fix and are expected to fail; each one names the
    location of the bug it covers.
    """

    def test_saving_a_split_unchanged_keeps_it_balanced(self):
        """
        T1 -- `update()` sets every non-bank line to the same account and the full
        amount, so re-saving a split leaves debits at double the credits.
        """
        tx = self.make_split()
        entry = tx.journal_entry

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "inflow": "0",
                    "outflow": "210.40",
                    "description": "Costco",
                    "payee": "",
                    "splits": [
                        {"category": self.groceries.id, "amount": "160.00"},
                        {"category": self.household.id, "amount": "50.40"},
                    ],
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertBalanced(entry, "Re-saving a split must not change what it books.")
        self.assertEqual(entry.lines.count(), 3)

    def test_saving_a_split_with_a_single_category_is_refused(self):
        """
        T1b -- the actual reproduction of the corruption.

        Today the modal shows a split's *last* leg as though it were the whole
        transaction's category (T2's bug), so saving sends one `category` and the
        full amount. The old `update()` then set every leg to that account and that
        amount: two legs of $210.40 against a bank line of $210.40, i.e. debits at
        double the credits, with nothing to catch it -- `JournalEntry.clean()` is
        never called on this path.

        The fix refuses the request rather than guessing which apportionment the
        user meant.
        """
        tx = self.make_split()
        entry = tx.journal_entry

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "category": self.household.id,
                    "inflow": "0",
                    "outflow": "210.40",
                    "description": "Costco",
                    "payee": "",
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("split", str(resp.data).lower())
        self.assertBalanced(entry)
        self.assertEqual(entry.lines.count(), 3)
        self.assertEqual(
            sorted(str(line.dr_amount) for line in entry.lines.all()),
            ["0.00", "160.00", "50.40"],
            "The apportionment must be exactly as it was.",
        )

    def test_feed_row_reports_a_split_as_split(self):
        """
        T2 -- `bank_transaction_to_feed_row` has no `break`, so a split reports
        whichever leg sorts last as its one category.
        """
        tx = self.make_split()
        with current_book(self.book):
            resp = self.client.get(self.feed_url(f"?account={self.chequing.id}"))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        row = next(r for r in resp.data["results"] if r["imported_transaction_id"] == tx.id)
        self.assertTrue(row["is_split"])
        self.assertEqual(row["split_count"], 2)
        self.assertIsNone(row["category"], "A split has no single category to report.")
        self.assertEqual(
            sorted((leg["category_name"], str(leg["amount"])) for leg in row["splits"]),
            [("Groceries", "160.00"), ("Household Goods", "50.40")],
        )

    def test_bulk_categorize_refuses_a_split(self):
        """
        T3 -- `_update_journal_category` breaks after the first leg, silently
        re-pointing one leg of the split and leaving the rest.
        """
        tx = self.make_split()
        entry = tx.journal_entry

        with current_book(self.book):
            resp = self.client.post(
                self.feed_url("categorize/"),
                {"rows": [{"id": tx.id}], "category_id": self.shopping.id},
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("split", str(resp.data).lower())
        self.assertBalanced(entry)
        self.assertEqual(entry.lines.count(), 3, "The split must be left exactly as it was.")
        self.assertFalse(entry.lines.filter(account=self.shopping).exists())

    def test_batch_edit_refuses_a_split_all_or_nothing(self):
        """
        T4 -- a split caught in a select-all must not be half-edited, and must not
        take the rest of the batch down with it.
        """
        split = self.make_split()
        plain = self.make_plain()

        with current_book(self.book):
            resp = self.client.patch(
                self.feed_url("batch_edit/"),
                {"ids": [split.id, plain.id], "category_id": self.shopping.id},
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("split", str(resp.data).lower())
        # All-or-nothing: the plain transaction in the same batch is untouched.
        plain.refresh_from_db()
        self.assertFalse(plain.journal_entry.lines.filter(account=self.shopping).exists())
        self.assertBalanced(split.journal_entry)

    def test_split_mirrors_only_its_transfer_leg(self):
        """
        T5 -- a split whose first leg is a feed account once grew a mirror for the
        split's *whole* amount. A transfer leg is mirrored for its own amount only.
        """
        tx = self.make_split(
            legs=[(self.savings, Decimal("100.00")), (self.groceries, Decimal("60.00"))],
        )
        sync_transfer(tx)

        mirrors = BankTransaction.objects.filter(journal_entry=tx.journal_entry).exclude(id=tx.id)
        self.assertEqual(
            [(m.account_id, m.amount) for m in mirrors],
            [(self.savings.id, Decimal("-100.00"))],
            "The mirror carries the transfer leg, never the split's total.",
        )

    def test_split_survives_a_payee_only_edit(self):
        """
        T5b -- `sync_transfer` runs after every edit, so the mirror is reachable
        from an edit that never mentions a category: it follows the leg, once.
        """
        tx = self.make_split(
            legs=[(self.savings, Decimal("100.00")), (self.groceries, Decimal("60.00"))],
        )

        with current_book(self.book):
            resp = self.client.patch(
                self.feed_url("batch_edit/"),
                {"ids": [tx.id], "payee": "Costco Wholesale"},
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT, resp.data)
        self.assertBalanced(tx.journal_entry)
        mirrors = BankTransaction.objects.filter(journal_entry=tx.journal_entry).exclude(id=tx.id)
        self.assertEqual([(m.account_id, m.amount) for m in mirrors], [(self.savings.id, Decimal("-100.00"))])
        self.assertEqual(mirrors.get().merchant_name, "Costco Wholesale")


class SplitArithmeticTest(SplitTestCase):
    """
    The four worked examples from the plan, each checked line by line.

    A leg takes the same side as its own sign; the bank line takes the opposite
    side of the total. These cover both directions and both mixed-sign cases,
    which is where a sign convention usually breaks.
    """

    def lines_of(self, tx):
        """{account name: (dr, cr)} for the transaction's entry."""
        tx.refresh_from_db()
        return {line.account.name: (str(line.dr_amount), str(line.cr_amount)) for line in tx.journal_entry.lines.all()}

    def create_split(self, *, inflow, outflow, legs):
        with current_book(self.book):
            return self.client.post(
                self.feed_url(),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "inflow": inflow,
                    "outflow": outflow,
                    "description": "Test",
                    "payee": "",
                    "splits": [{"category": account.id, "amount": amount} for account, amount in legs],
                },
                format="json",
            )

    def test_example_a_plain_outflow_split(self):
        """$210.40 out, groceries $160.00 + household $50.40."""
        resp = self.create_split(
            inflow="0",
            outflow="210.40",
            legs=[(self.groceries, "160.00"), (self.household, "50.40")],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        tx = BankTransaction.objects.get(id=resp.data["imported_transaction_id"])
        self.assertEqual(
            self.lines_of(tx),
            {
                "Chequing": ("0.00", "210.40"),
                "Groceries": ("160.00", "0.00"),
                "Household Goods": ("50.40", "0.00"),
            },
        )
        self.assertBalanced(tx.journal_entry)

    def test_example_b_outflow_with_a_refund_leg(self):
        """Net $80.00 out: a $100.00 purchase and a $20.00 credit."""
        resp = self.create_split(
            inflow="0",
            outflow="80.00",
            legs=[(self.shopping, "100.00"), (self.household, "-20.00")],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        tx = BankTransaction.objects.get(id=resp.data["imported_transaction_id"])
        self.assertEqual(
            self.lines_of(tx),
            {
                "Chequing": ("0.00", "80.00"),
                "Shopping": ("100.00", "0.00"),
                "Household Goods": ("0.00", "20.00"),
            },
        )
        self.assertBalanced(tx.journal_entry)

    def test_example_c_inflow_split(self):
        """$2,000.00 in, split $1,800.00 salary + $200.00 other income."""
        resp = self.create_split(
            inflow="2000.00",
            outflow="0",
            legs=[(self.salary, "-1800.00"), (self.groceries, "-200.00")],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        tx = BankTransaction.objects.get(id=resp.data["imported_transaction_id"])
        self.assertEqual(
            self.lines_of(tx),
            {
                "Chequing": ("2000.00", "0.00"),
                "Salary": ("0.00", "1800.00"),
                "Groceries": ("0.00", "200.00"),
            },
        )
        self.assertBalanced(tx.journal_entry)

    def test_example_d_gross_paycheque_with_deductions(self):
        """$3,000.00 net in; gross $4,000.00 less $800.00 tax less $200.00 pension."""
        resp = self.create_split(
            inflow="3000.00",
            outflow="0",
            legs=[(self.salary, "-4000.00"), (self.groceries, "800.00"), (self.household, "200.00")],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        tx = BankTransaction.objects.get(id=resp.data["imported_transaction_id"])
        self.assertEqual(
            self.lines_of(tx),
            {
                "Chequing": ("3000.00", "0.00"),
                "Salary": ("0.00", "4000.00"),
                "Groceries": ("800.00", "0.00"),
                "Household Goods": ("200.00", "0.00"),
            },
        )
        self.assertBalanced(tx.journal_entry)


class SplitValidationTest(SplitTestCase):
    """Every rule in the plan's validation table, at the endpoint."""

    def put_splits(self, tx, splits, *, outflow="210.40", inflow="0"):
        with current_book(self.book):
            return self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "inflow": inflow,
                    "outflow": outflow,
                    "description": "Costco",
                    "payee": "",
                    "splits": splits,
                },
                format="json",
            )

    def test_legs_must_add_up_to_the_total(self):
        tx = self.make_split()
        resp = self.put_splits(
            tx,
            [
                {"category": self.groceries.id, "amount": "160.00"},
                {"category": self.household.id, "amount": "10.00"},  # 40.40 short
            ],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("add up", str(resp.data))
        self.assertBalanced(tx.journal_entry)
        # Nothing was written: the original apportionment stands.
        self.assertTrue(tx.journal_entry.lines.filter(account=self.household, dr_amount=Decimal("50.40")).exists())

    def test_a_single_leg_is_refused(self):
        tx = self.make_split()
        resp = self.put_splits(tx, [{"category": self.groceries.id, "amount": "210.40"}])
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("at least", str(resp.data))

    def test_too_many_legs_are_refused(self):
        tx = self.make_split()
        legs = [{"category": self.groceries.id, "amount": "10.00"} for _ in range(21)]
        resp = self.put_splits(tx, legs, outflow="210.00")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("more than 20", str(resp.data))

    def test_zero_amount_leg_is_refused(self):
        tx = self.make_split()
        resp = self.put_splits(
            tx,
            [
                {"category": self.groceries.id, "amount": "210.40"},
                {"category": self.household.id, "amount": "0"},
            ],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cannot be zero", str(resp.data))

    def test_unparseable_amount_is_refused(self):
        tx = self.make_split()
        resp = self.put_splits(
            tx,
            [
                {"category": self.groceries.id, "amount": "one hundred"},
                {"category": self.household.id, "amount": "50.40"},
            ],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not a number", str(resp.data))

    def test_another_teams_account_is_not_found(self):
        """
        Team scoping: a leg naming somebody else's account is refused, never
        written. `parse_legs` goes through the team-scoped manager, so this can
        only ever read as "not found".
        """
        tx = self.make_split()
        resp = self.put_splits(
            tx,
            [
                {"category": self.foreign_account.id, "amount": "160.00"},
                {"category": self.household.id, "amount": "50.40"},
            ],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not found", str(resp.data))
        self.assertFalse(JournalLine.objects.filter(account=self.foreign_account).exists())

    def test_category_and_splits_are_mutually_exclusive(self):
        tx = self.make_plain()
        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "category": self.groceries.id,
                    "inflow": "0",
                    "outflow": "40.00",
                    "description": "Coffee",
                    "payee": "",
                    "splits": [
                        {"category": self.groceries.id, "amount": "20.00"},
                        {"category": self.household.id, "amount": "20.00"},
                    ],
                },
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not both", str(resp.data))


class SplitEditingTest(SplitTestCase):
    """Turning splits on and off, and what must survive it."""

    def test_split_a_plain_transaction(self):
        tx = self.make_plain(amount="40.00")
        entry_id = tx.journal_entry_id

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "inflow": "0",
                    "outflow": "40.00",
                    "description": "Coffee",
                    "payee": "",
                    "splits": [
                        {"category": self.groceries.id, "amount": "25.00"},
                        {"category": self.household.id, "amount": "15.00"},
                    ],
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        tx.refresh_from_db()
        self.assertEqual(tx.journal_entry_id, entry_id, "Splitting must not replace the entry.")
        self.assertEqual(tx.journal_entry.lines.count(), 3)
        self.assertTrue(resp.data["is_split"])
        self.assertBalanced(tx.journal_entry)

    def test_add_a_leg_to_an_existing_split(self):
        tx = self.make_split()
        bank_line_id = tx.journal_entry.lines.get(account=self.chequing).id

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "inflow": "0",
                    "outflow": "210.40",
                    "description": "Costco",
                    "payee": "",
                    "splits": [
                        {"category": self.groceries.id, "amount": "100.00"},
                        {"category": self.household.id, "amount": "50.40"},
                        {"category": self.shopping.id, "amount": "60.00"},
                    ],
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        tx.refresh_from_db()
        self.assertEqual(tx.journal_entry.lines.count(), 4)
        self.assertEqual(resp.data["split_count"], 3)
        self.assertEqual(
            tx.journal_entry.lines.get(account=self.chequing).id,
            bank_line_id,
            "The bank line must be updated in place, never recreated.",
        )
        self.assertBalanced(tx.journal_entry)

    def test_remove_split_collapses_to_one_category(self):
        tx = self.make_split()
        bank_line_id = tx.journal_entry.lines.get(account=self.chequing).id

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "category": self.groceries.id,
                    "inflow": "0",
                    "outflow": "210.40",
                    "description": "Costco",
                    "payee": "",
                    "splits": None,
                    "remove_split": True,
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        tx.refresh_from_db()
        self.assertEqual(tx.journal_entry.lines.count(), 2)
        self.assertFalse(resp.data["is_split"])
        self.assertEqual(resp.data["category"]["id"], self.groceries.id)
        self.assertEqual(tx.journal_entry.lines.get(account=self.chequing).id, bank_line_id)
        self.assertBalanced(tx.journal_entry)

    def test_reconciled_split_can_be_reapportioned(self):
        """
        Reconciliation is a fact about the bank line, whose amount does not change
        when the legs are re-apportioned -- so this is allowed, and the flag must
        survive it.
        """
        tx = self.make_split(reconciled=True)
        bank_line = tx.journal_entry.lines.get(account=self.chequing)

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "inflow": "0",
                    "outflow": "210.40",
                    "description": "Costco",
                    "payee": "",
                    "splits": [
                        {"category": self.groceries.id, "amount": "200.00"},
                        {"category": self.household.id, "amount": "10.40"},
                    ],
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        bank_line.refresh_from_db()
        self.assertTrue(bank_line.is_reconciled, "Re-apportioning must not silently unreconcile.")
        self.assertEqual(tx.journal_entry.lines.get(account=self.chequing).id, bank_line.id)
        self.assertBalanced(tx.journal_entry)

    def test_reconciled_split_cannot_change_its_total(self):
        tx = self.make_split(reconciled=True)

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "inflow": "0",
                    "outflow": "300.00",
                    "description": "Costco",
                    "payee": "",
                    "splits": [
                        {"category": self.groceries.id, "amount": "250.00"},
                        {"category": self.household.id, "amount": "50.00"},
                    ],
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reconciled", str(resp.data).lower())
        self.assertBalanced(tx.journal_entry)
        self.assertEqual(tx.journal_entry.total_credits, Decimal("210.40"))

    def test_decategorizing_a_split_removes_the_whole_entry(self):
        tx = self.make_split()
        entry_id = tx.journal_entry_id

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "category": None,
                    "inflow": "0",
                    "outflow": "210.40",
                    "description": "Costco",
                    "payee": "",
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        tx.refresh_from_db()
        self.assertIsNone(tx.journal_entry_id)
        self.assertFalse(JournalEntry.objects.filter(id=entry_id).exists())
        self.assertFalse(JournalLine.objects.filter(journal_entry_id=entry_id).exists())

    def test_moving_a_split_to_another_account(self):
        """The bank line must follow the move, and the legs must not."""
        tx = self.make_split()

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.savings.id,
                    "inflow": "0",
                    "outflow": "210.40",
                    "description": "Costco",
                    "payee": "",
                    "splits": [
                        {"category": self.groceries.id, "amount": "160.00"},
                        {"category": self.household.id, "amount": "50.40"},
                    ],
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        tx.refresh_from_db()
        self.assertEqual(tx.account_id, self.savings.id)
        self.assertFalse(tx.journal_entry.lines.filter(account=self.chequing).exists())
        self.assertEqual(tx.journal_entry.lines.get(account=self.savings).cr_amount, Decimal("210.40"))
        self.assertBalanced(tx.journal_entry)


class SplitReportingTest(SplitTestCase):
    """
    Budget actuals and reports aggregate per line, so they already handle splits.
    These lock that in: the whole point of a split is that each leg lands in its
    own category, and nothing here should ever need a special case.
    """

    def test_each_leg_lands_in_its_own_budget_actual(self):
        from apps.budget.services import BudgetService

        self.make_split()
        service = BudgetService(self.book)
        month = date(2026, 9, 1)

        self.assertEqual(service.actual(self.groceries, month), Decimal("160.00"))
        self.assertEqual(service.actual(self.household, month), Decimal("50.40"))

    def test_income_statement_counts_each_leg_once(self):
        from apps.reports.services import ReportService

        self.make_split()
        data = ReportService(self.book).get_income_statement_data(date(2026, 9, 1), date(2026, 9, 30))

        by_name = {item["account"].name: item["amount"] for item in data["expenses"]}
        self.assertEqual(by_name["Groceries"], Decimal("160.00"))
        self.assertEqual(by_name["Household Goods"], Decimal("50.40"))
        self.assertEqual(data["total_expenses"], Decimal("210.40"), "The split must not be double-counted.")


class SplitTransferMirrorTest(SplitTestCase):
    """
    A split with a transfer leg shows in both feeds.

    The split is written once, on the account that holds it; the transfer leg's
    other side appears as a mirror row, the same way a plain transfer does --
    so the counterpart feed never needs a row of its own.
    """

    def put_split(self, tx, legs, *, outflow="500.00", **extra):
        payload = {
            "date": "2026-09-14",
            "account": self.chequing.id,
            "inflow": "0",
            "outflow": outflow,
            "description": "Paycheque split",
            "payee": "",
            "splits": [{"category": account.id, "amount": amount} for account, amount in legs],
        }
        payload.update(extra)
        with current_book(self.book):
            return self.client.put(self.feed_url(f"{tx.id}/"), payload, format="json")

    def mirrors_of(self, tx):
        return list(BankTransaction.objects.filter(journal_entry_id=tx.journal_entry_id, is_transfer_mirror=True))

    def test_splitting_with_a_transfer_leg_creates_a_mirror_for_that_leg(self):
        tx = self.make_plain(amount="500.00")

        resp = self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertTrue(resp.data["is_split"])
        (mirror,) = self.mirrors_of(tx)
        self.assertEqual(mirror.account_id, self.savings.id)
        self.assertEqual(mirror.amount, Decimal("-80.00"), "Money arriving in savings is an inflow there.")
        self.assertEqual(mirror.posted_date, date(2026, 9, 14))
        self.assertEqual(mirror.description, "Paycheque split")
        self.assertEqual(mirror.source, BankTransaction.SOURCE_SYSTEM)
        self.assertBalanced(tx.journal_entry)

    def test_mirror_follows_the_leg_amount(self):
        tx = self.make_plain(amount="500.00")
        self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])

        resp = self.put_split(tx, [(self.groceries, "450.00"), (self.savings, "50.00")])

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        (mirror,) = self.mirrors_of(tx)
        self.assertEqual(mirror.amount, Decimal("-50.00"))

    def test_dropping_the_transfer_leg_drops_the_mirror(self):
        tx = self.make_plain(amount="500.00")
        self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])

        resp = self.put_split(tx, [(self.groceries, "300.00"), (self.household, "200.00")])

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(self.mirrors_of(tx), [])

    def test_a_plain_transfer_split_keeps_one_mirror_resized_to_the_leg(self):
        tx = self.make_plain(amount="500.00", category=self.groceries)
        with current_book(self.book):
            self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "category": self.savings.id,
                    "inflow": "0",
                    "outflow": "500.00",
                    "description": "To savings",
                    "payee": "",
                },
                format="json",
            )
        self.assertEqual([m.amount for m in self.mirrors_of(tx)], [Decimal("-500.00")])

        self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])

        self.assertEqual([m.amount for m in self.mirrors_of(tx)], [Decimal("-80.00")])

    def test_collapsing_to_a_transfer_keeps_one_mirror_for_the_whole_amount(self):
        tx = self.make_plain(amount="500.00")
        self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "category": self.savings.id,
                    "inflow": "0",
                    "outflow": "500.00",
                    "description": "To savings",
                    "payee": "",
                    "remove_split": True,
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual([m.amount for m in self.mirrors_of(tx)], [Decimal("-500.00")])

    def test_mirror_row_reads_as_a_plain_transfer_from_the_split_account(self):
        tx = self.make_plain(amount="500.00")
        self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])

        with current_book(self.book):
            resp = self.client.get(self.feed_url(f"?account={self.savings.id}"))

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        (row,) = resp.data["results"]
        self.assertFalse(row["is_split"])
        self.assertEqual(row["category"]["id"], self.chequing.id)
        self.assertEqual(Decimal(row["inflow"]), Decimal("80.00"))
        self.assertEqual(row["journal_entry_id"], tx.journal_entry_id)

    def test_the_mirror_cannot_be_edited_on_its_own(self):
        tx = self.make_plain(amount="500.00")
        self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])
        (mirror,) = self.mirrors_of(tx)

        with current_book(self.book):
            put = self.client.put(
                self.feed_url(f"{mirror.id}/"),
                {
                    "date": "2026-09-20",
                    "account": self.savings.id,
                    "category": self.chequing.id,
                    "inflow": "80.00",
                    "outflow": "0",
                    "description": "Changed",
                    "payee": "",
                },
                format="json",
            )
            batch = self.client.patch(self.feed_url("batch_edit/"), {"ids": [mirror.id], "payee": "X"}, format="json")

        self.assertEqual(put.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(batch.status_code, status.HTTP_400_BAD_REQUEST)
        mirror.refresh_from_db()
        self.assertEqual(mirror.description, "Paycheque split")
        self.assertEqual(tx.journal_entry.lines.count(), 3)

    def test_archiving_the_split_archives_its_mirror(self):
        tx = self.make_plain(amount="500.00")
        self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])
        (mirror,) = self.mirrors_of(tx)

        with current_book(self.book):
            resp = self.client.post(self.feed_url("batch_archive/"), {"ids": [tx.id]}, format="json")

        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        mirror.refresh_from_db()
        self.assertTrue(mirror.is_archived)

    def test_decategorizing_the_split_removes_its_mirror(self):
        tx = self.make_plain(amount="500.00")
        self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])
        (mirror,) = self.mirrors_of(tx)

        with current_book(self.book):
            resp = self.client.put(
                self.feed_url(f"{tx.id}/"),
                {
                    "date": "2026-09-14",
                    "account": self.chequing.id,
                    "inflow": "0",
                    "outflow": "500.00",
                    "description": "Paycheque split",
                    "payee": "",
                },
                format="json",
            )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertFalse(BankTransaction.objects.filter(id=mirror.id).exists())

    def test_sync_is_idempotent(self):
        tx = self.make_plain(amount="500.00")
        self.put_split(tx, [(self.groceries, "420.00"), (self.savings, "80.00")])
        tx.refresh_from_db()
        before = [(m.id, m.amount, m.updated_at) for m in self.mirrors_of(tx)]

        sync_transfer(tx)

        self.assertEqual([(m.id, m.amount, m.updated_at) for m in self.mirrors_of(tx)], before)
