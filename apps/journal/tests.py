"""
Tests for journal app.
Tests models, views, serializers, and API endpoints.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
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
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking", account_number=1000, account_group=cls.asset_group
        )
        cls.expense_account = Account.objects.create(
            team=cls.team, name="Groceries", account_number=4000, account_group=cls.expense_group
        )
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
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking", account_number=1000, account_group=cls.asset_group
        )
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
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking Account", account_number=1001, account_group=cls.asset_group
        )
        cls.groceries_account = Account.objects.create(
            team=cls.team, name="Groceries", account_number=4001, account_group=cls.expense_group
        )
        cls.salary_account = Account.objects.create(
            team=cls.team, name="Salary", account_number=3001, account_group=cls.income_group
        )

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
                "account": self.bank_account.account_id,
                "category": self.groceries_account.account_id,
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
                "account": self.bank_account.account_id,
                "category": self.salary_account.account_id,
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
        """Test createing a transaction with no category."""
        with current_team(self.team):
            data = {
                "date": "2025-12-17",
                "account": self.bank_account.account_id,
                "category": None,
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
            income_line = journal_entry.lines.get(account=None)

            self.assertEqual(bank_line.dr_amount, Decimal("1000.00"))
            self.assertEqual(bank_line.cr_amount, Decimal("0.00"))
            self.assertEqual(income_line.dr_amount, Decimal("0.00"))
            self.assertEqual(income_line.cr_amount, Decimal("1000.00"))

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
                "account": self.bank_account.account_id,
                "category": self.groceries_account.account_id,
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
                "account": self.bank_account.account_id,
                "category": self.groceries_account.account_id,
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
                "account": self.bank_account.account_id,
                "category": self.groceries_account.account_id,
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
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking", account_number=1000, account_group=cls.asset_group
        )
        cls.expense_account = Account.objects.create(
            team=cls.team, name="Groceries", account_number=4000, account_group=cls.expense_group
        )
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
                    {"account": self.bank_account.account_id, "dr_amount": "100.00", "cr_amount": "0.00"},
                    {"account": self.expense_account.account_id, "dr_amount": "0.00", "cr_amount": "100.00"},
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
                    {"account": self.bank_account.account_id, "dr_amount": "150.00", "cr_amount": "0.00"},
                    {"account": self.expense_account.account_id, "dr_amount": "0.00", "cr_amount": "150.00"},
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
                    {"account": self.bank_account.account_id, "dr_amount": "100.00", "cr_amount": "0.00"},
                    {"account": self.expense_account.account_id, "dr_amount": "0.00", "cr_amount": "50.00"},
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
                    {"account": self.bank_account.account_id, "dr_amount": "100.00", "cr_amount": "0.00"},
                ],
            }

            response = self.client.post(f"/a/{self.team.slug}/journal/api/journal-entries/", data, format="json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class JournalTemplateViewTest(TestCase):
    """Tests for journal template views."""

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

        # Create account with feed
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking", account_number=1000, account_group=cls.asset_group, has_feed=True
        )

    def setUp(self):
        """Set up for each test."""
        self.client.login(username="testuser", password="testpass123")

    def test_journal_home_view(self):
        """Test journal home view renders correctly."""
        response = self.client.get(f"/a/{self.team.slug}/journal/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(response, "journal/journal_home.html")
        self.assertIn("accounts", response.context)
        self.assertIn("all_accounts", response.context)
        self.assertIn("all_payees", response.context)
        self.assertIn("api_urls", response.context)

    def test_journal_home_view_requires_login(self):
        """Test journal home view requires login."""
        self.client.logout()
        response = self.client.get(f"/a/{self.team.slug}/journal/")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("/accounts/login/", response.url)


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
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking", account_number=1000, account_group=cls.asset_group
        )
        cls.expense_account = Account.objects.create(
            team=cls.team, name="Groceries", account_number=4000, account_group=cls.expense_group
        )

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
                    {"account": self.bank_account.account_id, "dr_amount": "100.00", "cr_amount": "0.00"},
                    {"account": self.expense_account.account_id, "dr_amount": "0.00", "cr_amount": "100.00"},
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
