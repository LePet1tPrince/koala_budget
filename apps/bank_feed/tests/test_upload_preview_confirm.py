"""
Tests for BankFeedViewSet.upload_preview and upload_confirm endpoints.
"""

import json
from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
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


class BankFeedViewSetUploadPreviewTest(TestCase):
    """Tests for BankFeedViewSet.upload_preview endpoint."""

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

        cls.bank_account = Account.objects.create(
            team=cls.team,
            name="Checking",
            account_number=1000,
            account_group=cls.asset_group,
            has_feed=True,
        )
        cls.groceries_account = Account.objects.create(
            team=cls.team,
            name="Groceries",
            account_number=4000,
            account_group=cls.expense_group,
        )

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _create_csv_file(self, content: str) -> SimpleUploadedFile:
        """Create a SimpleUploadedFile for CSV content."""
        return SimpleUploadedFile("test.csv", content.encode(), content_type="text/csv")

    def test_upload_preview_parses_transactions(self):
        """Test that preview returns parsed transaction list."""
        csv_content = "Date,Description,Amount\n2025-01-01,Test transaction,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data["transactions"]), 1)
            tx = response.data["transactions"][0]
            self.assertEqual(tx["description"], "Test transaction")
            self.assertEqual(tx["amount"], "100.00")

    def test_upload_preview_detects_duplicates(self):
        """Test that preview detects potential duplicates."""
        # Create existing transaction
        BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date(2025, 1, 1),
            description="Test transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        csv_content = "Date,Description,Amount\n2025-01-01,Test transaction,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.data["transactions"][0]["is_potential_duplicate"])
            self.assertEqual(response.data["duplicate_count"], 1)

    def test_upload_preview_matches_categories(self):
        """Test that preview matches categories by name."""
        csv_content = "Date,Description,Category,Amount\n2025-01-01,Test,Groceries,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "category": 2, "amount": 3}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            tx = response.data["transactions"][0]
            self.assertEqual(tx["matched_category_id"], self.groceries_account.id)

    def test_upload_preview_reports_unmapped_categories(self):
        """Test that preview reports unmapped categories."""
        csv_content = "Date,Description,Category,Amount\n2025-01-01,Test,UnknownCategory,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "category": 2, "amount": 3}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("UnknownCategory", response.data["unmapped_categories"])

    def test_upload_preview_handles_dual_column_amounts(self):
        """Test that preview handles separate inflow/outflow columns."""
        csv_content = "Date,Description,Inflow,Outflow\n2025-01-01,Deposit,100.00,\n2025-01-02,Purchase,,50.00"
        csv_file = self._create_csv_file(csv_content)

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "inflow": 2, "outflow": 3}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data["transactions"]), 2)
            # Inflow becomes negative (Plaid convention)
            self.assertEqual(response.data["transactions"][0]["amount"], "-100.00")
            # Outflow stays positive
            self.assertEqual(response.data["transactions"][1]["amount"], "50.00")

    def test_upload_preview_no_file_returns_400(self):
        """Test that missing file returns 400."""
        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_preview_invalid_account_returns_404(self):
        """Test that invalid account returns 404."""
        csv_content = "Date,Description,Amount\n2025-01-01,Test,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": 99999,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_upload_preview_invalid_column_mapping_returns_400(self):
        """Test that invalid column_mapping JSON returns 400."""
        csv_content = "Date,Description,Amount\n2025-01-01,Test,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": "invalid json{",
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class BankFeedViewSetUploadConfirmTest(TestCase):
    """Tests for BankFeedViewSet.upload_confirm endpoint."""

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

        cls.bank_account = Account.objects.create(
            team=cls.team,
            name="Checking",
            account_number=1000,
            account_group=cls.asset_group,
            has_feed=True,
        )
        cls.groceries_account = Account.objects.create(
            team=cls.team,
            name="Groceries",
            account_number=4000,
            account_group=cls.expense_group,
        )

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_upload_confirm_creates_bank_transactions(self):
        """Test that confirm creates BankTransaction records."""
        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_confirm/",
                {
                    "account_id": self.bank_account.id,
                    "transactions": [
                        {"date": "2025-01-01", "description": "Transaction 1", "payee": "", "amount": "100.00"},
                        {"date": "2025-01-02", "description": "Transaction 2", "payee": "", "amount": "-50.00"},
                    ],
                    "skip_duplicates": True,
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["created_count"], 2)
            self.assertEqual(BankTransaction.objects.filter(team=self.team).count(), 2)

    def test_upload_confirm_skips_duplicates(self):
        """Test that confirm skips duplicates when skip_duplicates=True."""
        # Create existing transaction
        BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date(2025, 1, 1),
            description="Existing transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_confirm/",
                {
                    "account_id": self.bank_account.id,
                    "transactions": [
                        {"date": "2025-01-01", "description": "Existing transaction", "payee": "", "amount": "100.00"},
                        {"date": "2025-01-02", "description": "New transaction", "payee": "", "amount": "50.00"},
                    ],
                    "skip_duplicates": True,
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["created_count"], 1)
            self.assertEqual(response.data["skipped_count"], 1)

    def test_upload_confirm_includes_duplicates_when_flag_false(self):
        """Test that confirm includes duplicates when skip_duplicates=False."""
        # Create existing transaction
        BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date(2025, 1, 1),
            description="Existing transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_confirm/",
                {
                    "account_id": self.bank_account.id,
                    "transactions": [
                        {"date": "2025-01-01", "description": "Existing transaction", "payee": "", "amount": "100.00"},
                    ],
                    "skip_duplicates": False,
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["created_count"], 1)
            self.assertEqual(response.data["skipped_count"], 0)
            # Total should now be 2 (original + duplicate)
            self.assertEqual(BankTransaction.objects.filter(team=self.team).count(), 2)

    def test_upload_confirm_auto_categorizes_with_category_id(self):
        """Test that confirm auto-categorizes transactions with category_id."""
        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_confirm/",
                {
                    "account_id": self.bank_account.id,
                    "transactions": [
                        {
                            "date": "2025-01-01",
                            "description": "Grocery shopping",
                            "payee": "Store",
                            "amount": "50.00",
                            "category_id": self.groceries_account.id,
                        },
                    ],
                    "skip_duplicates": True,
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["created_count"], 1)

            bank_tx = BankTransaction.objects.get(description="Grocery shopping")
            self.assertIsNotNone(bank_tx.journal_entry)
            self.assertEqual(JournalEntry.objects.count(), 1)

    def test_upload_confirm_returns_counts(self):
        """Test that confirm returns created_count, skipped_count, error_count."""
        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_confirm/",
                {
                    "account_id": self.bank_account.id,
                    "transactions": [
                        {"date": "2025-01-01", "description": "Valid", "payee": "", "amount": "100.00"},
                        {"date": "2025-01-02", "description": "Skipped", "payee": "", "amount": "50.00", "skip": True},
                    ],
                    "skip_duplicates": True,
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("created_count", response.data)
            self.assertIn("skipped_count", response.data)
            self.assertIn("error_count", response.data)
            self.assertEqual(response.data["created_count"], 1)
            self.assertEqual(response.data["skipped_count"], 1)
            self.assertEqual(response.data["error_count"], 0)

    def test_upload_confirm_invalid_account_returns_404(self):
        """Test that invalid account returns 404."""
        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_confirm/",
                {
                    "account_id": 99999,
                    "transactions": [
                        {"date": "2025-01-01", "description": "Test", "payee": "", "amount": "100.00"},
                    ],
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_upload_confirm_missing_required_fields_returns_400(self):
        """Test that missing required fields returns 400."""
        with current_team(self.team):
            # Missing account_id
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_confirm/",
                {
                    "transactions": [
                        {"date": "2025-01-01", "description": "Test", "payee": "", "amount": "100.00"},
                    ],
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
