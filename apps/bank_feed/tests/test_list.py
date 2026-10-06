"""
Tests for BankFeedViewSet.list endpoint.
"""

from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
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
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class BankFeedViewSetListTest(TestCase):
    """Tests for BankFeedViewSet.list endpoint."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        # Team and user
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        # Other team for isolation tests
        cls.other_team = Team.objects.create(name="Other Team", slug="other-team")
        cls.other_book = cls.other_team.default_book
        cls.other_user = CustomUser.objects.create_user(username="otheruser", password="pass")
        cls.other_team.members.add(cls.other_user, through_defaults={"role": ROLE_ADMIN})

        # Account groups
        cls.asset_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            book=cls.book, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )

        # Other team's account group
        cls.other_asset_group = AccountGroup.objects.create(
            book=cls.other_book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )

        # Accounts
        cls.bank_account = Account.objects.create(
            book=cls.book,
            name="Checking",
            account_group=cls.asset_group,
            has_feed=True,
        )
        cls.bank_account2 = Account.objects.create(
            book=cls.book,
            name="Savings",
            account_group=cls.asset_group,
            has_feed=True,
        )
        cls.category_account = Account.objects.create(
            book=cls.book,
            name="Groceries",
            account_group=cls.expense_group,
        )

        # Other team's account
        cls.other_bank_account = Account.objects.create(
            book=cls.other_book,
            name="Other Checking",
            account_group=cls.other_asset_group,
            has_feed=True,
        )

        # Sample bank transactions
        cls.bank_tx1 = BankTransaction.objects.create(
            book=cls.book,
            account=cls.bank_account,
            posted_date=date.today(),
            description="Test transaction 1",
            amount=Decimal("100.00"),
            source=BankTransaction.SOURCE_CSV,
        )
        cls.bank_tx2 = BankTransaction.objects.create(
            book=cls.book,
            account=cls.bank_account2,
            posted_date=date.today(),
            description="Test transaction 2",
            amount=Decimal("-50.00"),
            source=BankTransaction.SOURCE_CSV,
        )

        # Other team's transaction
        cls.other_bank_tx = BankTransaction.objects.create(
            book=cls.other_book,
            account=cls.other_bank_account,
            posted_date=date.today(),
            description="Other team transaction",
            amount=Decimal("200.00"),
            source=BankTransaction.SOURCE_CSV,
        )

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_list_returns_all_team_transactions(self):
        """Test that list returns all bank transactions for the team."""
        with current_book(self.book):
            response = self.client.get(f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 2)
            descriptions = [r["description"] for r in response.data["results"]]
            self.assertIn("Test transaction 1", descriptions)
            self.assertIn("Test transaction 2", descriptions)

    def test_list_filters_by_account(self):
        """Test that list filters by account when account parameter is provided."""
        with current_book(self.book):
            response = self.client.get(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/",
                {"account": self.bank_account.id},
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["description"], "Test transaction 1")

    def test_list_returns_empty_for_no_transactions(self):
        """Test that list returns empty results when no transactions exist."""
        # Create a new team with no transactions
        empty_team = Team.objects.create(name="Empty Team", slug="empty-team")
        empty_book = empty_team.default_book
        empty_user = CustomUser.objects.create_user(username="emptyuser", password="pass")
        empty_team.members.add(empty_user, through_defaults={"role": ROLE_ADMIN})

        self.client.force_authenticate(user=empty_user)
        with current_book(empty_book):
            response = self.client.get(f"/a/{empty_team.slug}/{empty_book.slug}/bankfeed/api/feed/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 0)
            self.assertEqual(response.data["results"], [])

    def test_list_without_authentication_denied(self):
        """Test that the list endpoint rejects unauthenticated requests.

        TeamModelAccessPermissions enforces authenticated team membership at the
        view level, so anonymous requests must not see any team data.
        """
        self.client.force_authenticate(user=None)
        response = self.client.get(f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_denied_for_non_member(self):
        """Users who are not members of the team must not see its feed."""
        outsider = CustomUser.objects.create_user(username="outsider", password="pass")
        self.client.force_authenticate(user=outsider)
        response = self.client.get(f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_only_shows_own_team_transactions(self):
        """Test that users can only see their own team's transactions."""
        with current_book(self.book):
            response = self.client.get(f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Should not include other team's transaction
            descriptions = [r["description"] for r in response.data["results"]]
            self.assertNotIn("Other team transaction", descriptions)


class BankFeedListUncategorizedAndQueryCountTest(TestCase):
    """`?uncategorized=1` (categorize mode's queue) and a query count that does not grow per row."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Queue Team", slug="queue-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="queueuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        asset_group = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        expense_group = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.bank = Account.objects.create(book=cls.book, name="Chequing", account_group=asset_group, has_feed=True)
        cls.expenses = [
            Account.objects.create(book=cls.book, name=f"Expense {i}", account_group=expense_group) for i in range(3)
        ]
        cls.waiting = BankTransaction.objects.create(
            book=cls.book,
            account=cls.bank,
            posted_date=date(2026, 1, 5),
            description="Waiting",
            amount=Decimal("12.00"),
            source=BankTransaction.SOURCE_CSV,
        )
        cls.archived = BankTransaction.objects.create(
            book=cls.book,
            account=cls.bank,
            posted_date=date(2026, 1, 6),
            description="Archived",
            amount=Decimal("13.00"),
            source=BankTransaction.SOURCE_CSV,
            is_archived=True,
        )
        cls.categorized = cls._categorized("Filed", [(cls.expenses[0], Decimal("14.00"))])
        cls.split = cls._categorized("Split", [(cls.expenses[1], Decimal("10.00")), (cls.expenses[2], Decimal("5.00"))])

    @classmethod
    def _categorized(cls, description, legs, day=7):
        total = sum(amount for _, amount in legs)
        entry = JournalEntry.objects.create(book=cls.book, entry_date=date(2026, 1, day), description=description)
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=cls.bank, cr_amount=total)
        for account, amount in legs:
            JournalLine.objects.create(book=cls.book, journal_entry=entry, account=account, dr_amount=amount)
        return BankTransaction.objects.create(
            book=cls.book,
            account=cls.bank,
            posted_date=date(2026, 1, day),
            description=description,
            amount=total,
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/"

    def test_uncategorized_returns_only_rows_waiting_to_be_categorized(self):
        response = self.client.get(self.url, {"uncategorized": "1"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Not the categorized row, not the split (category null, but filed), not the archived one.
        self.assertEqual([r["id"] for r in response.data["results"]], [str(self.waiting.id)])

    def test_without_the_flag_every_row_is_listed(self):
        response = self.client.get(self.url)

        self.assertEqual(response.data["count"], 4)

    def test_query_count_does_not_grow_with_rows(self):
        def queries_for_list():
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(self.url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            return len(ctx.captured_queries)

        before = queries_for_list()
        for day in range(10, 20):
            self._categorized(f"More {day}", [(self.expenses[day % 3], Decimal("1.00"))], day=day)
        # Each row serializes its account and category with their group; loading
        # those per row cost a query each (about 250 per 200-row page).
        self.assertEqual(queries_for_list(), before)
