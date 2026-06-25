"""
Tests for the ``search`` query parameter on BankFeedViewSet.list.
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
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class BankFeedSearchTest(TestCase):
    """Tests for searching the bank feed by payee, description, category, and amount."""

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

        cls.checking = Account.objects.create(
            team=cls.team, name="Checking", account_group=cls.asset_group, has_feed=True
        )
        cls.savings = Account.objects.create(
            team=cls.team, name="Savings", account_group=cls.asset_group, has_feed=True
        )
        cls.groceries = Account.objects.create(
            team=cls.team, name="Groceries", account_group=cls.expense_group
        )

        # An uncategorized transaction on Checking with a merchant + description.
        cls.tx_whole_foods = BankTransaction.objects.create(
            team=cls.team,
            account=cls.checking,
            posted_date=date.today(),
            description="WHOLEFDS market purchase",
            merchant_name="Whole Foods",
            amount=Decimal("42.50"),
            source=BankTransaction.SOURCE_CSV,
        )
        # A transaction on Savings (different account) for the cross-account test.
        cls.tx_starbucks = BankTransaction.objects.create(
            team=cls.team,
            account=cls.savings,
            posted_date=date.today(),
            description="Coffee run",
            merchant_name="Starbucks",
            amount=Decimal("7.25"),
            source=BankTransaction.SOURCE_CSV,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _search(self, term, account=None):
        params = {"search": term}
        if account is not None:
            params["account"] = account
        return self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/", params)

    def _categorize(self, tx, category):
        """Categorize a transaction so its journal entry links to a category account."""
        return self.client.post(
            f"/a/{self.team.slug}/bankfeed/api/feed/categorize/",
            {"rows": [{"id": tx.id}], "category_id": category.id},
            format="json",
        )

    def test_search_by_merchant_name(self):
        with current_team(self.team):
            response = self._search("Whole Foods")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["id"], self.tx_whole_foods.id)

    def test_search_by_description(self):
        with current_team(self.team):
            response = self._search("Coffee")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["id"], self.tx_starbucks.id)

    def test_search_by_category_name(self):
        """Searching by the category (account name via journal entry) matches."""
        with current_team(self.team):
            resp = self._categorize(self.tx_whole_foods, self.groceries)
            self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

            response = self._search("Groceries")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["id"], self.tx_whole_foods.id)

    def test_search_by_amount(self):
        with current_team(self.team):
            response = self._search("42.50")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["id"], self.tx_whole_foods.id)

    def test_search_by_amount_matches_opposite_sign(self):
        """Inflow amounts are stored negative; searching a bare amount matches either sign."""
        with current_team(self.team):
            BankTransaction.objects.create(
                team=self.team,
                account=self.checking,
                posted_date=date.today(),
                description="Refund",
                amount=Decimal("-99.99"),
                source=BankTransaction.SOURCE_CSV,
            )
            response = self._search("99.99")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["description"], "Refund")

    def test_search_no_results(self):
        with current_team(self.team):
            response = self._search("nonexistent merchant xyz")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 0)
            self.assertEqual(response.data["results"], [])

    def test_search_across_all_accounts(self):
        """Without an account filter, search spans transactions in every account."""
        with current_team(self.team):
            response = self._search("a")  # substring present in both descriptions/merchants

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            ids = {r["id"] for r in response.data["results"]}
            self.assertIn(self.tx_whole_foods.id, ids)
            self.assertIn(self.tx_starbucks.id, ids)

    def test_search_scoped_to_account(self):
        """Combining account + search restricts results to that account."""
        with current_team(self.team):
            response = self._search("a", account=self.savings.id)

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            ids = {r["id"] for r in response.data["results"]}
            self.assertIn(self.tx_starbucks.id, ids)
            self.assertNotIn(self.tx_whole_foods.id, ids)
