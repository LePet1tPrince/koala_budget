"""
Tests for opening balances.

These are double-entry bookkeeping, so the assertions are about the ledger, not
the endpoint: every entry balances, the signs match what the rest of the app reads,
and the resulting net worth is the number the user typed.
"""

import json
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Account, AccountGroup
from apps.budget.services import NetWorthService
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.models import OnboardingState
from apps.onboarding.services.opening import (
    OpeningBalanceError,
    OpeningRow,
    balance_accounts,
    create_opening_balances,
    existing_opening_balances,
    parse_rows,
)
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

TODAY = date(2026, 9, 1)


class OpeningTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Opening", slug="opening")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="owner", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        assets = AccountGroup.objects.create(book=cls.book, name="Bank Accounts", account_type="asset")
        debts = AccountGroup.objects.create(book=cls.book, name="Credit Cards", account_type="liability")
        equity = AccountGroup.objects.create(
            book=cls.book, name="Equity Adjustments", account_type="goal", is_system=True
        )
        expenses = AccountGroup.objects.create(book=cls.book, name="Regular", account_type="expense")

        cls.chequing = Account.objects.create(
            book=cls.book, name="Chequing Account", account_group=assets, has_feed=True
        )
        cls.card = Account.objects.create(book=cls.book, name="Credit Card", account_group=debts, has_feed=True)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=expenses)
        cls.offset = Account.objects.create(
            book=cls.book, name="Reconciliation Adjustments", account_group=equity, is_system=True
        )

    def net_worth(self):
        return NetWorthService(self.book).get_net_worth(TODAY)

    def categorize_something(self):
        """The gate: opening balances wait for real categorized activity."""
        entry = JournalEntry.objects.create(
            book=self.book, entry_date=TODAY, description="LOBLAWS", status=JournalEntry.STATUS_POSTED
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.groceries, dr_amount=Decimal("42"), cr_amount=0
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.chequing, dr_amount=0, cr_amount=Decimal("42")
        )


class BalanceAccountsTest(OpeningTestCase):
    def test_offers_assets_and_debts_only(self):
        """Income and expense accounts measure flow, not a position."""
        names = {a.name for a in balance_accounts(self.book)}

        self.assertEqual(names, {"Chequing Account", "Credit Card"})

    def test_hides_system_accounts(self):
        self.assertNotIn("Reconciliation Adjustments", {a.name for a in balance_accounts(self.book)})


class ParseRowsTest(OpeningTestCase):
    def test_blank_and_zero_amounts_are_skipped(self):
        """Leaving a box empty is how the user skips an account."""
        rows = parse_rows(
            self.book,
            [
                {"account_id": self.chequing.id, "amount": ""},
                {"account_id": self.card.id, "amount": "0"},
            ],
        )

        self.assertEqual(rows, [])

    def test_amounts_are_quantized(self):
        rows = parse_rows(self.book, [{"account_id": self.chequing.id, "amount": "1234.567"}])

        self.assertEqual(rows[0].amount, Decimal("1234.57"))

    def test_a_non_numeric_amount_is_refused(self):
        with self.assertRaises(OpeningBalanceError):
            parse_rows(self.book, [{"account_id": self.chequing.id, "amount": "lots"}])

    def test_a_negative_amount_is_refused(self):
        """A debt is entered as what is owed, so a negative is a misunderstanding."""
        with self.assertRaises(OpeningBalanceError):
            parse_rows(self.book, [{"account_id": self.card.id, "amount": "-500"}])

    def test_an_expense_account_is_refused_rather_than_ignored(self):
        """Dropping it silently would leave the user believing they had set it."""
        with self.assertRaises(OpeningBalanceError):
            parse_rows(self.book, [{"account_id": self.groceries.id, "amount": "100"}])

    def test_another_teams_account_is_refused(self):
        other = Team.objects.create(name="Theirs", slug="theirs-opening")
        other_book = other.default_book
        group = AccountGroup.objects.create(book=other_book, name="Bank Accounts", account_type="asset")
        theirs = Account.objects.create(book=other_book, name="Their Chequing", account_group=group)

        with self.assertRaises(OpeningBalanceError):
            parse_rows(self.book, [{"account_id": theirs.id, "amount": "100"}])

    def test_garbage_is_tolerated(self):
        self.assertEqual(parse_rows(self.book, "nope"), [])
        self.assertEqual(parse_rows(self.book, [None, 7, {}]), [])


