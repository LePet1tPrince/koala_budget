"""
Tests for BankFeedViewSet.categorize endpoint.
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
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class BankFeedViewSetCategorizeTest(TestCase):
    """Tests for BankFeedViewSet.categorize endpoint."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME)

        cls.bank_account = Account.objects.create(
            team=cls.team,
            name="Checking",
            account_number=1000,
            account_group=cls.asset_group,
            has_feed=True,
        )
        cls.expense_category = Account.objects.create(
            team=cls.team,
            name="Groceries",
            account_number=4000,
            account_group=cls.expense_group,
        )
        cls.income_category = Account.objects.create(
            team=cls.team,
            name="Salary",
            account_number=3000,
            account_group=cls.income_group,
        )

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_categorize_creates_journal_entry(self):
        """Test that categorize creates a JournalEntry with correct lines."""
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Grocery shopping",
            amount=Decimal("50.00"),  # Positive = outflow
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
                {
                    "rows": [{"id": bank_tx.id}],
                    "category_id": self.expense_category.id,
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            self.assertEqual(JournalEntry.objects.count(), 1)

            journal_entry = JournalEntry.objects.first()
            self.assertEqual(journal_entry.description, "Grocery shopping")
            self.assertEqual(journal_entry.lines.count(), 2)
            self.assertTrue(journal_entry.is_balanced)

    def test_categorize_links_transaction_to_journal(self):
        """Test that categorize sets bank_tx.journal_entry."""
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Test transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
                {
                    "rows": [{"id": bank_tx.id}],
                    "category_id": self.expense_category.id,
                },
                format="json",
            )

            bank_tx.refresh_from_db()
            self.assertIsNotNone(bank_tx.journal_entry)
            self.assertEqual(bank_tx.journal_entry.description, "Test transaction")

    def test_categorize_handles_inflow_correctly(self):
        """Test that negative amount (inflow) creates correct journal entry."""
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Paycheck",
            amount=Decimal("-1000.00"),  # Negative = inflow
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
                {
                    "rows": [{"id": bank_tx.id}],
                    "category_id": self.income_category.id,
                },
                format="json",
            )

            journal_entry = JournalEntry.objects.first()
            bank_line = journal_entry.lines.get(account=self.bank_account)
            category_line = journal_entry.lines.get(account=self.income_category)

            # Inflow: debit bank, credit category
            self.assertEqual(bank_line.dr_amount, Decimal("1000.00"))
            self.assertEqual(bank_line.cr_amount, Decimal("0"))
            self.assertEqual(category_line.dr_amount, Decimal("0"))
            self.assertEqual(category_line.cr_amount, Decimal("1000.00"))

    def test_categorize_handles_outflow_correctly(self):
        """Test that positive amount (outflow) creates correct journal entry."""
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Groceries",
            amount=Decimal("50.00"),  # Positive = outflow
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
                {
                    "rows": [{"id": bank_tx.id}],
                    "category_id": self.expense_category.id,
                },
                format="json",
            )

            journal_entry = JournalEntry.objects.first()
            bank_line = journal_entry.lines.get(account=self.bank_account)
            category_line = journal_entry.lines.get(account=self.expense_category)

            # Outflow: credit bank, debit category
            self.assertEqual(bank_line.dr_amount, Decimal("0"))
            self.assertEqual(bank_line.cr_amount, Decimal("50.00"))
            self.assertEqual(category_line.dr_amount, Decimal("50.00"))
            self.assertEqual(category_line.cr_amount, Decimal("0"))

    def test_categorize_multiple_transactions(self):
        """Test that batch categorization works for multiple transactions."""
        bank_tx1 = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Transaction 1",
            amount=Decimal("25.00"),
            source=BankTransaction.SOURCE_CSV,
        )
        bank_tx2 = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Transaction 2",
            amount=Decimal("75.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
                {
                    "rows": [{"id": bank_tx1.id}, {"id": bank_tx2.id}],
                    "category_id": self.expense_category.id,
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            self.assertEqual(JournalEntry.objects.count(), 2)

            bank_tx1.refresh_from_db()
            bank_tx2.refresh_from_db()
            self.assertIsNotNone(bank_tx1.journal_entry)
            self.assertIsNotNone(bank_tx2.journal_entry)

    def test_categorize_missing_rows_returns_400(self):
        """Test that missing rows field returns 400."""
        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
                {"category_id": self.expense_category.id},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("error", response.data)

    def test_categorize_missing_category_id_returns_400(self):
        """Test that missing category_id returns 400."""
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Test",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
                {"rows": [{"id": bank_tx.id}]},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("error", response.data)

    def test_categorize_invalid_category_returns_404(self):
        """Test that invalid category_id returns 404."""
        bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Test",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
                {
                    "rows": [{"id": bank_tx.id}],
                    "category_id": 99999,
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_categorize_empty_rows_returns_400(self):
        """Test that categorizing with empty rows returns 400."""
        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
                {
                    "rows": [],
                    "category_id": self.expense_category.id,
                },
                format="json",
            )

            # Empty rows should return 400
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
