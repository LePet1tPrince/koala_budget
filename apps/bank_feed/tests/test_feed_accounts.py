"""
Tests for feed_accounts endpoint with latest_reconciled_date.
"""

from datetime import date, timedelta
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
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class FeedAccountsEndpointTest(TestCase):
    """Tests for the feed_accounts endpoint with latest_reconciled_date."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        # Team and user
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        # Account groups
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )

        # Accounts
        cls.bank_account = Account.objects.create(
            team=cls.team,
            name="Checking",
            account_group=cls.asset_group,
            has_feed=True,
        )
        cls.expense_account = Account.objects.create(
            team=cls.team,
            name="Groceries",
            account_group=cls.expense_group,
        )

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_feed_accounts_returns_latest_reconciled_date(self):
        """Test that feed_accounts endpoint returns latest_reconciled_date."""
        today = date.today()

        # Create a journal entry with reconciled lines
        entry = JournalEntry.objects.create(team=self.team, posted_date=today)
        JournalLine.objects.create(
            team=self.team,
            journal_entry=entry,
            account=self.bank_account,
            dr_amount=Decimal("100.00"),
            is_reconciled=True,
        )
        JournalLine.objects.create(
            team=self.team,
            journal_entry=entry,
            account=self.expense_account,
            cr_amount=Decimal("100.00"),
        )

        # Create a bank transaction linked to the entry
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=today,
            description="Test transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )

        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/feed-accounts/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data), 1)

            account = response.data[0]
            self.assertEqual(account["id"], self.bank_account.id)
            self.assertEqual(account["latest_reconciled_date"], str(today))

    def test_feed_accounts_no_reconciled_date_without_reconciliation(self):
        """Test that latest_reconciled_date is None when no transactions are reconciled."""
        # Create a journal entry without reconciliation
        entry = JournalEntry.objects.create(team=self.team, posted_date=date.today())
        JournalLine.objects.create(
            team=self.team,
            journal_entry=entry,
            account=self.bank_account,
            dr_amount=Decimal("100.00"),
            is_reconciled=False,
        )
        JournalLine.objects.create(
            team=self.team,
            journal_entry=entry,
            account=self.expense_account,
            cr_amount=Decimal("100.00"),
        )

        # Create a bank transaction linked to the entry
        BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Test transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )

        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/feed-accounts/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data), 1)

            account = response.data[0]
            self.assertEqual(account["id"], self.bank_account.id)
            self.assertIsNone(account["latest_reconciled_date"])

    def test_feed_accounts_latest_reconciled_date_most_recent(self):
        """Test that latest_reconciled_date shows the most recent reconciled date."""
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Create two journal entries with reconciled lines on different dates
        entry1 = JournalEntry.objects.create(team=self.team, posted_date=yesterday)
        JournalLine.objects.create(
            team=self.team,
            journal_entry=entry1,
            account=self.bank_account,
            dr_amount=Decimal("50.00"),
            is_reconciled=True,
        )
        JournalLine.objects.create(
            team=self.team,
            journal_entry=entry1,
            account=self.expense_account,
            cr_amount=Decimal("50.00"),
        )

        entry2 = JournalEntry.objects.create(team=self.team, posted_date=today)
        JournalLine.objects.create(
            team=self.team,
            journal_entry=entry2,
            account=self.bank_account,
            dr_amount=Decimal("100.00"),
            is_reconciled=True,
        )
        JournalLine.objects.create(
            team=self.team,
            journal_entry=entry2,
            account=self.expense_account,
            cr_amount=Decimal("100.00"),
        )

        # Create bank transactions linked to the entries
        BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=yesterday,
            description="Test transaction 1",
            amount=Decimal("50.00"),
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry1,
        )
        BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=today,
            description="Test transaction 2",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry2,
        )

        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/feed-accounts/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data), 1)

            account = response.data[0]
            self.assertEqual(account["id"], self.bank_account.id)
            # Should show the most recent reconciled date
            self.assertEqual(account["latest_reconciled_date"], str(today))

    def test_feed_accounts_no_date_without_categorization(self):
        """Test that latest_reconciled_date is None for uncategorized transactions."""
        # Create uncategorized bank transaction
        BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Uncategorized transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/feed-accounts/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data), 1)

            account = response.data[0]
            self.assertEqual(account["id"], self.bank_account.id)
            self.assertIsNone(account["latest_reconciled_date"])
