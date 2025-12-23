from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    Account,
    AccountGroup,
    Payee,
)
from apps.teams.models import Team
from apps.users.models import CustomUser

from .models import JournalEntry, JournalLine


class SimpleTransactionAPITest(TestCase):
    """Test the simplified transaction API endpoint."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        # Create team
        cls.team = Team.objects.create(name="Test Team", slug="test-team")

        # Create user and add to team
        cls.user = CustomUser.objects.create_user(username="testuser", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": "admin"})

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
        data = {
            "date": "2025-12-17",
            "account": self.bank_account.account_id,
            "category": self.groceries_account.account_id,
            "amount": "50.00",
            "description": "Bought groceries",
            "payee": self.payee.id,
        }

        response = self.client.post(f"/a/{self.team.slug}/journal/api/transactions/", data, format="json")

        self.assertEqual(response.status_code, 201)
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
        data = {
            "date": "2025-12-17",
            "account": self.bank_account.account_id,
            "category": self.salary_account.account_id,
            "amount": "1000.00",
            "description": "Monthly salary",
        }

        response = self.client.post(f"/a/{self.team.slug}/journal/api/transactions/", data, format="json")

        self.assertEqual(response.status_code, 201)

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

    def test_list_transactions(self):
        """Test listing transactions."""
        # Create a transaction first
        journal_entry = JournalEntry.objects.create(
            team=self.team, entry_date="2025-12-17", description="Test transaction", status=JournalEntry.STATUS_DRAFT
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

        response = self.client.get(f"/a/{self.team.slug}/journal/api/transactions/")

        self.assertEqual(response.status_code, 200)
        # Response is paginated, so check the results key
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["description"], "Test transaction")

    def test_retrieve_transaction(self):
        """Test retrieving a single transaction."""
        # Create a transaction
        journal_entry = JournalEntry.objects.create(
            team=self.team, entry_date="2025-12-17", description="Test transaction", status=JournalEntry.STATUS_DRAFT
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

        response = self.client.get(f"/a/{self.team.slug}/journal/api/transactions/{journal_entry.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["description"], "Test transaction")
        self.assertEqual(response.data["amount"], "50.00")

    def test_update_transaction(self):
        """Test updating a transaction."""
        # Create a transaction
        journal_entry = JournalEntry.objects.create(
            team=self.team, entry_date="2025-12-17", description="Old description", status=JournalEntry.STATUS_DRAFT
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

        # Update the transaction
        data = {
            "date": "2025-12-18",
            "account": self.bank_account.account_id,
            "category": self.groceries_account.account_id,
            "amount": "75.00",
            "description": "Updated description",
        }

        response = self.client.put(
            f"/a/{self.team.slug}/journal/api/transactions/{journal_entry.id}/", data, format="json"
        )

        self.assertEqual(response.status_code, 200)

        # Verify the update
        journal_entry.refresh_from_db()
        self.assertEqual(journal_entry.description, "Updated description")
        self.assertEqual(str(journal_entry.entry_date), "2025-12-18")

        # Verify lines were updated
        expense_line = journal_entry.lines.get(account=self.groceries_account)
        self.assertEqual(expense_line.dr_amount, Decimal("75.00"))

    def test_delete_transaction(self):
        """Test deleting a transaction."""
        # Create a transaction
        journal_entry = JournalEntry.objects.create(
            team=self.team, entry_date="2025-12-17", description="To be deleted", status=JournalEntry.STATUS_DRAFT
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

        response = self.client.delete(f"/a/{self.team.slug}/journal/api/transactions/{journal_entry.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(JournalLine.objects.count(), 0)
