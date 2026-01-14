"""
Tests for budget app.
Tests models, forms, services, views, and API endpoints.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team

from .forms import BudgetAmountForm
from .models import Budget
from .services import BudgetService


class BudgetModelTest(TestCase):
    """Tests for Budget model."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Budget Test Team", slug="budget-test-team")
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Model Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.income_group = AccountGroup.objects.create(
            team=cls.team, name="Model Income", account_type=ACCOUNT_TYPE_INCOME
        )
        cls.expense_account = Account.objects.create(
            team=cls.team, name="Model Groceries", account_number=4001, account_group=cls.expense_group
        )
        cls.income_account = Account.objects.create(
            team=cls.team, name="Model Salary", account_number=3001, account_group=cls.income_group
        )

    def test_create_budget(self):
        """Test creating a budget."""
        budget = Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )
        self.assertEqual(budget.budget_amount, Decimal("500.00"))
        self.assertEqual(budget.category, self.expense_account)
        self.assertEqual(budget.month, date(2025, 12, 1))

    def test_budget_str(self):
        """Test string representation of budget."""
        budget = Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )
        self.assertIn("2025-12", str(budget))
        self.assertIn("Groceries", str(budget))
        self.assertIn("$500.00", str(budget))

    def test_unique_together_constraint(self):
        """Test that budgets have unique team/month/category combinations."""
        Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )

        # Should raise IntegrityError for duplicate
        with self.assertRaises(Exception):  # Could be IntegrityError or ValidationError
            Budget.objects.create(
                team=self.team,
                month=date(2025, 12, 1),
                category=self.expense_account,
                budget_amount=Decimal("600.00"),
            )

    def test_budget_ordering(self):
        """Test that budgets are ordered by month descending, then account number."""
        budget1 = Budget.objects.create(
            team=self.team,
            month=date(2025, 11, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )
        budget2 = Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("600.00"),
        )

        budgets = list(Budget.objects.all())
        self.assertEqual(budgets[0], budget2)  # December first (newer)
        self.assertEqual(budgets[1], budget1)  # November second


