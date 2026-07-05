"""
Tests for creating/updating manual bank feed transactions via BankFeedViewSet.

Focus: a manual transaction may be created (or edited) with a blank category,
leaving it uncategorized (no journal entry) for the user to categorize later.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class ManualTransactionCreateTest(TestCase):
    """Creating manual transactions with and without a category."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking", account_group=cls.asset_group, has_feed=True
        )
        cls.expense_category = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _create(self, body):
        with current_team(self.team):
            return self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/",
                body,
                format="json",
            )

    def test_create_with_category_creates_journal_entry(self):
        """A category still creates a linked, balanced journal entry (unchanged behavior)."""
        response = self._create(
            {
                "date": "2026-01-15",
                "category": self.expense_category.id,
                "outflow": "50.00",
                "account": self.bank_account.id,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(JournalEntry.objects.count(), 1)
        bank_tx = BankTransaction.objects.get()
        self.assertIsNotNone(bank_tx.journal_entry)
        self.assertTrue(bank_tx.journal_entry.is_balanced)

    def test_create_without_category_is_uncategorized(self):
        """A blank category creates an uncategorized transaction with no journal entry."""
        response = self._create(
            {
                "date": "2026-01-15",
                "outflow": "50.00",
                "account": self.bank_account.id,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(JournalEntry.objects.count(), 0)

        bank_tx = BankTransaction.objects.get()
        self.assertIsNone(bank_tx.journal_entry)
        self.assertEqual(bank_tx.amount, Decimal("50.00"))
        self.assertEqual(bank_tx.source, BankTransaction.SOURCE_MANUAL)

        # It surfaces as an uncategorized feed row (category is null)
        self.assertIsNone(response.data["category"])
        self.assertIsNone(response.data["journal_entry_id"])

    def test_create_with_null_category_is_uncategorized(self):
        """An explicit null category is accepted (same as omitting it)."""
        response = self._create(
            {
                "date": "2026-01-15",
                "category": None,
                "inflow": "120.00",
                "account": self.bank_account.id,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(JournalEntry.objects.count(), 0)
        bank_tx = BankTransaction.objects.get()
        self.assertIsNone(bank_tx.journal_entry)
        # Inflow stored with Plaid convention (negative = inflow)
        self.assertEqual(bank_tx.amount, Decimal("-120.00"))

    def test_create_still_requires_an_amount(self):
        """Amount validation is unchanged — zero inflow and outflow is rejected."""
        response = self._create(
            {
                "date": "2026-01-15",
                "account": self.bank_account.id,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_bad_category_returns_404(self):
        """A non-null category that doesn't exist still 404s."""
        response = self._create(
            {
                "date": "2026-01-15",
                "category": 99999,
                "outflow": "50.00",
                "account": self.bank_account.id,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ManualTransactionUpdateTest(TestCase):
    """Editing a manual transaction's category, including clearing it."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking", account_group=cls.asset_group, has_feed=True
        )
        cls.expense_category = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _update(self, tx_id, body):
        with current_team(self.team):
            return self.client.put(
                f"/a/{self.team.slug}/bankfeed/api/feed/{tx_id}/",
                body,
                format="json",
            )

    def test_clearing_category_decategorizes(self):
        """Clearing the category on a categorized transaction removes its journal entry."""
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date(2026, 1, 10),
            description="Groceries",
            amount=Decimal("50.00"),
            source=BankTransaction.SOURCE_MANUAL,
        )
        entry = JournalEntry.objects.create(
            team=self.team,
            entry_date=bank_tx.posted_date,
            description="Groceries",
            source=JournalEntry.SOURCE_MANUAL,
            status=JournalEntry.STATUS_POSTED,
        )
        from apps.journal.models import JournalLine

        JournalLine.objects.create(
            journal_entry=entry,
            team=self.team,
            account=self.bank_account,
            dr_amount=Decimal("0"),
            cr_amount=Decimal("50.00"),
        )
        JournalLine.objects.create(
            journal_entry=entry,
            team=self.team,
            account=self.expense_category,
            dr_amount=Decimal("50.00"),
            cr_amount=Decimal("0"),
        )
        bank_tx.journal_entry = entry
        bank_tx.save()

        response = self._update(
            bank_tx.id,
            {
                "date": "2026-01-10",
                "outflow": "50.00",
                "account": self.bank_account.id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bank_tx.refresh_from_db()
        self.assertIsNone(bank_tx.journal_entry)
        self.assertFalse(JournalEntry.objects.filter(id=entry.id).exists())
        self.assertIsNone(response.data["category"])

    def test_editing_uncategorized_transaction_stays_uncategorized(self):
        """Editing fields on an uncategorized transaction without a category keeps it uncategorized."""
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date(2026, 1, 10),
            description="Pending",
            amount=Decimal("30.00"),
            source=BankTransaction.SOURCE_MANUAL,
        )

        response = self._update(
            bank_tx.id,
            {
                "date": "2026-01-11",
                "outflow": "35.00",
                "description": "Updated",
                "account": self.bank_account.id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(JournalEntry.objects.count(), 0)
        bank_tx.refresh_from_db()
        self.assertIsNone(bank_tx.journal_entry)
        self.assertEqual(bank_tx.amount, Decimal("35.00"))
        self.assertEqual(bank_tx.description, "Updated")

    def test_adding_category_to_uncategorized_creates_entry(self):
        """Setting a category on an uncategorized transaction creates a journal entry."""
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date(2026, 1, 10),
            description="Groceries",
            amount=Decimal("50.00"),
            source=BankTransaction.SOURCE_MANUAL,
        )

        response = self._update(
            bank_tx.id,
            {
                "date": "2026-01-10",
                "category": self.expense_category.id,
                "outflow": "50.00",
                "account": self.bank_account.id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(JournalEntry.objects.count(), 1)
        bank_tx.refresh_from_db()
        self.assertIsNotNone(bank_tx.journal_entry)
        self.assertTrue(bank_tx.journal_entry.is_balanced)
