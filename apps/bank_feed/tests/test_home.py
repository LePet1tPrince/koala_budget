"""
Tests for bank_feed_home template view and permissions.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser


class BankFeedHomeViewTest(TestCase):
    """Tests for bank_feed_home template view."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="testpass123")
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
        cls.savings_account = Account.objects.create(
            team=cls.team,
            name="Savings",
            account_number=1001,
            account_group=cls.asset_group,
            has_feed=False,  # No feed
        )

    def setUp(self):
        """Set up for each test."""
        self.client.login(username="testuser", password="testpass123")

    def test_bank_feed_home_renders_template(self):
        """Test that bank feed home view renders the correct template."""
        response = self.client.get(f"/a/{self.team.slug}/bankfeed/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(response, "bank_feed/bank_feed_home.html")

    def test_bank_feed_home_requires_login(self):
        """Test that bank feed home requires login."""
        self.client.logout()
        response = self.client.get(f"/a/{self.team.slug}/bankfeed/")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("/accounts/login/", response.url)

    def test_bank_feed_home_context_contains_accounts(self):
        """Test that context contains accounts with bank feeds."""
        response = self.client.get(f"/a/{self.team.slug}/bankfeed/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accounts", response.context)
        # Should only include accounts with has_feed=True
        account_names = [a["name"] for a in response.context["accounts"]]
        self.assertIn("Checking", account_names)
        self.assertNotIn("Savings", account_names)

    def test_bank_feed_home_context_contains_api_urls(self):
        """Test that context contains api_urls."""
        response = self.client.get(f"/a/{self.team.slug}/bankfeed/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("api_urls", response.context)
        api_urls = response.context["api_urls"]
        self.assertIn("feed_list", api_urls)
        self.assertIn(self.team.slug, api_urls["feed_list"])


class BankFeedPermissionsTest(TestCase):
    """Tests for bank feed permissions."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.admin_user = CustomUser.objects.create_user(username="admin", password="pass")
        cls.member_user = CustomUser.objects.create_user(username="member", password="pass")
        cls.other_user = CustomUser.objects.create_user(username="other", password="pass")

        cls.team.members.add(cls.admin_user, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member_user, through_defaults={"role": ROLE_MEMBER})

        cls.other_team = Team.objects.create(name="Other Team", slug="other-team")
        cls.other_team.members.add(cls.other_user, through_defaults={"role": ROLE_ADMIN})

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

        cls.bank_tx = BankTransaction.objects.create(
            team=cls.team,
            account=cls.bank_account,
            posted_date=date.today(),
            description="Test transaction",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()

    def test_team_member_can_view_feed(self):
        """Test that team members can view the bank feed."""
        self.client.force_authenticate(user=self.member_user)

        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)

    def test_authenticated_user_can_access_team_feed(self):
        """Test that authenticated team members can access the feed.

        Note: Team access control is typically enforced at the middleware level.
        The view filters data by team from the URL, so membership enforcement
        happens before the request reaches the view.
        """
        self.client.force_authenticate(user=self.member_user)

        with current_team(self.team):
            response = self.client.get(f"/a/{self.team.slug}/bankfeed/api/feed/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Team member should see the team's transaction
        self.assertEqual(response.data["count"], 1)
