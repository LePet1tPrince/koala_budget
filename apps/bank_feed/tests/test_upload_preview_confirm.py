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
from apps.books.context import current_book
from apps.journal.models import JournalEntry
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class BankFeedViewSetUploadPreviewTest(TestCase):
    """Tests for BankFeedViewSet.upload_preview endpoint."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            book=cls.book, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )

        cls.bank_account = Account.objects.create(
            book=cls.book,
            name="Checking",
            account_group=cls.asset_group,
            has_feed=True,
        )
        cls.groceries_account = Account.objects.create(
            book=cls.book,
            name="Groceries",
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

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
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

    def test_upload_preview_tags_date_errors_with_the_field_and_raw_value(self):
        """A row rejected by the chosen date format reports error_field='date' and its raw cell."""
        csv_content = "Date,Description,Amount\n28/02/2025,Test transaction,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2}),
                    "date_format": "%m/%d/%Y",
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            tx = response.data["transactions"][0]
            self.assertEqual(tx["error_field"], "date")
            self.assertEqual(tx["raw_date"], "28/02/2025")
            self.assertIn("Invalid date", tx["error"])
            self.assertEqual(response.data["error_count"], 1)

    def test_upload_preview_tags_amount_errors_with_the_field(self):
        """A row with an unparseable amount reports error_field='amount'."""
        csv_content = "Date,Description,Amount\n2025-01-01,Test transaction,not-a-number"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            tx = response.data["transactions"][0]
            self.assertEqual(tx["error_field"], "amount")
            self.assertIn("Invalid amount", tx["error"])

    def test_upload_preview_valid_row_has_no_error_field(self):
        """A clean row carries no error_field but still reports its raw date cell."""
        csv_content = "Date,Description,Amount\n2025-01-01,Test transaction,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2}),
                },
                format="multipart",
            )

            tx = response.data["transactions"][0]
            self.assertIsNone(tx["error_field"])
            self.assertEqual(tx["raw_date"], "2025-01-01")

    def test_upload_preview_inverts_single_column_amounts(self):
        """invert_amounts flips a single amount column: the file's outflow becomes an inflow."""
        csv_content = "Date,Description,Amount\n2025-01-01,Purchase,100.00\n2025-01-02,Refund,-25.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2, "invert_amounts": True}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            amounts = [tx["amount"] for tx in response.data["transactions"]]
            self.assertEqual(amounts, ["-100.00", "25.00"])

    def test_upload_preview_without_invert_keeps_signs(self):
        """The flag defaults off, leaving the file's own signs untouched."""
        csv_content = "Date,Description,Amount\n2025-01-01,Purchase,100.00\n2025-01-02,Refund,-25.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2}),
                },
                format="multipart",
            )

            amounts = [tx["amount"] for tx in response.data["transactions"]]
            self.assertEqual(amounts, ["100.00", "-25.00"])

    def test_upload_preview_invert_leaves_zero_unsigned(self):
        """A zero amount must not come back as -0.00."""
        csv_content = "Date,Description,Amount\n2025-01-01,Zero fee,0.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "amount": 2, "invert_amounts": True}),
                },
                format="multipart",
            )

            self.assertEqual(response.data["transactions"][0]["amount"], "0.00")

    def test_upload_preview_invert_is_ignored_in_dual_column_mode(self):
        """Dual-column files swap direction by re-picking columns, so the flag must not apply."""
        csv_content = "Date,Description,In,Out\n2025-01-01,Purchase,,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps(
                        {"date": 0, "description": 1, "inflow": 2, "outflow": 3, "invert_amounts": True}
                    ),
                },
                format="multipart",
            )

            # Outflow stays positive under the Plaid convention.
            self.assertEqual(response.data["transactions"][0]["amount"], "100.00")

    def test_upload_preview_invert_flows_into_category_totals(self):
        """The flip happens at parse time, so per-category inflow/outflow totals follow it."""
        csv_content = "Date,Description,Category,Amount\n2025-01-01,Payday,Salary,1000.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps(
                        {"date": 0, "description": 1, "category": 2, "amount": 3, "invert_amounts": True}
                    ),
                },
                format="multipart",
            )

            unmapped = response.data["unmapped_categories"][0]
            self.assertEqual(unmapped["name"], "Salary")
            # Without the flip this would have counted as 1000 of outflow.
            self.assertEqual(unmapped["inflow"], "1000.00")
            self.assertEqual(unmapped["outflow"], "0.00")

    def test_upload_preview_detects_duplicates(self):
        """Test that preview detects potential duplicates."""
        # Create existing transaction
        BankTransaction.objects.create(
            book=self.book,
            account=self.bank_account,
            posted_date=date(2025, 1, 1),
            description="Test transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        csv_content = "Date,Description,Amount\n2025-01-01,Test transaction,100.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
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

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
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

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "category": 2, "amount": 3}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            names = [c["name"] for c in response.data["unmapped_categories"]]
            self.assertIn("UnknownCategory", names)

    def test_upload_preview_unmapped_category_includes_flow_totals(self):
        """Unmapped categories carry per-category inflow/outflow totals and a count."""
        # Two outflows and one inflow under the same unmatched category.
        csv_content = (
            "Date,Description,Category,Amount\n"
            "2025-01-01,A,Mystery,100.00\n"
            "2025-01-02,B,Mystery,25.00\n"
            "2025-01-03,C,Mystery,-40.00"
        )
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "category": 2, "amount": 3}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            unmapped = response.data["unmapped_categories"]
            self.assertEqual(len(unmapped), 1)
            cat = unmapped[0]
            self.assertEqual(cat["name"], "Mystery")
            self.assertEqual(cat["count"], 3)
            # Outflows: 100 + 25; inflow: 40 (positive = outflow in Plaid convention)
            self.assertEqual(Decimal(cat["outflow"]), Decimal("125.00"))
            self.assertEqual(Decimal(cat["inflow"]), Decimal("40.00"))

    def test_upload_preview_suggests_account_for_unmapped_category(self):
        """A close-name account is offered as a suggestion for an unmapped category."""
        Account.objects.create(
            book=self.book,
            name="Restaurants",
            account_group=self.expense_group,
        )
        csv_content = "Date,Description,Category,Amount\n2025-01-01,Dinner,Restaurant,40.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
                {
                    "file": csv_file,
                    "account_id": self.bank_account.id,
                    "column_mapping": json.dumps({"date": 0, "description": 1, "category": 2, "amount": 3}),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            cat = response.data["unmapped_categories"][0]
            self.assertEqual(cat["suggested_account_name"], "Restaurants")
            self.assertIsNotNone(cat["suggested_account_id"])

    def test_upload_preview_handles_dual_column_amounts(self):
        """Test that preview handles separate inflow/outflow columns."""
        csv_content = "Date,Description,Inflow,Outflow\n2025-01-01,Deposit,100.00,\n2025-01-02,Purchase,,50.00"
        csv_file = self._create_csv_file(csv_content)

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
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
        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
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

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
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

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_preview/",
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
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            book=cls.book, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )

        cls.bank_account = Account.objects.create(
            book=cls.book,
            name="Checking",
            account_group=cls.asset_group,
            has_feed=True,
        )
        cls.groceries_account = Account.objects.create(
            book=cls.book,
            name="Groceries",
            account_group=cls.expense_group,
        )

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_upload_confirm_creates_bank_transactions(self):
        """Test that confirm creates BankTransaction records."""
        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_confirm/",
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
            self.assertEqual(BankTransaction.objects.filter(book=self.book).count(), 2)

    def test_upload_confirm_skips_duplicates(self):
        """Test that confirm skips duplicates when skip_duplicates=True."""
        # Create existing transaction
        BankTransaction.objects.create(
            book=self.book,
            account=self.bank_account,
            posted_date=date(2025, 1, 1),
            description="Existing transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_confirm/",
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
            book=self.book,
            account=self.bank_account,
            posted_date=date(2025, 1, 1),
            description="Existing transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_confirm/",
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
            self.assertEqual(BankTransaction.objects.filter(book=self.book).count(), 2)

    def test_upload_confirm_auto_categorizes_with_category_id(self):
        """Test that confirm auto-categorizes transactions with category_id."""
        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_confirm/",
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
        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_confirm/",
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
        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_confirm/",
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
        with current_book(self.book):
            # Missing account_id
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/upload_confirm/",
                {
                    "transactions": [
                        {"date": "2025-01-01", "description": "Test", "payee": "", "amount": "100.00"},
                    ],
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
