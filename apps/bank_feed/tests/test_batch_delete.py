"""
Tests for BankFeedViewSet.batch_delete endpoint.
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
from apps.books.context import current_book
from apps.journal.models import JournalEntry
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class BatchDeleteTest(TestCase):
    """Tests for BankFeedViewSet.batch_delete endpoint."""

    @classmethod
    def setUpTestData(cls):
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
        cls.expense_category = Account.objects.create(
            book=cls.book,
            name="Groceries",
            account_group=cls.expense_group,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/batch_delete/"

    def _create_archived_tx(self, **kwargs):
        defaults = dict(
            book=self.book,
            account=self.bank_account,
            posted_date=date.today(),
            description="Test tx",
            amount=Decimal("50.00"),
            source=BankTransaction.SOURCE_CSV,
            is_archived=True,
        )
        defaults.update(kwargs)
        return BankTransaction.objects.create(**defaults)

    def test_delete_archived_transactions(self):
        tx1 = self._create_archived_tx()
        tx2 = self._create_archived_tx()
        with current_book(self.book):
            resp = self.client.post(self.url, {"ids": [tx1.id, tx2.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BankTransaction.objects.filter(id__in=[tx1.id, tx2.id]).exists())

    def test_delete_also_removes_journal_entry(self):
        je = JournalEntry.objects.create(
            book=self.book,
            description="Test entry",
            entry_date=date.today(),
        )
        tx = self._create_archived_tx(journal_entry=je)
        with current_book(self.book):
            resp = self.client.post(self.url, {"ids": [tx.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BankTransaction.objects.filter(id=tx.id).exists())
        self.assertFalse(JournalEntry.objects.filter(id=je.id).exists())

    def test_cannot_delete_non_archived_transactions(self):
        tx = BankTransaction.objects.create(
            book=self.book,
            account=self.bank_account,
            posted_date=date.today(),
            description="Active tx",
            amount=Decimal("25.00"),
            source=BankTransaction.SOURCE_CSV,
            is_archived=False,
        )
        with current_book(self.book):
            resp = self.client.post(self.url, {"ids": [tx.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        # Non-archived transaction should not be deleted
        self.assertTrue(BankTransaction.objects.filter(id=tx.id).exists())

    def test_cannot_delete_other_teams_transactions(self):
        other_team = Team.objects.create(name="Other Team", slug="other-team")
        other_book = other_team.default_book
        other_asset_group = AccountGroup.objects.create(
            book=other_book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        other_account = Account.objects.create(
            book=other_book,
            name="Checking",
            account_group=other_asset_group,
            has_feed=True,
        )
        other_tx = BankTransaction.objects.create(
            book=other_book,
            account=other_account,
            posted_date=date.today(),
            description="Other team tx",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
            is_archived=True,
        )
        with current_book(self.book):
            resp = self.client.post(self.url, {"ids": [other_tx.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(BankTransaction.objects.filter(id=other_tx.id).exists())

    def test_requires_authentication(self):
        tx = self._create_archived_tx()
        unauth_client = APIClient()
        resp = unauth_client.post(self.url, {"ids": [tx.id]}, format="json")
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        self.assertTrue(BankTransaction.objects.filter(id=tx.id).exists())