class CreateOpeningBalancesTest(OpeningTestCase):
    def test_an_asset_entry_balances_and_raises_net_worth(self):
        create_opening_balances(self.book, [OpeningRow(self.chequing, Decimal("2500"))], as_of=TODAY)

        entry = JournalEntry.objects.get(book=self.book)
        totals = entry.lines.aggregate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
        self.assertEqual(totals["dr"], totals["cr"])

        line = entry.lines.get(account=self.chequing)
        self.assertEqual(line.dr_amount, Decimal("2500"))
        self.assertEqual(self.net_worth(), Decimal("2500"))

    def test_a_debt_entry_balances_and_lowers_net_worth(self):
        create_opening_balances(self.book, [OpeningRow(self.card, Decimal("800"))], as_of=TODAY)

        line = JournalLine.objects.get(book=self.book, account=self.card)
        self.assertEqual(line.cr_amount, Decimal("800"))
        self.assertEqual(self.net_worth(), Decimal("-800"))

    def test_assets_and_debts_net_out(self):
        create_opening_balances(
            self.book,
            [OpeningRow(self.chequing, Decimal("2500")), OpeningRow(self.card, Decimal("800"))],
            as_of=TODAY,
        )

        self.assertEqual(self.net_worth(), Decimal("1700"))

    def test_everything_offsets_to_the_system_equity_account(self):
        create_opening_balances(self.book, [OpeningRow(self.chequing, Decimal("100"))], as_of=TODAY)

        self.assertTrue(JournalLine.objects.filter(book=self.book, account=self.offset).exists())

    def test_entries_are_posted_not_draft(self):
        """A draft entry is excluded from balances, so the reveal would show nothing."""
        create_opening_balances(self.book, [OpeningRow(self.chequing, Decimal("100"))], as_of=TODAY)

        self.assertEqual(JournalEntry.objects.get(book=self.book).status, JournalEntry.STATUS_POSTED)

    def test_no_rows_creates_nothing(self):
        create_opening_balances(self.book, [], as_of=TODAY)

        self.assertFalse(JournalEntry.objects.filter(book=self.book).exists())

    def test_a_team_with_no_equity_account_is_refused(self):
        self.offset.delete()

        with self.assertRaises(OpeningBalanceError):
            create_opening_balances(self.book, [OpeningRow(self.chequing, Decimal("100"))], as_of=TODAY)

    def test_existing_balances_are_reported(self):
        create_opening_balances(self.book, [OpeningRow(self.chequing, Decimal("100"))], as_of=TODAY)

        self.assertEqual(existing_opening_balances(self.book), {self.chequing.id})


class OpeningBalanceEndpointTest(OpeningTestCase):
    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("onboarding:api_opening_balances", args=[self.team.slug, self.book.slug])
        state = OnboardingState.objects.create(book=self.book)
        state.complete()
        state.save()

    def post(self, payload):
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            headers={"accept": "application/json"},
        )

    def test_refused_before_anything_is_categorized(self):
        """
        The gate is real, not merely hidden in the UI: anchoring a net worth before
        the user has seen any categorized activity gives them nothing to check it
        against.
        """
        response = self.post({"rows": [{"account_id": self.chequing.id, "amount": "2500"}]})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(JournalEntry.objects.filter(book=self.book, description__startswith="Opening").exists())

    def test_get_reports_the_gate_rather_than_the_accounts(self):
        payload = self.client.get(self.url).json()

        self.assertFalse(payload["allowed"])
        self.assertTrue(payload["error"])

    def test_lists_accounts_once_unlocked(self):
        self.categorize_something()
        payload = self.client.get(self.url).json()

        self.assertTrue(payload["allowed"])
        self.assertEqual({a["name"] for a in payload["accounts"]}, {"Chequing Account", "Credit Card"})

    def test_saving_returns_the_before_and_after(self):
        self.categorize_something()
        before = self.net_worth()

        response = self.post(
            {
                "rows": [
                    {"account_id": self.chequing.id, "amount": "2500"},
                    {"account_id": self.card.id, "amount": "800"},
                ]
            }
        )

        data = response.json()
        self.assertEqual(Decimal(data["net_worth_before"]), before)
        self.assertEqual(Decimal(data["net_worth"]), before + Decimal("1700"))
        self.assertEqual(data["created"], 2)

    def test_a_second_submission_does_not_double_the_balance(self):
        """The step can be revisited; setting it twice would silently double it."""
        self.categorize_something()
        rows = {"rows": [{"account_id": self.chequing.id, "amount": "2500"}]}

        self.post(rows)
        after_first = self.net_worth()
        self.post(rows)

        self.assertEqual(self.net_worth(), after_first)

    def test_an_invalid_amount_creates_nothing(self):
        self.categorize_something()
        before = self.net_worth()

        response = self.post({"rows": [{"account_id": self.chequing.id, "amount": "heaps"}]})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.net_worth(), before)

    def test_records_the_step_against_the_walkthrough(self):
        self.categorize_something()
        self.post({"rows": [{"account_id": self.chequing.id, "amount": "10"}]})

        self.assertIn("opening_balances", OnboardingState.objects.get(book=self.book).tasks_done)

    def test_non_member_is_refused(self):
        self.categorize_something()
        before = self.net_worth()
        outsider = CustomUser.objects.create_user(username="nosy", password="pass")
        self.client.force_login(outsider)

        self.post({"rows": [{"account_id": self.chequing.id, "amount": "9999"}]})
        self.assertEqual(self.net_worth(), before)
