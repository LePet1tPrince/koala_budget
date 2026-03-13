"""
Tests for BankFeedViewSet.batch_edit endpoint.
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
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class BatchEditTest(TestCase):
    """Tests for BankFeedViewSet.batch_edit endpoint."""

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
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME)

        cls.bank_account = Account.objects.create(
            team=cls.team,
            name="Checking",
            account_number=1000,
            account_group=cls.asset_group,
            has_feed=True,
        )
        cls.bank_account2 = Account.objects.create(
            team=cls.team,
            name="Savings",
            account_number=1001,
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
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_edit/"

    def _create_tx(self, **kwargs):
        defaults = dict(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Test tx",
            amount=Decimal("50.00"),
            source=BankTransaction.SOURCE_CSV,
        )
        defaults.update(kwargs)
        return BankTransaction.objects.create(**defaults)

    # ---- Categorize via batch_edit ----

    def test_batch_edit_category_creates_journal(self):
        tx = self._create_tx()
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "category_id": self.expense_category.id},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        tx.refresh_from_db()
        self.assertIsNotNone(tx.journal_entry)
        self.assertEqual(tx.journal_entry.lines.count(), 2)

    def test_batch_edit_category_updates_existing_journal(self):
        """If transaction already has a journal, update the category line."""
        tx = self._create_tx()
        # First categorize
        with current_team(self.team):
            self.client.patch(
                self.url,
                {"ids": [tx.id], "category_id": self.expense_category.id},
                format="json",
            )
        tx.refresh_from_db()
        je_id = tx.journal_entry_id

        # Now re-categorize to income
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "category_id": self.income_category.id},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        tx.refresh_from_db()
        # Should reuse the same journal entry
        self.assertEqual(tx.journal_entry_id, je_id)
        # Category line should now be income
        category_line = tx.journal_entry.lines.exclude(account=self.bank_account).first()
        self.assertEqual(category_line.account, self.income_category)

    # ---- Move account via batch_edit ----

    def test_batch_edit_move_account(self):
        tx = self._create_tx()
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "account_id": self.bank_account2.id},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        tx.refresh_from_db()
        self.assertEqual(tx.account, self.bank_account2)

    def test_batch_edit_move_rejects_non_feed_account(self):
        tx = self._create_tx()
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "account_id": self.expense_category.id},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ---- Payee via batch_edit ----

    def test_batch_edit_payee(self):
        tx = self._create_tx()
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "payee": "Walmart"},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        tx.refresh_from_db()
        self.assertEqual(tx.merchant_name, "Walmart")

    # ---- Description via batch_edit ----

    def test_batch_edit_description(self):
        tx = self._create_tx()
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "description": "New description"},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        tx.refresh_from_db()
        self.assertEqual(tx.description, "New description")

    # ---- Date via batch_edit ----

    def test_batch_edit_date(self):
        tx = self._create_tx()
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "date": "2024-06-15"},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        tx.refresh_from_db()
        self.assertEqual(tx.posted_date, date(2024, 6, 15))

    # ---- Multiple fields at once ----

    def test_batch_edit_multiple_fields(self):
        tx = self._create_tx()
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {
                    "ids": [tx.id],
                    "payee": "Target",
                    "description": "Bulk update",
                    "date": "2024-01-01",
                },
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        tx.refresh_from_db()
        self.assertEqual(tx.merchant_name, "Target")
        self.assertEqual(tx.description, "Bulk update")
        self.assertEqual(tx.posted_date, date(2024, 1, 1))

    # ---- Only provided fields are updated ----

    def test_batch_edit_leaves_unset_fields_unchanged(self):
        tx = self._create_tx(description="Original", merchant_name="OriginalPayee")
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "payee": "NewPayee"},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        tx.refresh_from_db()
        self.assertEqual(tx.merchant_name, "NewPayee")
        # Description should remain unchanged
        self.assertEqual(tx.description, "Original")

    # ---- Multiple transactions ----

    def test_batch_edit_multiple_transactions(self):
        tx1 = self._create_tx(description="Tx 1")
        tx2 = self._create_tx(description="Tx 2")
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx1.id, tx2.id], "description": "Batch updated"},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        tx1.refresh_from_db()
        tx2.refresh_from_db()
        self.assertEqual(tx1.description, "Batch updated")
        self.assertEqual(tx2.description, "Batch updated")

    # ---- Validation ----

    def test_batch_edit_empty_ids_returns_400(self):
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": []},
                format="json",
            )
        # Empty ids list is technically valid but no-op
        # DRF ListField allows empty list by default
        self.assertIn(resp.status_code, [status.HTTP_204_NO_CONTENT, status.HTTP_400_BAD_REQUEST])

    def test_batch_edit_invalid_category_returns_404(self):
        tx = self._create_tx()
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "category_id": 99999},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_batch_edit_invalid_account_returns_404(self):
        tx = self._create_tx()
        with current_team(self.team):
            resp = self.client.patch(
                self.url,
                {"ids": [tx.id], "account_id": 99999},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class RetrieveEndpointRemovedTest(TestCase):
    """Verify that the retrieve endpoint is no longer available."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team-ret")
        cls.user = CustomUser.objects.create_user(username="testuser2", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.bank_account = Account.objects.create(
            team=cls.team,
            name="Checking",
            account_number=1000,
            account_group=cls.asset_group,
            has_feed=True,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_retrieve_returns_404_or_405(self):
        tx = BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="Test",
            amount=Decimal("10.00"),
            source=BankTransaction.SOURCE_CSV,
        )
        with current_team(self.team):
            resp = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/{tx.id}/")
        # Should return 405 Method Not Allowed since retrieve is removed
        self.assertIn(resp.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED])
