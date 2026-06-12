"""
Tests for the bank feed category_suggestions endpoint.
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


class CategorySuggestionsTest(TestCase):
    """Tests for BankFeedViewSet.category_suggestions."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        asset_group = AccountGroup.objects.create(team=cls.team, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        expense_group = AccountGroup.objects.create(team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking", account_group=asset_group, has_feed=True
        )
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=expense_group)
        cls.dining = Account.objects.create(team=cls.team, name="Dining", account_group=expense_group)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _categorized_tx(self, merchant, category, posted_date):
        entry = JournalEntry.objects.create(
            team=self.team,
            entry_date=posted_date,
            description=merchant,
            status=JournalEntry.STATUS_POSTED,
        )
        JournalLine.objects.create(
            journal_entry=entry,
            team=self.team,
            account=self.bank_account,
            dr_amount=Decimal("0"),
            cr_amount=Decimal("10"),
        )
        JournalLine.objects.create(
            journal_entry=entry,
            team=self.team,
            account=category,
            dr_amount=Decimal("10"),
            cr_amount=Decimal("0"),
        )
        return BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=posted_date,
            description=merchant,
            merchant_name=merchant,
            amount=Decimal("10.00"),
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )

    def test_returns_most_recent_category_per_merchant(self):
        """The newest categorization wins when a merchant was categorized differently over time."""
        self._categorized_tx("Starbucks", self.groceries, date.today() - timedelta(days=30))
        self._categorized_tx("Starbucks", self.dining, date.today())

        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/category_suggestions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        suggestions = {s["merchant_name"]: s for s in response.data}
        self.assertEqual(suggestions["Starbucks"]["category_id"], self.dining.id)
        self.assertEqual(suggestions["Starbucks"]["category_name"], "Dining")

    def test_uncategorized_and_unnamed_transactions_excluded(self):
        """Transactions without a journal entry or merchant name produce no suggestions."""
        BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=date.today(),
            description="No merchant",
            amount=Decimal("5.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/category_suggestions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_denied_for_anonymous(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/category_suggestions/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