class BudgetServiceTest(TestCase):
    """Tests for BudgetService."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Service Test Team", slug="service-test-team")
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Service Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.income_group = AccountGroup.objects.create(
            team=cls.team, name="Service Income", account_type=ACCOUNT_TYPE_INCOME
        )
        cls.expense_account = Account.objects.create(
            team=cls.team, name="Service Groceries", account_number=4005, account_group=cls.expense_group
        )
        cls.income_account = Account.objects.create(
            team=cls.team, name="Service Salary", account_number=3003, account_group=cls.income_group
        )
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Service Assets", account_type="asset"
        )
        cls.asset_account = Account.objects.create(
            team=cls.team, name="Service Checking", account_number=1001, account_group=cls.asset_group
        )

    def setUp(self):
        self.service = BudgetService(self.team)

    def test_actual_expense_account(self):
        """Test actual calculation for expense accounts (dr - cr)."""
        # Create journal entry: expense debit, asset credit
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2025, 12, 15), description="Grocery purchase"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=Decimal("100.00")
        )

        actual = self.service.actual(self.expense_account, date(2025, 12, 1))
        self.assertEqual(actual, Decimal("100.00"))  # dr - cr = 100 - 0

    def test_actual_income_account(self):
        """Test actual calculation for income accounts (cr - dr)."""
        # Create journal entry: asset debit, income credit
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2025, 12, 15), description="Salary payment"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("2000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.income_account, cr_amount=Decimal("2000.00")
        )

        actual = self.service.actual(self.income_account, date(2025, 12, 1))
        self.assertEqual(actual, Decimal("2000.00"))  # cr - dr = 2000 - 0

    def test_actual_no_transactions(self):
        """Test actual calculation when no transactions exist."""
        actual = self.service.actual(self.expense_account, date(2025, 12, 1))
        self.assertEqual(actual, Decimal("0"))

    def test_available_expense_account_basic(self):
        """Test available calculation for expense accounts (budget - actual)."""
        # Create budget
        Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )

        # Create transaction
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2025, 12, 15), description="Grocery purchase"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=Decimal("100.00")
        )

        available = self.service.available(self.expense_account, date(2025, 12, 1))
        self.assertEqual(available, Decimal("400.00"))  # 500 - 100

    def test_available_income_account_basic(self):
        """Test available calculation for income accounts (actual - budget)."""
        # Create budget
        Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.income_account,
            budget_amount=Decimal("1500.00"),
        )

        # Create transaction
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2025, 12, 15), description="Salary payment"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("2000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.income_account, cr_amount=Decimal("2000.00")
        )

        available = self.service.available(self.income_account, date(2025, 12, 1))
        self.assertEqual(available, Decimal("500.00"))  # 2000 - 1500

    def test_available_recursive_calculation(self):
        """Test available calculation rolls forward from previous months."""
        # November budget: $500, actual: $100, available: $400
        Budget.objects.create(
            team=self.team,
            month=date(2025, 11, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )
        entry_nov = JournalEntry.objects.create(
            team=self.team, entry_date=date(2025, 11, 15), description="November expense"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry_nov, account=self.expense_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry_nov, account=self.asset_account, cr_amount=Decimal("100.00")
        )

        # December budget: $300, actual: $50
        # Available should be: 300 - 50 + 400 = 650
        Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("300.00"),
        )
        entry_dec = JournalEntry.objects.create(
            team=self.team, entry_date=date(2025, 12, 15), description="December expense"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry_dec, account=self.expense_account, dr_amount=Decimal("50.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry_dec, account=self.asset_account, cr_amount=Decimal("50.00")
        )

        available = self.service.available(self.expense_account, date(2025, 12, 1))
        self.assertEqual(available, Decimal("650.00"))

    def test_get_actuals_by_category(self):
        """Test get_actuals_by_category returns correct values."""
        # Create transactions for both expense and income accounts
        entry1 = JournalEntry.objects.create(
            team=self.team, entry_date=date(2025, 12, 15), description="Expense transaction"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry1, account=self.expense_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry1, account=self.asset_account, cr_amount=Decimal("100.00")
        )

        entry2 = JournalEntry.objects.create(
            team=self.team, entry_date=date(2025, 12, 15), description="Income transaction"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.asset_account, dr_amount=Decimal("2000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.income_account, cr_amount=Decimal("2000.00")
        )

        actuals = self.service.get_actuals_by_category(date(2025, 12, 1))

        self.assertEqual(actuals[self.expense_account.account_id], Decimal("100.00"))
        self.assertEqual(actuals[self.income_account.account_id], Decimal("2000.00"))

    def test_build_budget_rows(self):
        """Test build_budget_rows includes expense and income accounts."""
        # Create budgets and transactions
        Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )
        Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.income_account,
            budget_amount=Decimal("1500.00"),
        )

        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2025, 12, 15), description="Transactions"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("2000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.income_account, cr_amount=Decimal("2000.00")
        )

        rows = self.service.build_budget_rows(date(2025, 12, 1))

        # Should have 2 rows (expense and income accounts)
        self.assertEqual(len(rows), 2)

        # Find rows by account
        expense_row = next(r for r in rows if r["category_id"] == self.expense_account.account_id)
        income_row = next(r for r in rows if r["category_id"] == self.income_account.account_id)

        # Check expense row calculations
        self.assertEqual(expense_row["budgeted"], Decimal("500.00"))
        self.assertEqual(expense_row["actual"], Decimal("100.00"))
        self.assertEqual(expense_row["available"], Decimal("400.00"))  # 500 - 100

        # Check income row calculations
        self.assertEqual(income_row["budgeted"], Decimal("1500.00"))
        self.assertEqual(income_row["actual"], Decimal("2000.00"))
        self.assertEqual(income_row["available"], Decimal("500.00"))  # 2000 - 1500


class BudgetAmountFormTest(TestCase):
    """Tests for BudgetAmountForm."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Form Test Team", slug="form-test-team")
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Form Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.expense_account = Account.objects.create(
            team=cls.team, name="Form Groceries", account_number=4002, account_group=cls.expense_group
        )

    def test_form_valid(self):
        """Test form validation with valid data."""
        budget = Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )

        form_data = {"budget_amount": "750.00"}
        form = BudgetAmountForm(data=form_data, instance=budget)
        self.assertTrue(form.is_valid())

    def test_form_decimal_input(self):
        """Test form handles decimal input correctly."""
        budget = Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )

        form_data = {"budget_amount": "123.45"}
        form = BudgetAmountForm(data=form_data, instance=budget)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["budget_amount"], Decimal("123.45"))

    def test_form_blank_input_converts_to_zero(self):
        """Test form converts blank input to 0."""
        budget = Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )

        # Test empty string
        form_data = {"budget_amount": ""}
        form = BudgetAmountForm(data=form_data, instance=budget)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["budget_amount"], Decimal("0"))

        # Test missing field (None)
        form_data = {}
        form = BudgetAmountForm(data=form_data, instance=budget)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["budget_amount"], Decimal("0"))

    def test_form_field_not_required(self):
        """Test that budget_amount field is not required."""
        budget = Budget.objects.create(
            team=self.team,
            month=date(2025, 12, 1),
            category=self.expense_account,
            budget_amount=Decimal("500.00"),
        )

        form_data = {}  # No budget_amount field
        form = BudgetAmountForm(data=form_data, instance=budget)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["budget_amount"], Decimal("0"))
