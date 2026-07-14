"""
Tests for budget app.
Tests models, forms, services, views, and API endpoints.
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError
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
            team=cls.team, name="Model Groceries", account_group=cls.expense_group
        )
        cls.income_account = Account.objects.create(team=cls.team, name="Model Salary", account_group=cls.income_group)

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
        with self.assertRaises(IntegrityError):
            Budget.objects.create(
                team=self.team,
                month=date(2025, 12, 1),
                category=self.expense_account,
                budget_amount=Decimal("600.00"),
            )

    def test_budget_ordering(self):
        """Test that budgets are ordered by month descending."""
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
            team=cls.team, name="Service Groceries", account_group=cls.expense_group
        )
        cls.income_account = Account.objects.create(
            team=cls.team, name="Service Salary", account_group=cls.income_group
        )
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Service Assets", account_type="asset")
        cls.asset_account = Account.objects.create(
            team=cls.team, name="Service Checking", account_group=cls.asset_group
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
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 15), description="Salary payment")
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
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 15), description="Salary payment")
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

        self.assertEqual(actuals[self.expense_account.pk], Decimal("100.00"))
        self.assertEqual(actuals[self.income_account.pk], Decimal("2000.00"))

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

        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2025, 12, 15), description="Transactions")
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
        expense_row = next(r for r in rows if r["category_id"] == self.expense_account.pk)
        income_row = next(r for r in rows if r["category_id"] == self.income_account.pk)

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
            team=cls.team, name="Form Groceries", account_group=cls.expense_group
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


class BudgetMonthViewTest(TestCase):
    """Tests for budget_month_view GET/POST behavior."""

    @classmethod
    def setUpTestData(cls):
        from apps.teams.roles import ROLE_ADMIN
        from apps.users.models import CustomUser

        cls.team = Team.objects.create(name="View Test Team", slug="view-test-team")
        cls.user = CustomUser.objects.create_user(username="budgetuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="View Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.expense_account = Account.objects.create(
            team=cls.team, name="View Groceries", account_group=cls.expense_group
        )

    def setUp(self):
        self.client.login(username="budgetuser@example.com", password="testpass123")

    def test_get_does_not_create_budget_rows(self):
        """Merely viewing a month must not insert Budget rows."""
        response = self.client.get(f"/a/{self.team.slug}/budget/?month=2030-01-01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Budget.objects.filter(team=self.team).count(), 0)

    def test_post_creates_budget_lazily_for_category(self):
        """Saving an amount for a category without a Budget row creates it."""
        response = self.client.post(
            f"/a/{self.team.slug}/budget/?month=2025-06-01",
            {
                "category_id": self.expense_account.pk,
                "budget_month": "2025-06-01",
                "budget_amount": "123.45",
            },
        )
        self.assertEqual(response.status_code, 302)
        budget = Budget.objects.get(team=self.team, category=self.expense_account, month=date(2025, 6, 1))
        self.assertEqual(budget.budget_amount, Decimal("123.45"))

    def test_post_updates_existing_budget(self):
        """Saving an amount for an existing Budget row updates it in place."""
        budget = Budget.objects.create(
            team=self.team,
            category=self.expense_account,
            month=date(2025, 6, 1),
            budget_amount=Decimal("10.00"),
        )
        response = self.client.post(
            f"/a/{self.team.slug}/budget/?month=2025-06-01",
            {"budget_id": budget.pk, "budget_amount": "55.00"},
        )
        self.assertEqual(response.status_code, 302)
        budget.refresh_from_db()
        self.assertEqual(budget.budget_amount, Decimal("55.00"))
        self.assertEqual(Budget.objects.filter(team=self.team).count(), 1)


class BudgetAutofillViewTest(TestCase):
    """Tests for budget_autofill_view, including the category_ids selection filter."""

    @classmethod
    def setUpTestData(cls):
        from apps.teams.roles import ROLE_ADMIN
        from apps.users.models import CustomUser

        cls.team = Team.objects.create(name="Autofill Test Team", slug="autofill-test-team")
        cls.user = CustomUser.objects.create_user(username="autofilluser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Autofill Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.groceries = Account.objects.create(
            team=cls.team, name="Autofill Groceries", account_group=cls.expense_group
        )
        cls.rent = Account.objects.create(team=cls.team, name="Autofill Rent", account_group=cls.expense_group)

    def setUp(self):
        self.client.login(username="autofilluser@example.com", password="testpass123")
        self.prev_month = date(2025, 5, 1)
        self.month = date(2025, 6, 1)
        Budget.objects.create(
            team=self.team, category=self.groceries, month=self.prev_month, budget_amount=Decimal("100.00")
        )
        Budget.objects.create(
            team=self.team, category=self.rent, month=self.prev_month, budget_amount=Decimal("900.00")
        )

    def test_assigned_last_month_applies_to_all_when_not_filtered(self):
        """Without the 'filtered' marker (no-JS fallback), the action applies to every category."""
        response = self.client.post(
            f"/a/{self.team.slug}/budget/autofill/",
            {"month": "2025-06-01", "action": "assigned_last_month"},
        )
        self.assertEqual(response.status_code, 302)
        groceries_budget = Budget.objects.get(team=self.team, category=self.groceries, month=self.month)
        rent_budget = Budget.objects.get(team=self.team, category=self.rent, month=self.month)
        self.assertEqual(groceries_budget.budget_amount, Decimal("100.00"))
        self.assertEqual(rent_budget.budget_amount, Decimal("900.00"))

    def test_assigned_last_month_respects_category_selection(self):
        """When filtered, only the selected category_ids are touched."""
        response = self.client.post(
            f"/a/{self.team.slug}/budget/autofill/",
            {
                "month": "2025-06-01",
                "action": "assigned_last_month",
                "filtered": "1",
                "category_ids": [str(self.groceries.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        groceries_budget = Budget.objects.get(team=self.team, category=self.groceries, month=self.month)
        self.assertEqual(groceries_budget.budget_amount, Decimal("100.00"))
        self.assertFalse(Budget.objects.filter(team=self.team, category=self.rent, month=self.month).exists())


class BudgetGridViewTest(TestCase):
    """Tests for the multi-month budget grid editor and its bulk save endpoint."""

    @classmethod
    def setUpTestData(cls):
        from apps.teams.roles import ROLE_ADMIN
        from apps.users.models import CustomUser

        cls.team = Team.objects.create(name="Grid Test Team", slug="grid-test-team")
        cls.user = CustomUser.objects.create_user(username="griduser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Grid Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.income_group = AccountGroup.objects.create(
            team=cls.team, name="Grid Income", account_type=ACCOUNT_TYPE_INCOME
        )
        cls.groceries = Account.objects.create(team=cls.team, name="Grid Groceries", account_group=cls.expense_group)
        cls.salary = Account.objects.create(team=cls.team, name="Grid Salary", account_group=cls.income_group)

        # An account on another team, to verify cross-tenant writes are rejected
        cls.other_team = Team.objects.create(name="Grid Other Team", slug="grid-other-team")
        other_group = AccountGroup.objects.create(
            team=cls.other_team, name="Other Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.other_account = Account.objects.create(team=cls.other_team, name="Other Rent", account_group=other_group)

        cls.grid_url = f"/a/{cls.team.slug}/budget/grid/"
        cls.save_url = f"/a/{cls.team.slug}/budget/grid/save/"

    def setUp(self):
        self.client.login(username="griduser@example.com", password="testpass123")

    def post_save(self, changes):
        return self.client.post(self.save_url, {"changes": changes}, content_type="application/json")

    # ------------------------------------------------------------------ GET

    def test_grid_view_renders_with_existing_amounts(self):
        Budget.objects.create(
            team=self.team, category=self.groceries, month=date(2026, 3, 1), budget_amount=Decimal("250.00")
        )
        response = self.client.get(f"{self.grid_url}?start=2026-01-01")
        self.assertEqual(response.status_code, 200)
        props = response.context["grid_props"]
        self.assertEqual(len(props["months"]), 12)
        self.assertEqual(props["months"][0], {"key": "2026-01-01", "label": "Jan 2026"})
        groceries_row = next(
            row for group in props["groups"] for row in group["rows"] if row["id"] == self.groceries.pk
        )
        self.assertEqual(groceries_row["amounts"]["2026-03-01"], "250.00")

    def test_grid_view_does_not_create_budget_rows(self):
        response = self.client.get(f"{self.grid_url}?start=2031-01-01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Budget.objects.filter(team=self.team).count(), 0)

    def test_grid_view_excludes_other_teams_accounts(self):
        response = self.client.get(self.grid_url)
        row_ids = {row["id"] for group in response.context["grid_props"]["groups"] for row in group["rows"]}
        self.assertNotIn(self.other_account.pk, row_ids)

    def test_grid_view_clamps_months_param(self):
        response = self.client.get(f"{self.grid_url}?start=2026-01-01&months=999")
        self.assertEqual(len(response.context["grid_props"]["months"]), 24)

    def test_grid_view_requires_login(self):
        self.client.logout()
        response = self.client.get(self.grid_url)
        self.assertEqual(response.status_code, 302)

    def test_grid_view_requires_team_membership(self):
        response = self.client.get(f"/a/{self.other_team.slug}/budget/grid/")
        self.assertEqual(response.status_code, 404)

    # ----------------------------------------------------------------- POST

    def test_save_creates_and_updates_budgets(self):
        existing = Budget.objects.create(
            team=self.team, category=self.groceries, month=date(2026, 1, 1), budget_amount=Decimal("100.00")
        )
        response = self.post_save(
            [
                {"category_id": self.groceries.pk, "month": "2026-01-01", "amount": "150.00"},
                {"category_id": self.groceries.pk, "month": "2026-02-01", "amount": "175.50"},
                {"category_id": self.salary.pk, "month": "2026-01-01", "amount": "4000"},
            ]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"saved": 3})
        existing.refresh_from_db()
        self.assertEqual(existing.budget_amount, Decimal("150.00"))
        self.assertEqual(
            Budget.objects.get(team=self.team, category=self.groceries, month=date(2026, 2, 1)).budget_amount,
            Decimal("175.50"),
        )
        self.assertEqual(
            Budget.objects.get(team=self.team, category=self.salary, month=date(2026, 1, 1)).budget_amount,
            Decimal("4000.00"),
        )

    def test_save_logs_audit_event(self):
        from apps.audit.models import AuditEvent

        self.post_save([{"category_id": self.groceries.pk, "month": "2026-01-01", "amount": "10"}])
        event = AuditEvent.objects.filter(team=self.team, event_type=AuditEvent.BULK_EDIT).latest("timestamp")
        self.assertEqual(event.metadata["scope"], "budget_grid")
        self.assertEqual(event.metadata["saved"], 1)

    def test_save_rejects_other_teams_category(self):
        response = self.post_save(
            [
                {"category_id": self.groceries.pk, "month": "2026-01-01", "amount": "50.00"},
                {"category_id": self.other_account.pk, "month": "2026-01-01", "amount": "50.00"},
            ]
        )
        self.assertEqual(response.status_code, 400)
        # All-or-nothing: the valid change must not have been applied either
        self.assertEqual(Budget.objects.count(), 0)

    def test_save_rejects_invalid_amount(self):
        response = self.post_save([{"category_id": self.groceries.pk, "month": "2026-01-01", "amount": "abc"}])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Budget.objects.count(), 0)

    def test_save_rejects_invalid_month(self):
        response = self.post_save([{"category_id": self.groceries.pk, "month": "not-a-date", "amount": "10"}])
        self.assertEqual(response.status_code, 400)

    def test_save_rejects_malformed_body(self):
        response = self.client.post(self.save_url, "not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(self.save_url, {"changes": "nope"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_save_normalizes_month_to_first_day(self):
        response = self.post_save([{"category_id": self.groceries.pk, "month": "2026-01-15", "amount": "20"}])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Budget.objects.filter(team=self.team, category=self.groceries, month=date(2026, 1, 1)).exists())

    def test_save_last_write_wins_for_duplicate_cells(self):
        response = self.post_save(
            [
                {"category_id": self.groceries.pk, "month": "2026-01-01", "amount": "10"},
                {"category_id": self.groceries.pk, "month": "2026-01-01", "amount": "30"},
            ]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"saved": 1})
        self.assertEqual(
            Budget.objects.get(team=self.team, category=self.groceries, month=date(2026, 1, 1)).budget_amount,
            Decimal("30.00"),
        )

    def test_save_requires_post(self):
        response = self.client.get(self.save_url)
        self.assertEqual(response.status_code, 405)

    def test_save_requires_team_membership(self):
        response = self.client.post(
            f"/a/{self.other_team.slug}/budget/grid/save/",
            {"changes": []},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)


class BudgetSectionOrderingTest(TestCase):
    """Income categories render above expenses, with separate section totals."""

    @classmethod
    def setUpTestData(cls):
        from apps.teams.roles import ROLE_ADMIN
        from apps.users.models import CustomUser

        cls.team = Team.objects.create(name="Order Test Team", slug="order-test-team")
        cls.user = CustomUser.objects.create_user(username="orderuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        # "Alpha Expenses" sorts before "Zeta Income" alphabetically, so these
        # verify the income-before-expense ordering is deliberate
        expense_group = AccountGroup.objects.create(
            team=cls.team, name="Alpha Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        income_group = AccountGroup.objects.create(team=cls.team, name="Zeta Income", account_type=ACCOUNT_TYPE_INCOME)
        cls.expense_account = Account.objects.create(team=cls.team, name="Order Rent", account_group=expense_group)
        cls.income_account = Account.objects.create(team=cls.team, name="Order Salary", account_group=income_group)

    def setUp(self):
        self.client.login(username="orderuser@example.com", password="testpass123")

    def test_month_view_sections_income_first_with_totals(self):
        Budget.objects.create(
            team=self.team, category=self.income_account, month=date(2026, 5, 1), budget_amount=Decimal("4000.00")
        )
        Budget.objects.create(
            team=self.team, category=self.expense_account, month=date(2026, 5, 1), budget_amount=Decimal("1500.00")
        )
        response = self.client.get(f"/a/{self.team.slug}/budget/?month=2026-05-01")
        self.assertEqual(response.status_code, 200)
        income_section, expense_section = response.context["sections"]
        self.assertEqual(income_section["key"], "income")
        self.assertEqual(income_section["groups"][0]["name"], "Zeta Income")
        self.assertEqual(income_section["totals"]["budgeted"], Decimal("4000.00"))
        self.assertEqual(expense_section["key"], "expense")
        self.assertEqual(expense_section["groups"][0]["name"], "Alpha Expenses")
        self.assertEqual(expense_section["totals"]["budgeted"], Decimal("1500.00"))

    def test_grid_view_groups_income_first(self):
        response = self.client.get(f"/a/{self.team.slug}/budget/grid/?start=2026-01-01")
        groups = response.context["grid_props"]["groups"]
        self.assertEqual([g["type"] for g in groups], ["income", "expense"])
        self.assertEqual(groups[0]["name"], "Zeta Income")
