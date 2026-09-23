"""
Tests for journal app.
Tests models, views, serializers, and API endpoints.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
    Payee,
)
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

from .models import JournalEntry, JournalLine


class JournalEntryModelTest(TestCase):
    """Tests for JournalEntry model."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)
        cls.expense_account = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)
        cls.payee = Payee.objects.create(team=cls.team, name="Test Store")

    def test_create_journal_entry(self):
        """Test creating a journal entry."""
        entry = JournalEntry.objects.create(
            team=self.team,
            entry_date=date(2025, 12, 17),
            description="Test entry",
            payee=self.payee,
        )
        self.assertEqual(entry.description, "Test entry")
        self.assertEqual(entry.payee, self.payee)
        self.assertEqual(entry.status, JournalEntry.STATUS_DRAFT)
        self.assertEqual(entry.source, JournalEntry.SOURCE_MANUAL)

    def test_journal_entry_ordering(self):
        """Test that journal entries are ordered by entry_date descending."""
        with current_team(self.team):
            entry1 = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 15), description="First")
            entry2 = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Second")
            entries = list(JournalEntry.for_team.all())
            self.assertEqual(entries[0], entry2)
            self.assertEqual(entries[1], entry1)

    def test_journal_entry_str(self):
        """Test string representation of journal entry."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test entry")
        self.assertIn("JE-", str(entry))
        self.assertIn("2025-12-17", str(entry))
        self.assertIn("Test entry", str(entry))

    def test_total_debits_property(self):
        """Test total_debits property."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
        )
        self.assertEqual(entry.total_debits, Decimal("100.00"))

    def test_total_credits_property(self):
        """Test total_credits property."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
        )
        self.assertEqual(entry.total_credits, Decimal("100.00"))

    def test_is_balanced_property(self):
        """Test is_balanced property."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test")
        # Unbalanced entry
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
        )
        self.assertFalse(entry.is_balanced)

        # Add balancing line
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
        )
        self.assertTrue(entry.is_balanced)

    def test_clean_validation_balanced(self):
        """Test clean method validates balanced entries."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
        )
        # Should not raise
        entry.clean()

    def test_clean_validation_unbalanced(self):
        """Test clean method raises error for unbalanced entries."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("50.00")
        )
        with self.assertRaises(ValidationError):
            entry.clean()


