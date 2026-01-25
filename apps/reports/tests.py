"""
Tests for reports app.
Tests forms, services, views, and URL configuration.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .forms import BalanceSheetForm, IncomeStatementForm, NetWorthTrendForm
from .services import ReportService


class ReportServiceTest(TestCase):
    """Tests for ReportService."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Report Test Team", slug="report-test-team")

        # Create account groups
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.liability_group = AccountGroup.objects.create(
            team=cls.team, name="Liabilities", account_type=ACCOUNT_TYPE_LIABILITY
        )
        cls.equity_group = AccountGroup.objects.create(
            team=cls.team, name="Equity", account_type=ACCOUNT_TYPE_EQUITY
        )
        cls.income_group = AccountGroup.objects.create(
            team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )

        # Create accounts
        cls.asset_account = Account.objects.create(
            team=cls.team, name="Cash", account_number=1001, account_group=cls.asset_group
        )
        cls.liability_account = Account.objects.create(
            team=cls.team, name="Loans", account_number=2001, account_group=cls.liability_group
        )
        cls.equity_account = Account.objects.create(
            team=cls.team, name="Retained Earnings", account_number=3001, account_group=cls.equity_group
        )
        cls.income_account = Account.objects.create(
            team=cls.team, name="Sales Revenue", account_number=4001, account_group=cls.income_group
        )
        cls.expense_account = Account.objects.create(
            team=cls.team, name="Operating Expenses", account_number=5001, account_group=cls.expense_group
        )

    def setUp(self):
        self.service = ReportService(self.team)

    def test_income_statement_data_basic(self):
        """Test basic income statement data calculation."""
        # Create income transaction
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2024, 12, 15), description="Sales revenue"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.income_account, cr_amount=Decimal("1000.00")
        )

        # Create expense transaction
        entry2 = JournalEntry.objects.create(
            team=self.team, entry_date=date(2024, 12, 20), description="Operating expenses"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.expense_account, dr_amount=Decimal("300.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.asset_account, cr_amount=Decimal("300.00")
        )

        start_date = date(2024, 12, 1)
        end_date = date(2024, 12, 31)
        data = self.service.get_income_statement_data(start_date, end_date)

        self.assertEqual(len(data['income']), 1)
        self.assertEqual(len(data['expenses']), 1)
        self.assertEqual(data['total_income'], Decimal("1000.00"))
        self.assertEqual(data['total_expenses'], Decimal("300.00"))
        self.assertEqual(data['net_profit'], Decimal("700.00"))

    def test_balance_sheet_data_basic(self):
        """Test basic balance sheet data calculation."""
        # Create asset transaction
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2024, 12, 15), description="Initial capital"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("5000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.equity_account, cr_amount=Decimal("5000.00")
        )

        # Create liability transaction
        entry2 = JournalEntry.objects.create(
            team=self.team, entry_date=date(2024, 12, 20), description="Loan taken"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.asset_account, dr_amount=Decimal("2000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.liability_account, cr_amount=Decimal("2000.00")
        )

        as_of_date = date(2024, 12, 31)
        data = self.service.get_balance_sheet_data(as_of_date)

        self.assertEqual(len(data['assets']), 1)
        self.assertEqual(len(data['liabilities']), 1)
        self.assertEqual(len(data['equity']), 1)
        self.assertEqual(data['total_assets'], Decimal("7000.00"))
        self.assertEqual(data['total_liabilities'], Decimal("2000.00"))
        self.assertEqual(data['total_equity'], Decimal("5000.00"))
        self.assertEqual(data['net_worth'], Decimal("5000.00"))

    def test_net_worth_trend_data_by_date_range(self):
        """Test net worth trend data calculation by date range."""
        # Create transactions in different months
        # January transaction
        entry1 = JournalEntry.objects.create(
            team=self.team, entry_date=date(2024, 1, 15), description="Jan capital"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry1, account=self.asset_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry1, account=self.equity_account, cr_amount=Decimal("1000.00")
        )

        # February transaction
        entry2 = JournalEntry.objects.create(
            team=self.team, entry_date=date(2024, 2, 15), description="Feb loan"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.asset_account, dr_amount=Decimal("500.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.liability_account, cr_amount=Decimal("500.00")
        )

        start_date = date(2024, 1, 1)
        end_date = date(2024, 2, 28)
        data = self.service.get_net_worth_trend_data_by_date_range(start_date, end_date)

        # Should have 2 data points (Jan and Feb)
        self.assertEqual(len(data), 2)

        # January: assets=1000, liabilities=0, net_worth=1000
        self.assertEqual(data[0]['date'], date(2024, 1, 31))
        self.assertEqual(data[0]['net_worth'], Decimal("1000.00"))

        # February: assets=1500, liabilities=500, net_worth=1000
        self.assertEqual(data[1]['date'], date(2024, 2, 28))  # Last day of Feb 2024 (not leap year)
        self.assertEqual(data[1]['net_worth'], Decimal("1000.00"))

    def test_income_statement_no_data(self):
        """Test income statement with no transactions."""
        start_date = date(2024, 12, 1)
        end_date = date(2024, 12, 31)
        data = self.service.get_income_statement_data(start_date, end_date)

        self.assertEqual(len(data['income']), 0)
        self.assertEqual(len(data['expenses']), 0)
        self.assertEqual(data['total_income'], Decimal("0"))
        self.assertEqual(data['total_expenses'], Decimal("0"))
        self.assertEqual(data['net_profit'], Decimal("0"))

    def test_balance_sheet_no_data(self):
        """Test balance sheet with no transactions."""
        as_of_date = date(2024, 12, 31)
        data = self.service.get_balance_sheet_data(as_of_date)

        self.assertEqual(len(data['assets']), 0)
        self.assertEqual(len(data['liabilities']), 0)
        self.assertEqual(len(data['equity']), 0)
        self.assertEqual(data['total_assets'], Decimal("0"))
        self.assertEqual(data['total_liabilities'], Decimal("0"))
        self.assertEqual(data['total_equity'], Decimal("0"))
        self.assertEqual(data['net_worth'], Decimal("0"))


class IncomeStatementFormTest(TestCase):
    """Tests for IncomeStatementForm."""

    def test_form_initial_values(self):
        """Test form initializes with correct default values."""
        form = IncomeStatementForm()
        self.assertEqual(form.fields['period'].initial, 'this_month')

    def test_custom_period_validation_valid(self):
        """Test custom period validation with valid dates."""
        form_data = {
            'period': 'custom',
            'start_date': '2024-01-01',
            'end_date': '2024-01-31'
        }
        form = IncomeStatementForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_custom_period_validation_missing_dates(self):
        """Test custom period with missing dates returns None values from get_date_range."""
        form_data = {
            'period': 'custom',
            # Missing start_date and end_date
        }
        form = IncomeStatementForm(data=form_data)
        # Form is valid (dates are optional), but get_date_range returns None
        self.assertTrue(form.is_valid())
        start_date, end_date = form.get_date_range()
        self.assertIsNone(start_date)
        self.assertIsNone(end_date)

    def test_custom_period_validation_valid_dates(self):
        """Test custom period with valid dates."""
        form_data = {
            'period': 'custom',
            'start_date': '2024-01-01',
            'end_date': '2024-01-31'
        }
        form = IncomeStatementForm(data=form_data)
        self.assertTrue(form.is_valid())
        start_date, end_date = form.get_date_range()
        self.assertEqual(start_date, date(2024, 1, 1))
        self.assertEqual(end_date, date(2024, 1, 31))

    def test_get_date_range_this_month(self):
        """Test get_date_range for 'this_month' period returns first of month to today."""
        form_data = {'period': 'this_month'}
        form = IncomeStatementForm(data=form_data)
        self.assertTrue(form.is_valid())

        start_date, end_date = form.get_date_range()
        today = date.today()
        expected_start = today.replace(day=1)

        self.assertEqual(start_date, expected_start)
        self.assertEqual(end_date, today)


class BalanceSheetFormTest(TestCase):
    """Tests for BalanceSheetForm."""

    def test_form_initial_values(self):
        """Test form initializes with correct default values."""
        form = BalanceSheetForm()
        # The initial value is callable, so evaluate it
        self.assertEqual(form.fields['as_of_date'].initial(), date.today())

    def test_form_valid(self):
        """Test form validation with valid data."""
        form_data = {'as_of_date': '2024-12-31'}
        form = BalanceSheetForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['as_of_date'], date(2024, 12, 31))


class NetWorthTrendFormTest(TestCase):
    """Tests for NetWorthTrendForm."""

    # def test_form_initial_values(self):
    #     """Test form initializes with correct default values."""
    #     form = NetWorthTrendForm()

    #     # The initial values are lambda functions that return the current year-month
    #     # Calculate what they should return based on the test environment's date.today()
    #     expected_current_month = date.today().strftime('%Y-%m')

    #     # Both fields should have the same initial value (current month)
    #     self.assertEqual(form.fields['start_month'].initial(), expected_current_month)
    #     self.assertEqual(form.fields['end_month'].initial(), expected_current_month)

    def test_form_valid(self):
        """Test form validation with valid month data."""
        form_data = {
            'start_month': '2024-01',
            'end_month': '2024-12'
        }
        form = NetWorthTrendForm(data=form_data)
        self.assertTrue(form.is_valid())

        # Check that parsed dates are added to cleaned_data
        self.assertEqual(form.cleaned_data['start_date'], date(2024, 1, 1))
        self.assertEqual(form.cleaned_data['end_date'], date(2024, 12, 31))

    def test_form_validation_start_after_end(self):
        """Test form validation fails when start month is after end month."""
        form_data = {
            'start_month': '2024-12',
            'end_month': '2024-01'
        }
        form = NetWorthTrendForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_form_validation_invalid_month_format(self):
        """Test form validation fails with invalid month format."""
        form_data = {
            'start_month': 'invalid',
            'end_month': '2024-01'
        }
        form = NetWorthTrendForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)