class JournalLineModelTest(TestCase):
    """Tests for JournalLine model."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)
        cls.entry = JournalEntry.objects.create(team=cls.team, entry_date=date(2025, 12, 17), description="Test")

    def test_create_journal_line(self):
        """Test creating a journal line."""
        line = JournalLine.objects.create(
            team=self.team,
            journal_entry=self.entry,
            account=self.bank_account,
            dr_amount=Decimal("100.00"),
        )
        self.assertEqual(line.account, self.bank_account)
        self.assertEqual(line.dr_amount, Decimal("100.00"))
        self.assertEqual(line.cr_amount, Decimal("0.00"))
        self.assertFalse(line.is_cleared)
        self.assertFalse(line.is_reconciled)

    def test_journal_line_str(self):
        """Test string representation of journal line."""
        line = JournalLine.objects.create(
            team=self.team,
            journal_entry=self.entry,
            account=self.bank_account,
            dr_amount=Decimal("100.00"),
        )
        self.assertIn("Checking", str(line))
        self.assertIn("DR", str(line))
        self.assertIn("100", str(line))

    def test_amount_property_debit(self):
        """Test amount property returns debit amount."""
        line = JournalLine.objects.create(
            team=self.team,
            journal_entry=self.entry,
            account=self.bank_account,
            dr_amount=Decimal("100.00"),
        )
        self.assertEqual(line.amount, Decimal("100.00"))

    def test_amount_property_credit(self):
        """Test amount property returns credit amount."""
        line = JournalLine.objects.create(
            team=self.team,
            journal_entry=self.entry,
            account=self.bank_account,
            cr_amount=Decimal("100.00"),
        )
        self.assertEqual(line.amount, Decimal("100.00"))

    def test_clean_validation_both_amounts(self):
        """Test clean method raises error when both debit and credit are set."""
        line = JournalLine(
            team=self.team,
            journal_entry=self.entry,
            account=self.bank_account,
            dr_amount=Decimal("100.00"),
            cr_amount=Decimal("50.00"),
        )
        with self.assertRaises(ValidationError):
            line.clean()

    def test_clean_validation_no_amounts(self):
        """Test clean method raises error when neither debit nor credit is set."""
        line = JournalLine(
            team=self.team,
            journal_entry=self.entry,
            account=self.bank_account,
            dr_amount=Decimal("0.00"),
            cr_amount=Decimal("0.00"),
        )
        with self.assertRaises(ValidationError):
            line.clean()

    def test_clean_validation_negative_amounts(self):
        """Test clean method raises error for negative amounts."""
        line = JournalLine(
            team=self.team,
            journal_entry=self.entry,
            account=self.bank_account,
            dr_amount=Decimal("-100.00"),
        )
        with self.assertRaises(ValidationError):
            line.clean()


class SimpleLineAPITest(TestCase):
    """Test the simplified line API endpoint."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        # Create team
        cls.team = Team.objects.create(name="Test Team", slug="test-team")

        # Create user and add to team
        cls.user = CustomUser.objects.create_user(username="testuser", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        # Create account groups
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME)

        # Create accounts
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking Account", account_group=cls.asset_group)
        cls.groceries_account = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)
        cls.salary_account = Account.objects.create(team=cls.team, name="Salary", account_group=cls.income_group)

        # Create payee
        cls.payee = Payee.objects.create(team=cls.team, name="Test Store")

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_expense_transaction(self):
        """Test creating a simple expense transaction."""
        with current_team(self.team):
            data = {
                "date": "2025-12-17",
                "account": self.bank_account.pk,
                "category": self.groceries_account.pk,
                "inflow": "0.00",
                "outflow": "50.00",
                "description": "Bought groceries",
                "payee": self.payee.id,
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/lines/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(JournalEntry.objects.count(), 1)

            # Verify journal entry was created correctly
            journal_entry = JournalEntry.objects.first()
            self.assertEqual(journal_entry.description, "Bought groceries")
            self.assertEqual(journal_entry.payee, self.payee)
            self.assertEqual(journal_entry.status, JournalEntry.STATUS_DRAFT)

            # Verify journal lines
            self.assertEqual(journal_entry.lines.count(), 2)
            self.assertTrue(journal_entry.is_balanced)

            # Check that expense is debited and bank is credited
            expense_line = journal_entry.lines.get(account=self.groceries_account)
            bank_line = journal_entry.lines.get(account=self.bank_account)

            self.assertEqual(expense_line.dr_amount, Decimal("50.00"))
            self.assertEqual(expense_line.cr_amount, Decimal("0.00"))
            self.assertEqual(bank_line.dr_amount, Decimal("0.00"))
            self.assertEqual(bank_line.cr_amount, Decimal("50.00"))

    def test_create_income_transaction(self):
        """Test creating a simple income transaction."""
        with current_team(self.team):
            data = {
                "date": "2025-12-17",
                "account": self.bank_account.pk,
                "category": self.salary_account.pk,
                "inflow": "1000.00",
                "outflow": "0.00",
                "description": "Monthly salary",
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/lines/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

            # Verify journal entry
            journal_entry = JournalEntry.objects.first()
            self.assertEqual(journal_entry.description, "Monthly salary")

            # Check that bank is debited and income is credited
            bank_line = journal_entry.lines.get(account=self.bank_account)
            income_line = journal_entry.lines.get(account=self.salary_account)

            self.assertEqual(bank_line.dr_amount, Decimal("1000.00"))
            self.assertEqual(bank_line.cr_amount, Decimal("0.00"))
            self.assertEqual(income_line.dr_amount, Decimal("0.00"))
            self.assertEqual(income_line.cr_amount, Decimal("1000.00"))

    def test_create_transaction_with_no_category(self):
        """Test creating a transaction with no category returns 400."""
        with current_team(self.team):
            data = {
                "date": "2025-12-17",
                "account": self.bank_account.pk,
                "category": None,
                "inflow": "1000.00",
                "outflow": "0.00",
                "description": "Monthly salary",
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/lines/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_lines(self):
        """Test listing simple lines."""
        with current_team(self.team):
            # Create a transaction first
            journal_entry = JournalEntry.objects.create(
                team=self.team, entry_date="2025-12-17", description="Test transaction"
            )

            JournalLine.objects.create(
                team=self.team,
                journal_entry=journal_entry,
                account=self.groceries_account,
                dr_amount=Decimal("50.00"),
                cr_amount=Decimal("0.00"),
            )
            JournalLine.objects.create(
                team=self.team,
                journal_entry=journal_entry,
                account=self.bank_account,
                dr_amount=Decimal("0.00"),
                cr_amount=Decimal("50.00"),
            )

            response = self.client.get(f"/a/{self.team.slug}/journal/api/lines/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Response is paginated, so check the results key
            self.assertEqual(len(response.data["results"]), 2)

    def test_update_line(self):
        """Test updating a simple line."""
        with current_team(self.team):
            # Create a transaction
            journal_entry = JournalEntry.objects.create(
                team=self.team, entry_date="2025-12-17", description="Old description"
            )

            bank_line = JournalLine.objects.create(
                team=self.team,
                journal_entry=journal_entry,
                account=self.bank_account,
                dr_amount=Decimal("0.00"),
                cr_amount=Decimal("50.00"),
            )
            JournalLine.objects.create(
                team=self.team,
                journal_entry=journal_entry,
                account=self.groceries_account,
                dr_amount=Decimal("50.00"),
                cr_amount=Decimal("0.00"),
            )

            # Update the transaction
            data = {
                "date": "2025-12-18",
                "account": self.bank_account.pk,
                "category": self.groceries_account.pk,
                "inflow": "0.00",
                "outflow": "75.00",
                "description": "Updated description",
            }

            response = self.client.put(f"/a/{self.team.slug}/journal/api/lines/{bank_line.id}/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Verify the update
            journal_entry.refresh_from_db()
            self.assertEqual(journal_entry.description, "Updated description")
            self.assertEqual(str(journal_entry.entry_date), "2025-12-18")

            # Verify lines were updated
            bank_line.refresh_from_db()
            self.assertEqual(bank_line.cr_amount, Decimal("75.00"))

    def test_delete_line(self):
        """Test deleting a line deletes the entire journal entry."""
        with current_team(self.team):
            # Create a transaction
            journal_entry = JournalEntry.objects.create(
                team=self.team, entry_date="2025-12-17", description="To be deleted"
            )

            bank_line = JournalLine.objects.create(
                team=self.team,
                journal_entry=journal_entry,
                account=self.bank_account,
                dr_amount=Decimal("0.00"),
                cr_amount=Decimal("50.00"),
            )
            JournalLine.objects.create(
                team=self.team,
                journal_entry=journal_entry,
                account=self.groceries_account,
                dr_amount=Decimal("50.00"),
                cr_amount=Decimal("0.00"),
            )

            response = self.client.delete(f"/a/{self.team.slug}/journal/api/lines/{bank_line.id}/")

            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            self.assertEqual(JournalEntry.objects.count(), 0)
            self.assertEqual(JournalLine.objects.count(), 0)

    def test_validation_both_inflow_outflow(self):
        """Test validation error when both inflow and outflow are provided."""
        with current_team(self.team):
            data = {
                "date": "2025-12-17",
                "account": self.bank_account.pk,
                "category": self.groceries_account.pk,
                "inflow": "50.00",
                "outflow": "50.00",
                "description": "Invalid",
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/lines/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validation_no_inflow_outflow(self):
        """Test validation error when neither inflow nor outflow is provided."""
        with current_team(self.team):
            data = {
                "date": "2025-12-17",
                "account": self.bank_account.pk,
                "category": self.groceries_account.pk,
                "inflow": "0.00",
                "outflow": "0.00",
                "description": "Invalid",
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/lines/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class JournalEntryAPITest(TestCase):
    """Test the JournalEntry API endpoint."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        # Create account groups
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )

        # Create accounts
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)
        cls.expense_account = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)
        cls.payee = Payee.objects.create(team=cls.team, name="Test Store")

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_journal_entry(self):
        """Test creating a journal entry via API."""
        with current_team(self.team):
            data = {
                "entry_date": "2025-12-17",
                "description": "Test entry",
                "payee": self.payee.id,
                "lines": [
                    {"account": self.bank_account.pk, "dr_amount": "100.00", "cr_amount": "0.00"},
                    {"account": self.expense_account.pk, "dr_amount": "0.00", "cr_amount": "100.00"},
                ],
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(JournalEntry.objects.count(), 1)

            entry = JournalEntry.objects.first()
            self.assertEqual(entry.description, "Test entry")
            self.assertEqual(entry.lines.count(), 2)
            self.assertTrue(entry.is_balanced)

    def test_list_journal_entries(self):
        """Test listing journal entries."""
        with current_team(self.team):
            entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test entry")
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
            )

            response = self.client.get(f"/a/{self.team.slug}/journal/api/journal-entries/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data["results"]), 1)

    def test_retrieve_journal_entry(self):
        """Test retrieving a single journal entry."""
        with current_team(self.team):
            entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test entry")
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
            )

            response = self.client.get(f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["description"], "Test entry")
            self.assertEqual(len(response.data["lines"]), 2)

    def test_update_journal_entry(self):
        """Test updating a journal entry."""
        with current_team(self.team):
            entry = JournalEntry.objects.create(
                team=self.team, entry_date=date(2025, 12, 17), description="Old description"
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
            )

            data = {
                "entry_date": "2025-12-18",
                "description": "Updated description",
                "lines": [
                    {"account": self.bank_account.pk, "dr_amount": "150.00", "cr_amount": "0.00"},
                    {"account": self.expense_account.pk, "dr_amount": "0.00", "cr_amount": "150.00"},
                ],
            }

            response = self.client.put(
                f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/", data, format="json"
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            entry.refresh_from_db()
            self.assertEqual(entry.description, "Updated description")
            self.assertEqual(entry.total_debits, Decimal("150.00"))

    def test_delete_journal_entry(self):
        """Test deleting a journal entry."""
        with current_team(self.team):
            entry = JournalEntry.objects.create(
                team=self.team, entry_date=date(2025, 12, 17), description="To be deleted"
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
            )

            response = self.client.delete(f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/")

            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            self.assertEqual(JournalEntry.objects.count(), 0)

    def test_post_entry_action(self):
        """Test posting a draft journal entry."""
        with current_team(self.team):
            entry = JournalEntry.objects.create(
                team=self.team,
                entry_date=date(2025, 12, 17),
                description="Test entry",
                status=JournalEntry.STATUS_DRAFT,
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
            )

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/post_entry/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            entry.refresh_from_db()
            self.assertEqual(entry.status, JournalEntry.STATUS_POSTED)

    def test_post_entry_action_not_draft(self):
        """Test posting a non-draft entry returns error."""
        with current_team(self.team):
            entry = JournalEntry.objects.create(
                team=self.team,
                entry_date=date(2025, 12, 17),
                description="Test entry",
                status=JournalEntry.STATUS_POSTED,
            )

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/post_entry/")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_entry_action_unbalanced(self):
        """Test posting an unbalanced entry returns error."""
        with current_team(self.team):
            entry = JournalEntry.objects.create(
                team=self.team,
                entry_date=date(2025, 12, 17),
                description="Test entry",
                status=JournalEntry.STATUS_DRAFT,
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
            )

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/post_entry/")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_void_entry_action(self):
        """Test voiding a posted journal entry."""
        with current_team(self.team):
            entry = JournalEntry.objects.create(
                team=self.team,
                entry_date=date(2025, 12, 17),
                description="Test entry",
                status=JournalEntry.STATUS_POSTED,
            )

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/void_entry/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            entry.refresh_from_db()
            self.assertEqual(entry.status, JournalEntry.STATUS_VOID)

    def test_void_entry_action_not_posted(self):
        """Test voiding a non-posted entry returns error."""
        with current_team(self.team):
            entry = JournalEntry.objects.create(
                team=self.team,
                entry_date=date(2025, 12, 17),
                description="Test entry",
                status=JournalEntry.STATUS_DRAFT,
            )

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/void_entry/")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validation_unbalanced_entry(self):
        """Test validation error for unbalanced entry."""
        with current_team(self.team):
            data = {
                "entry_date": "2025-12-17",
                "description": "Unbalanced entry",
                "lines": [
                    {"account": self.bank_account.pk, "dr_amount": "100.00", "cr_amount": "0.00"},
                    {"account": self.expense_account.pk, "dr_amount": "0.00", "cr_amount": "50.00"},
                ],
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validation_less_than_two_lines(self):
        """Test validation error for entry with less than 2 lines."""
        with current_team(self.team):
            data = {
                "entry_date": "2025-12-17",
                "description": "Single line entry",
                "lines": [
                    {"account": self.bank_account.pk, "dr_amount": "100.00", "cr_amount": "0.00"},
                ],
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TransactionAPITest(TestCase):
    """Test the Transactions list API endpoint's pagination."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)
        cls.expense_account = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)

        with current_team(cls.team):
            for i in range(150):
                entry = JournalEntry.objects.create(
                    team=cls.team, entry_date=date(2025, 1, 1) + timedelta(days=i), description=f"Entry {i}"
                )
                JournalLine.objects.create(
                    team=cls.team, journal_entry=entry, account=cls.bank_account, dr_amount=Decimal("10.00")
                )
                JournalLine.objects.create(
                    team=cls.team, journal_entry=entry, account=cls.expense_account, cr_amount=Decimal("10.00")
                )

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_page_size_exceeds_old_default(self):
        """The transactions endpoint should paginate above DRF's global default of 100."""
        response = self.client.get(f"/a/{self.team.slug}/journal/api/transactions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 150)
        self.assertEqual(len(response.data["results"]), 150)
        self.assertIsNone(response.data["next"])

    def test_all_entries_reachable_by_following_pagination(self):
        """Every entry, including the oldest, must be reachable via the paginated results."""
        response = self.client.get(f"/a/{self.team.slug}/journal/api/transactions/")

        descriptions = {row["description"] for row in response.data["results"]}
        self.assertIn("Entry 0", descriptions)
        self.assertIn("Entry 149", descriptions)


class TransactionSearchFilterAPITest(TestCase):
    """Test server-side search and date-range filtering on the Transactions endpoint."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)
        cls.expense_account = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)
        cls.coffee_account = Account.objects.create(team=cls.team, name="Coffee Shops", account_group=cls.expense_group)
        cls.old_payee = Payee.objects.create(team=cls.team, name="Very Old Payee Inc")

        with current_team(cls.team):
            # 250 recent, generic entries -- newest-first pagination puts the
            # oldest 50 of these on page 2 (page size 200).
            for i in range(250):
                entry = JournalEntry.objects.create(
                    team=cls.team,
                    entry_date=date(2024, 1, 1) + timedelta(days=i),
                    description=f"Entry {i}",
                )
                JournalLine.objects.create(
                    team=cls.team, journal_entry=entry, account=cls.bank_account, dr_amount=Decimal("10.00")
                )
                JournalLine.objects.create(
                    team=cls.team, journal_entry=entry, account=cls.expense_account, cr_amount=Decimal("10.00")
                )

            # A single, much older, distinctive entry that only shows up on
            # page 2 of the unfiltered newest-first list.
            cls.old_entry = JournalEntry.objects.create(
                team=cls.team, entry_date=date(2020, 1, 1), payee=cls.old_payee, description="Ancient purchase"
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.old_entry, account=cls.coffee_account, dr_amount=Decimal("42.42")
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.old_entry, account=cls.bank_account, cr_amount=Decimal("42.42")
            )

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_search_finds_entry_beyond_first_page_by_payee(self):
        """A payee-name search must reach entries outside the first page of results."""
        response = self.client.get(f"/a/{self.team.slug}/journal/api/transactions/", {"search": "Very Old"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.old_entry.pk)

    def test_search_matches_account_name(self):
        """Search should match against either side's account name."""
        response = self.client.get(f"/a/{self.team.slug}/journal/api/transactions/", {"search": "Coffee"})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.old_entry.pk)

    def test_search_matches_description(self):
        """Search should match the entry description."""
        response = self.client.get(f"/a/{self.team.slug}/journal/api/transactions/", {"search": "Ancient"})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.old_entry.pk)

    def test_search_matches_amount(self):
        """Search should match the transaction amount."""
        response = self.client.get(f"/a/{self.team.slug}/journal/api/transactions/", {"search": "42.42"})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.old_entry.pk)

    def test_date_range_filters_entries(self):
        """Date range filtering should narrow results to entries in range."""
        response = self.client.get(
            f"/a/{self.team.slug}/journal/api/transactions/",
            {"start_date": "2020-01-01", "end_date": "2020-01-01"},
        )

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.old_entry.pk)

    def test_search_and_date_range_combine(self):
        """Search and date range filters should apply together (AND)."""
        response = self.client.get(
            f"/a/{self.team.slug}/journal/api/transactions/",
            {"search": "Entry", "start_date": "2024-01-01", "end_date": "2024-01-03"},
        )

        descriptions = {row["description"] for row in response.data["results"]}
        self.assertEqual(descriptions, {"Entry 0", "Entry 1", "Entry 2"})


class TransactionZeroAmountAPITest(TestCase):
    """
    A $0.00 entry has dr_amount == cr_amount == 0 on both of its lines, so
    the debit/credit account can't be picked out by testing each line's
    amount against zero in isolation -- the Transactions list must still
    report both accounts by comparing the two lines against each other.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)
        cls.expense_account = Account.objects.create(
            team=cls.team, name="Miscellaneous", account_group=cls.expense_group
        )

        with current_team(cls.team):
            cls.entry = JournalEntry.objects.create(
                team=cls.team, entry_date=date(2025, 1, 1), description="Zero-dollar memo transaction"
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.entry, account=cls.bank_account, dr_amount=Decimal("0")
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.entry, account=cls.expense_account, cr_amount=Decimal("0")
            )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_zero_amount_entry_still_reports_both_accounts(self):
        """Both accounts should be named even though neither line's amount is > 0."""
        response = self.client.get(f"/a/{self.team.slug}/journal/api/transactions/")

        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["debit_account"], "Checking")
        self.assertEqual(row["credit_account"], "Miscellaneous")
        self.assertEqual(row["amount"], "0.00")


class TransactionSplitAPITest(TestCase):
    """
    Splits on the Transactions list.

    This list used to filter to `line_count=2`, so every split -- an entry
    apportioned across several categories, which `apps.ynab_import` creates by
    the dozen -- was silently missing from the page that presents itself as the
    ledger, and from its filters, facet counts and export.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Split Team", slug="split-team")
        cls.user = CustomUser.objects.create_user(username="splituser", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME)
        cls.chequing = Account.objects.create(team=cls.team, name="Chequing", account_group=cls.asset_group)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)
        cls.household = Account.objects.create(team=cls.team, name="Household Goods", account_group=cls.expense_group)
        cls.salary = Account.objects.create(team=cls.team, name="Salary", account_group=cls.income_group)

        with current_team(cls.team):
            # An outflow split: one credit line, two debit legs.
            cls.split = JournalEntry.objects.create(team=cls.team, entry_date=date(2026, 9, 14), description="Costco")
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.split, account=cls.chequing, cr_amount=Decimal("210.40")
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.split, account=cls.groceries, dr_amount=Decimal("160.00")
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.split, account=cls.household, dr_amount=Decimal("50.40")
            )

            # An inflow split: one debit line, two credit legs.
            cls.inflow_split = JournalEntry.objects.create(
                team=cls.team, entry_date=date(2026, 9, 15), description="Paycheque"
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.inflow_split, account=cls.chequing, dr_amount=Decimal("2000.00")
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.inflow_split, account=cls.salary, cr_amount=Decimal("1800.00")
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.inflow_split, account=cls.groceries, cr_amount=Decimal("200.00")
            )

            # An ordinary two-line entry, to prove nothing about it changed.
            cls.plain = JournalEntry.objects.create(team=cls.team, entry_date=date(2026, 9, 16), description="Coffee")
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.plain, account=cls.chequing, cr_amount=Decimal("5.00")
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=cls.plain, account=cls.groceries, dr_amount=Decimal("5.00")
            )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def url(self):
        return f"/a/{self.team.slug}/journal/api/transactions/"

    def row_for(self, response, entry):
        return next(row for row in response.data["results"] if row["id"] == entry.id)

    def test_splits_appear_in_the_list(self):
        """The regression this class exists for: a split must be in the ledger."""
        response = self.client.get(self.url())

        self.assertEqual(response.data["count"], 3)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.split.id, ids)
        self.assertIn(self.inflow_split.id, ids)

    def test_outflow_split_row(self):
        response = self.client.get(self.url())
        row = self.row_for(response, self.split)

        self.assertEqual(row["debit_account"], "Split (2)")
        self.assertEqual(row["credit_account"], "Chequing")
        self.assertEqual(row["amount"], "210.40")
        self.assertEqual(row["line_count"], 3)
        self.assertTrue(row["is_split"])
        self.assertEqual(
            sorted((leg["account"], leg["debit"], leg["credit"]) for leg in row["legs"]),
            [
                ("Chequing", "0.00", "210.40"),
                ("Groceries", "160.00", "0.00"),
                ("Household Goods", "50.40", "0.00"),
            ],
        )

    def test_inflow_split_puts_the_label_on_the_credit_side(self):
        response = self.client.get(self.url())
        row = self.row_for(response, self.inflow_split)

        self.assertEqual(row["debit_account"], "Chequing")
        self.assertEqual(row["credit_account"], "Split (2)")
        self.assertEqual(row["amount"], "2000.00")

    def test_plain_entry_is_unchanged(self):
        """The two-line branch must be byte-for-byte what it was."""
        response = self.client.get(self.url())
        row = self.row_for(response, self.plain)

        self.assertEqual(row["debit_account"], "Groceries")
        self.assertEqual(row["credit_account"], "Chequing")
        self.assertEqual(row["amount"], "5.00")
        self.assertEqual(row["line_count"], 2)
        self.assertFalse(row["is_split"])
        self.assertEqual(row["legs"], [])

    def test_search_reaches_splits(self):
        response = self.client.get(self.url(), {"search": "Costco"})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.split.id)

    def test_date_filter_includes_splits(self):
        response = self.client.get(self.url(), {"start_date": "2026-09-14", "end_date": "2026-09-15"})

        self.assertEqual(response.data["count"], 2)


class JournalPermissionsTest(TestCase):
    """Tests for journal permissions."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.admin_user = CustomUser.objects.create_user(username="admin", password="testpass123")
        cls.member_user = CustomUser.objects.create_user(username="member", password="testpass123")
        cls.other_user = CustomUser.objects.create_user(username="other", password="testpass123")

        cls.team.members.add(cls.admin_user, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member_user, through_defaults={"role": ROLE_MEMBER})

        # Create account groups
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )

        # Create accounts
        cls.bank_account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)
        cls.expense_account = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()

    def test_team_member_can_create_entry(self):
        """Test that team members can create journal entries."""
        self.client.force_authenticate(user=self.member_user)

        with current_team(self.team):
            data = {
                "entry_date": "2025-12-17",
                "description": "Test entry",
                "lines": [
                    {"account": self.bank_account.pk, "dr_amount": "100.00", "cr_amount": "0.00"},
                    {"account": self.expense_account.pk, "dr_amount": "0.00", "cr_amount": "100.00"},
                ],
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_team_member_can_view_entries(self):
        """Test that team members can view journal entries."""
        self.client.force_authenticate(user=self.member_user)

        with current_team(self.team):
            entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 17), description="Test entry")
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.bank_account, dr_amount=Decimal("100.00")
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.expense_account, cr_amount=Decimal("100.00")
            )

            response = self.client.get(f"/a/{self.team.slug}/journal/api/journal-entries/{entry.id}/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)


class TransactionColumnFilterAPITest(TestCase):
    """
    Test per-column value filters, sorting and the facets endpoint.

    The table filters and sorts server-side against the whole ledger, so these
    cover the two things the client can't do for itself: a column's list of
    distinct values, and an ordering that survives pagination.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.treats_group = AccountGroup.objects.create(team=cls.team, name="Treats", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.checking = Account.objects.create(team=cls.team, name="Checking", account_group=cls.asset_group)
        cls.savings = Account.objects.create(team=cls.team, name="Savings", account_group=cls.asset_group)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)
        cls.coffee = Account.objects.create(team=cls.team, name="Coffee", account_group=cls.treats_group)

        cls.amazon = Payee.objects.create(team=cls.team, name="Amazon")
        cls.costco = Payee.objects.create(team=cls.team, name="Costco")

        def entry(day, payee, debit, credit, amount, description, **kwargs):
            je = JournalEntry.objects.create(
                team=cls.team,
                entry_date=date(2025, 3, day),
                payee=payee,
                description=description,
                **kwargs,
            )
            JournalLine.objects.create(team=cls.team, journal_entry=je, account=debit, dr_amount=Decimal(amount))
            JournalLine.objects.create(team=cls.team, journal_entry=je, account=credit, cr_amount=Decimal(amount))
            return je

        with current_team(cls.team):
            cls.a = entry(1, cls.amazon, cls.groceries, cls.checking, "25.00", "Weekly shop")
            cls.b = entry(2, cls.costco, cls.groceries, cls.checking, "10.00", "Milk")
            cls.c = entry(3, cls.amazon, cls.coffee, cls.savings, "5.00", "Beans")
            # No payee, and a non-default status, so the "(none)" facet value
            # and the choice-label columns both have something to report.
            cls.d = entry(4, None, cls.coffee, cls.checking, "5.00", "Espresso", status=JournalEntry.STATUS_POSTED)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def url(self, path=""):
        return f"/a/{self.team.slug}/journal/api/transactions/{path}"

    def ids(self, response):
        return [row["id"] for row in response.data["results"]]

    # ------------------------------------------------------------------
    # Column filters
    # ------------------------------------------------------------------

    def test_filter_by_single_column_value(self):
        response = self.client.get(self.url(), {"f_payee": "Amazon"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(self.ids(response)), {self.a.pk, self.c.pk})

    def test_filter_accepts_multiple_values_as_or(self):
        response = self.client.get(self.url(), {"f_debit_account": [f"a:{self.coffee.pk}", f"a:{self.groceries.pk}"]})

        self.assertEqual(set(self.ids(response)), {self.a.pk, self.b.pk, self.c.pk, self.d.pk})

    def test_filters_on_different_columns_combine_as_and(self):
        response = self.client.get(self.url(), {"f_payee": "Amazon", "f_debit_account": f"a:{self.coffee.pk}"})

        self.assertEqual(self.ids(response), [self.c.pk])

    def test_empty_value_selects_rows_with_no_payee(self):
        response = self.client.get(self.url(), {"f_payee": ""})

        self.assertEqual(self.ids(response), [self.d.pk])

    def test_filter_by_amount(self):
        response = self.client.get(self.url(), {"f_amount": "5.00"})

        self.assertEqual(set(self.ids(response)), {self.c.pk, self.d.pk})

    def test_filter_by_date(self):
        response = self.client.get(self.url(), {"f_date": ["2025-03-01", "2025-03-02"]})

        self.assertEqual(set(self.ids(response)), {self.a.pk, self.b.pk})

    def test_filter_by_status_uses_stored_code(self):
        response = self.client.get(self.url(), {"f_status": JournalEntry.STATUS_POSTED})

        self.assertEqual(self.ids(response), [self.d.pk])

    def test_unparseable_filter_value_is_ignored_rather_than_blanking_the_table(self):
        """A stale bookmark shouldn't 400 or silently show an empty ledger."""
        response = self.client.get(self.url(), {"f_date": "not-a-date"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 4)

    def test_column_filter_combines_with_search(self):
        response = self.client.get(self.url(), {"search": "Espresso", "f_payee": ""})

        self.assertEqual(self.ids(response), [self.d.pk])

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    def test_sort_by_amount_ascending(self):
        response = self.client.get(self.url(), {"sort": "amount", "dir": "asc"})

        amounts = [row["amount"] for row in response.data["results"]]
        self.assertEqual(amounts, sorted(amounts, key=Decimal))
        self.assertEqual(Decimal(amounts[0]), Decimal("5.00"))

    def test_sort_by_amount_descending(self):
        response = self.client.get(self.url(), {"sort": "amount", "dir": "desc"})

        self.assertEqual(self.ids(response)[0], self.a.pk)

    def test_sort_by_payee_puts_missing_payees_first(self):
        response = self.client.get(self.url(), {"sort": "payee", "dir": "asc"})

        self.assertEqual(self.ids(response)[0], self.d.pk)

    def test_sort_by_credit_account(self):
        response = self.client.get(self.url(), {"sort": "credit_account", "dir": "desc"})

        self.assertEqual(self.ids(response)[0], self.c.pk)

    def test_unknown_sort_column_falls_back_to_newest_first(self):
        response = self.client.get(self.url(), {"sort": "nonsense"})

        self.assertEqual(self.ids(response), [self.d.pk, self.c.pk, self.b.pk, self.a.pk])

    # ------------------------------------------------------------------
    # Facets
    # ------------------------------------------------------------------

    def test_facets_list_distinct_values_with_counts(self):
        """A flat column lists its stored values."""
        response = self.client.get(self.url("facets/"), {"column": "description"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["hierarchical"])
        self.assertEqual(
            [(row["value"], row["count"]) for row in response.data["values"]],
            [("Beans", 1), ("Espresso", 1), ("Milk", 1), ("Weekly shop", 1)],
        )
        self.assertFalse(response.data["truncated"])

    def test_facets_label_choice_columns(self):
        response = self.client.get(self.url("facets/"), {"column": "status"})

        labels = {row["value"]: row["label"] for row in response.data["values"]}
        self.assertEqual(labels[JournalEntry.STATUS_POSTED], "Posted")
        self.assertEqual(labels[JournalEntry.STATUS_DRAFT], "Draft")

    def test_facets_report_the_no_value_bucket(self):
        response = self.client.get(self.url("facets/"), {"column": "payee"})

        values = {row["value"]: row["count"] for row in response.data["values"]}
        self.assertEqual(values[""], 1)
        self.assertEqual(values["Amazon"], 2)

    def test_facets_ignore_the_columns_own_filter(self):
        """Otherwise the only value on offer would be the one already ticked."""
        response = self.client.get(self.url("facets/"), {"column": "payee", "f_payee": "Amazon"})

        self.assertEqual({row["value"] for row in response.data["values"]}, {"", "Amazon", "Costco"})

    def test_facets_respect_other_columns_filters(self):
        response = self.client.get(self.url("facets/"), {"column": "payee", "f_debit_account": f"a:{self.coffee.pk}"})

        self.assertEqual(
            {row["value"]: row["count"] for row in response.data["values"]},
            {"": 1, "Amazon": 1},
        )

    def test_facets_respect_search_and_date_range(self):
        response = self.client.get(
            self.url("facets/"),
            {"column": "description", "start_date": "2025-03-03", "end_date": "2025-03-04"},
        )

        self.assertEqual(
            [row["value"] for row in response.data["values"]],
            ["Beans", "Espresso"],
        )

    def test_facets_can_be_searched(self):
        response = self.client.get(self.url("facets/"), {"column": "payee", "q": "cost"})

        self.assertEqual([row["value"] for row in response.data["values"]], ["Costco"])

    def test_facets_reject_an_unknown_column(self):
        response = self.client.get(self.url("facets/"), {"column": "nonsense"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_facets_require_team_membership(self):
        outsider = CustomUser.objects.create_user(username="outsider", password="testpass123")
        self.client.force_authenticate(user=outsider)

        response = self.client.get(self.url("facets/"), {"column": "payee"})

        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))


class TransactionHierarchicalFilterAPITest(TestCase):
    """
    Test the hierarchical columns: dates (year → month → day) and the two
    account columns (account type → account group → account).

    A branch is its own filter value rather than shorthand for a list of
    leaves, so that selecting three years doesn't put a thousand values in the
    query string. These tests pin both halves: the branch tokens filter, and
    the facet tree offers them.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.bank_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.employment_group = AccountGroup.objects.create(
            team=cls.team, name="Employment Income", account_type=ACCOUNT_TYPE_INCOME
        )
        cls.side_group = AccountGroup.objects.create(
            team=cls.team, name="Side Income", account_type=ACCOUNT_TYPE_INCOME
        )
        cls.living_group = AccountGroup.objects.create(team=cls.team, name="Living", account_type=ACCOUNT_TYPE_EXPENSE)

        cls.checking = Account.objects.create(team=cls.team, name="Checking", account_group=cls.bank_group)
        cls.paycheck = Account.objects.create(team=cls.team, name="Viv's paycheck", account_group=cls.employment_group)
        cls.bonus = Account.objects.create(team=cls.team, name="Bonus", account_group=cls.employment_group)
        cls.freelance = Account.objects.create(team=cls.team, name="Freelance", account_group=cls.side_group)
        cls.rent = Account.objects.create(team=cls.team, name="Rent", account_group=cls.living_group)

        def entry(entry_date, debit, credit, amount):
            je = JournalEntry.objects.create(
                team=cls.team, entry_date=entry_date, description=f"{credit.name} {entry_date}"
            )
            JournalLine.objects.create(team=cls.team, journal_entry=je, account=debit, dr_amount=Decimal(amount))
            JournalLine.objects.create(team=cls.team, journal_entry=je, account=credit, cr_amount=Decimal(amount))
            return je

        with current_team(cls.team):
            # Credit side carries the income/expense account, debit the bank,
            # so both account columns have something worth nesting.
            cls.jan_pay = entry(date(2024, 1, 15), cls.checking, cls.paycheck, "2000.00")
            cls.feb_pay = entry(date(2024, 2, 15), cls.checking, cls.paycheck, "2000.00")
            cls.feb_bonus = entry(date(2024, 2, 20), cls.checking, cls.bonus, "500.00")
            cls.mar_freelance = entry(date(2025, 3, 10), cls.checking, cls.freelance, "750.00")
            cls.mar_rent = entry(date(2025, 3, 31), cls.rent, cls.checking, "1800.00")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def url(self, path=""):
        return f"/a/{self.team.slug}/journal/api/transactions/{path}"

    def ids(self, response):
        return [row["id"] for row in response.data["results"]]

    def find(self, nodes, value):
        """Depth-first lookup of one node in a facet tree."""
        for node in nodes:
            if node["value"] == value:
                return node
            found = self.find(node.get("children", []), value)
            if found:
                return found
        return None

    # ------------------------------------------------------------------
    # Dates
    # ------------------------------------------------------------------

    def test_year_token_selects_every_date_in_it(self):
        response = self.client.get(self.url(), {"f_date": "2024"})

        self.assertEqual(set(self.ids(response)), {self.jan_pay.pk, self.feb_pay.pk, self.feb_bonus.pk})

    def test_month_token_selects_every_date_in_it(self):
        response = self.client.get(self.url(), {"f_date": "2024-02"})

        self.assertEqual(set(self.ids(response)), {self.feb_pay.pk, self.feb_bonus.pk})

    def test_day_token_still_selects_one_date(self):
        response = self.client.get(self.url(), {"f_date": "2025-03-31"})

        self.assertEqual(self.ids(response), [self.mar_rent.pk])

    def test_date_tokens_of_different_depths_combine_as_or(self):
        response = self.client.get(self.url(), {"f_date": ["2024-02", "2025-03-10"]})

        self.assertEqual(set(self.ids(response)), {self.feb_pay.pk, self.feb_bonus.pk, self.mar_freelance.pk})

    def test_date_facets_nest_year_month_day_with_rolled_up_counts(self):
        response = self.client.get(self.url("facets/"), {"column": "date"})

        self.assertTrue(response.data["hierarchical"])
        years = response.data["values"]
        # Newest first, matching the table's default order.
        self.assertEqual([year["value"] for year in years], ["2025", "2024"])

        year_2024 = self.find(years, "2024")
        self.assertEqual(year_2024["count"], 3)
        self.assertEqual([month["value"] for month in year_2024["children"]], ["2024-02", "2024-01"])

        february = self.find(years, "2024-02")
        self.assertEqual(february["label"], "Feb")
        self.assertEqual(february["full"], "Feb 2024")
        self.assertEqual(february["count"], 2)
        self.assertEqual([day["value"] for day in february["children"]], ["2024-02-20", "2024-02-15"])
        self.assertEqual(february["children"][0]["label"], "20")

    def test_date_facets_ignore_the_date_columns_own_filter(self):
        """Otherwise the only year on offer would be the one already ticked."""
        response = self.client.get(self.url("facets/"), {"column": "date", "f_date": "2024"})

        self.assertEqual([year["value"] for year in response.data["values"]], ["2025", "2024"])

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    def test_account_token_selects_one_account(self):
        response = self.client.get(self.url(), {"f_credit_account": f"a:{self.paycheck.pk}"})

        self.assertEqual(set(self.ids(response)), {self.jan_pay.pk, self.feb_pay.pk})

    def test_group_token_selects_every_account_in_the_group(self):
        response = self.client.get(self.url(), {"f_credit_account": f"g:{self.employment_group.pk}"})

        self.assertEqual(set(self.ids(response)), {self.jan_pay.pk, self.feb_pay.pk, self.feb_bonus.pk})

    def test_type_token_selects_every_account_of_that_type(self):
        response = self.client.get(self.url(), {"f_credit_account": "t:income"})

        self.assertEqual(
            set(self.ids(response)),
            {self.jan_pay.pk, self.feb_pay.pk, self.feb_bonus.pk, self.mar_freelance.pk},
        )

    def test_account_tokens_of_different_depths_combine_as_or(self):
        response = self.client.get(self.url(), {"f_credit_account": [f"g:{self.side_group.pk}", f"a:{self.bonus.pk}"]})

        self.assertEqual(set(self.ids(response)), {self.mar_freelance.pk, self.feb_bonus.pk})

    def test_account_facets_nest_type_group_account_with_rolled_up_counts(self):
        response = self.client.get(self.url("facets/"), {"column": "credit_account"})

        self.assertTrue(response.data["hierarchical"])
        types = response.data["values"]
        self.assertEqual({node["value"] for node in types}, {"t:income", "t:asset"})

        income = self.find(types, "t:income")
        self.assertEqual(income["label"], "Income")
        self.assertEqual(income["count"], 4)
        self.assertEqual(
            {group["value"]: group["count"] for group in income["children"]},
            {f"g:{self.employment_group.pk}": 3, f"g:{self.side_group.pk}": 1},
        )

        employment = self.find(types, f"g:{self.employment_group.pk}")
        self.assertEqual(employment["label"], "Employment Income")
        self.assertEqual(
            {account["value"]: account["label"] for account in employment["children"]},
            {f"a:{self.paycheck.pk}": "Viv's paycheck", f"a:{self.bonus.pk}": "Bonus"},
        )

    def test_account_facets_only_offer_accounts_the_column_actually_shows(self):
        """The credit side of this ledger never carries an expense account."""
        response = self.client.get(self.url("facets/"), {"column": "credit_account"})

        self.assertIsNone(self.find(response.data["values"], f"a:{self.rent.pk}"))

    def test_account_facet_search_keeps_the_matching_branch(self):
        response = self.client.get(self.url("facets/"), {"column": "credit_account", "q": "paycheck"})

        income = self.find(response.data["values"], "t:income")
        self.assertEqual(income["count"], 2)
        self.assertEqual([group["value"] for group in income["children"]], [f"g:{self.employment_group.pk}"])
        self.assertEqual([account["label"] for account in income["children"][0]["children"]], ["Viv's paycheck"])

    def test_another_teams_group_token_matches_nothing(self):
        other_team = Team.objects.create(name="Other", slug="other-team")
        other_group = AccountGroup.objects.create(team=other_team, name="Theirs", account_type=ACCOUNT_TYPE_INCOME)

        response = self.client.get(self.url(), {"f_credit_account": f"g:{other_group.pk}"})

        self.assertEqual(response.data["count"], 0)

    def test_unparseable_account_token_is_ignored(self):
        """A stale bookmark naming a deleted account shouldn't blank the table."""
        response = self.client.get(self.url(), {"f_credit_account": "nonsense"})

        self.assertEqual(response.data["count"], 5)


class ArchivedAndVoidedEntriesExcludedTest(TestCase):
    """
    Voided entries and entries behind an archived bank transaction count toward
    nothing: account balances, reconciled balances, reports, budget actuals, net
    worth, and the transactions ledger.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.bank_feed.models import BankTransaction

        cls.team = Team.objects.create(name="Counted Team", slug="counted-team")
        cls.user = CustomUser.objects.create_user(username="counted", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        asset_group = AccountGroup.objects.create(team=cls.team, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        expense_group = AccountGroup.objects.create(team=cls.team, name="Spend", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.bank = Account.objects.create(team=cls.team, name="Checking", account_group=asset_group, has_feed=True)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=expense_group)
        cls.day = date(2026, 8, 10)

        def spend(amount, description, *, status_=JournalEntry.STATUS_POSTED, archived=False):
            entry = JournalEntry.objects.create(
                team=cls.team, entry_date=cls.day, description=description, status=status_
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=entry, account=cls.groceries, dr_amount=Decimal(amount)
            )
            JournalLine.objects.create(
                team=cls.team, journal_entry=entry, account=cls.bank, cr_amount=Decimal(amount), is_reconciled=True
            )
            BankTransaction.objects.create(
                team=cls.team,
                account=cls.bank,
                amount=Decimal(amount),
                posted_date=cls.day,
                description=description,
                journal_entry=entry,
                is_archived=archived,
            )

        spend("10.00", "Kept")
        spend("500.00", "Archived", archived=True)
        spend("7000.00", "Voided", status_=JournalEntry.STATUS_VOID)

    def test_account_balances(self):
        account = Account.objects.filter(pk=self.bank.pk).with_balance().with_reconciled_balance().get()
        self.assertEqual(account._balance, Decimal("-10.00"))
        self.assertEqual(account._reconciled_balance, Decimal("-10.00"))
        self.assertEqual(Account.objects.get(pk=self.bank.pk).balance, Decimal("-10.00"))

    def test_reports(self):
        from apps.reports.services import ReportService

        service = ReportService(self.team)
        income_statement = service.get_income_statement_data(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(income_statement["total_expenses"], Decimal("10.00"))
        self.assertEqual(service.get_balance_sheet_data(date(2026, 8, 31))["net_worth"], Decimal("-10.00"))

    def test_budget_actual_and_net_worth(self):
        from apps.budget.services import BudgetService, NetWorthService

        self.assertEqual(BudgetService(self.team).actual(self.groceries, date(2026, 8, 1)), Decimal("10.00"))
        self.assertEqual(NetWorthService(self.team).get_net_worth(date(2026, 8, 1)), Decimal("-10.00"))

    def test_transactions_ledger(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get(f"/a/{self.team.slug}/journal/api/transactions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["description"] for row in response.data["results"]], ["Kept"])


class RecategorizeLineAPITest(TestCase):
    """The budget Actual popup's "Move to..." accepts any account type."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Recat Team", slug="recat-team")
        cls.user = CustomUser.objects.create_user(username="recat", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        asset_group = AccountGroup.objects.create(team=cls.team, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        liability_group = AccountGroup.objects.create(team=cls.team, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        expense_group = AccountGroup.objects.create(team=cls.team, name="Spend", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.checking = Account.objects.create(team=cls.team, name="Checking", account_group=asset_group, has_feed=True)
        cls.savings = Account.objects.create(team=cls.team, name="Cash Box", account_group=asset_group)
        cls.card = Account.objects.create(team=cls.team, name="Visa", account_group=liability_group, has_feed=True)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=expense_group)

        other_team = Team.objects.create(name="Other", slug="other-recat")
        other_group = AccountGroup.objects.create(team=other_team, name="X", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.foreign = Account.objects.create(team=other_team, name="Foreign", account_group=other_group)

    def setUp(self):
        from apps.bank_feed.models import BankTransaction

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.entry = JournalEntry.objects.create(team=self.team, entry_date=date(2026, 9, 1), description="Paid")
        self.expense_line = JournalLine.objects.create(
            team=self.team, journal_entry=self.entry, account=self.groceries, dr_amount=Decimal("40.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=self.entry, account=self.checking, cr_amount=Decimal("40.00")
        )
        self.bank_tx = BankTransaction.objects.create(
            team=self.team,
            account=self.checking,
            journal_entry=self.entry,
            amount=Decimal("40.00"),
            posted_date=date(2026, 9, 1),
            description="Paid",
        )

    def _move(self, account_id):
        url = f"/a/{self.team.slug}/journal/api/lines/{self.expense_line.pk}/recategorize/"
        return self.client.post(url, {"new_category_id": account_id}, format="json")

    def test_move_to_asset_account(self):
        response = self._move(self.savings.pk)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.expense_line.refresh_from_db()
        self.assertEqual(self.expense_line.account, self.savings)

    def test_move_to_feed_account_creates_transfer_mirror(self):
        from apps.bank_feed.models import BankTransaction

        response = self._move(self.card.pk)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mirror = BankTransaction.objects.get(journal_entry=self.entry, is_transfer_mirror=True)
        self.assertEqual(mirror.account, self.card)
        self.assertEqual(mirror.amount, Decimal("-40.00"))

    def test_move_onto_other_side_account_refused(self):
        response = self._move(self.checking.pk)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.expense_line.refresh_from_db()
        self.assertEqual(self.expense_line.account, self.groceries)

    def test_other_team_account_not_found(self):
        response = self._move(self.foreign.pk)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.expense_line.refresh_from_db()
        self.assertEqual(self.expense_line.account, self.groceries)