class ReportViewsTest(TestCase):
    """Tests for report views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="View Test Team", slug="view-test-team")
        cls.user = CustomUser.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)

        # Create account groups and accounts for testing
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.asset_account = Account.objects.create(
            team=cls.team, name="Cash", account_number=1001, account_group=cls.asset_group
        )

    def setUp(self):
        self.client.login(username="testuser", password="testpass123")

    def test_reports_home_view(self):
        """Test reports home view loads successfully."""
        url = reverse('reports:reports_home', kwargs={'team_slug': self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/reports_home.html')

    def test_income_statement_view_get(self):
        """Test income statement view GET request."""
        url = reverse('reports:income_statement', kwargs={'team_slug': self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/income_statement.html')
        # View uses direct date parameters, not a form
        self.assertIn('report_data', response.context)
        self.assertIn('start_date', response.context)
        self.assertIn('end_date', response.context)

    def test_balance_sheet_view_get(self):
        """Test balance sheet view GET request."""
        url = reverse('reports:balance_sheet', kwargs={'team_slug': self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/balance_sheet.html')
        self.assertIsInstance(response.context['form'], BalanceSheetForm)

    def test_net_worth_trend_view_get(self):
        """Test net worth trend view GET request."""
        url = reverse('reports:net_worth_trend', kwargs={'team_slug': self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/net_worth_trend.html')
        self.assertIsInstance(response.context['form'], NetWorthTrendForm)

    def test_net_worth_trend_view_post_valid(self):
        """Test net worth trend view with valid form submission."""
        url = reverse('reports:net_worth_trend', kwargs={'team_slug': self.team.slug})
        form_data = {
            'start_month': '2024-01',
            'end_month': '2024-12'
        }
        response = self.client.get(url, form_data)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context.get('report_data'))

    def test_net_worth_trend_view_post_invalid(self):
        """Test net worth trend view with invalid form submission."""
        url = reverse('reports:net_worth_trend', kwargs={'team_slug': self.team.slug})
        form_data = {
            'start_month': '2024-12',
            'end_month': '2024-01'  # Invalid: start after end
        }
        response = self.client.get(url, form_data)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context.get('report_data'))  # No data generated
        self.assertTrue(response.context['form'].errors)
