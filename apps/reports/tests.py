"""
Tests for reports app.
Tests forms, services, views, and URL configuration.
"""

from datetime import date
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

from .forms import NetWorthTrendForm
from .services import ReportService


class ReportServiceTest(TestCase):
    """Tests for ReportService."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Report Test Team", slug="report-test-team")

        # Create account groups
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.liability_group = AccountGroup.objects.create(
            team=cls.team, name="Liabilities", account_type=ACCOUNT_TYPE_LIABILITY
        )
        cls.equity_group = AccountGroup.objects.create(team=cls.team, name="Equity", account_type=ACCOUNT_TYPE_EQUITY)
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME)
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )

        # Create accounts
        cls.asset_account = Account.objects.create(team=cls.team, name="Cash", account_group=cls.asset_group)
        cls.liability_account = Account.objects.create(team=cls.team, name="Loans", account_group=cls.liability_group)
        cls.equity_account = Account.objects.create(
            team=cls.team, name="Retained Earnings", account_group=cls.equity_group
        )
        cls.income_account = Account.objects.create(team=cls.team, name="Sales Revenue", account_group=cls.income_group)
        cls.expense_account = Account.objects.create(
            team=cls.team, name="Operating Expenses", account_group=cls.expense_group
        )

    def setUp(self):
        self.service = ReportService(self.team)

    def test_income_statement_data_basic(self):
        """Test basic income statement data calculation."""
        # Create income transaction
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 12, 15), description="Sales revenue")
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

        self.assertEqual(len(data["income"]), 1)
        self.assertEqual(len(data["expenses"]), 1)
        self.assertEqual(data["total_income"], Decimal("1000.00"))
        self.assertEqual(data["total_expenses"], Decimal("300.00"))
        self.assertEqual(data["net_profit"], Decimal("700.00"))

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
        entry2 = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 12, 20), description="Loan taken")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.asset_account, dr_amount=Decimal("2000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.liability_account, cr_amount=Decimal("2000.00")
        )

        as_of_date = date(2024, 12, 31)
        data = self.service.get_balance_sheet_data(as_of_date)

        self.assertEqual(len(data["assets"]), 1)
        self.assertEqual(len(data["liabilities"]), 1)
        self.assertEqual(len(data["equity"]), 1)
        self.assertEqual(data["total_assets"], Decimal("7000.00"))
        self.assertEqual(data["total_liabilities"], Decimal("2000.00"))
        self.assertEqual(data["total_equity"], Decimal("5000.00"))
        self.assertEqual(data["net_worth"], Decimal("5000.00"))
        # Accounts are also grouped by account group with subtotals
        self.assertEqual(len(data["asset_groups"]), 1)
        self.assertEqual(data["asset_groups"][0]["group"], self.asset_group)
        self.assertEqual(data["asset_groups"][0]["subtotal"], Decimal("7000.00"))
        self.assertEqual(len(data["liability_groups"]), 1)
        self.assertEqual(data["liability_groups"][0]["subtotal"], Decimal("2000.00"))
        self.assertEqual(len(data["equity_groups"]), 1)
        self.assertEqual(data["equity_groups"][0]["subtotal"], Decimal("5000.00"))

    def test_net_worth_trend_data_by_date_range(self):
        """Test net worth trend data calculation by date range."""
        # Create transactions in different months
        # January transaction
        entry1 = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 1, 15), description="Jan capital")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry1, account=self.asset_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry1, account=self.equity_account, cr_amount=Decimal("1000.00")
        )

        # February transaction
        entry2 = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 2, 15), description="Feb loan")
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
        self.assertEqual(data[0]["date"], date(2024, 1, 31))
        self.assertEqual(data[0]["net_worth"], Decimal("1000.00"))
        self.assertEqual(data[0]["assets"], Decimal("1000.00"))
        self.assertEqual(data[0]["liabilities"], Decimal("0.00"))

        # February: assets=1500, liabilities=500, net_worth=1000
        self.assertEqual(data[1]["date"], date(2024, 2, 28))
        self.assertEqual(data[1]["net_worth"], Decimal("1000.00"))
        self.assertEqual(data[1]["assets"], Decimal("1500.00"))
        self.assertEqual(data[1]["liabilities"], Decimal("500.00"))

    def test_net_worth_trend_includes_opening_balances(self):
        """Activity before the range is carried in as the opening balance of the first month."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2023, 6, 15), description="Old capital")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("2000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.equity_account, cr_amount=Decimal("2000.00")
        )
        entry2 = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 3, 10), description="Mar loan")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.asset_account, dr_amount=Decimal("300.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.liability_account, cr_amount=Decimal("300.00")
        )

        data = self.service.get_net_worth_trend_data_by_date_range(date(2024, 3, 1), date(2024, 4, 30))

        self.assertEqual(len(data), 2)
        # March: opening 2000 + 300 new assets, 300 new liabilities
        self.assertEqual(data[0]["assets"], Decimal("2300.00"))
        self.assertEqual(data[0]["liabilities"], Decimal("300.00"))
        self.assertEqual(data[0]["net_worth"], Decimal("2000.00"))
        # April: no activity, balances carry forward
        self.assertEqual(data[1]["assets"], Decimal("2300.00"))
        self.assertEqual(data[1]["net_worth"], Decimal("2000.00"))

    def test_net_worth_trend_excludes_voided_entries(self):
        """Voided journal entries don't move the trend balances."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 1, 15), description="Capital")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.equity_account, cr_amount=Decimal("1000.00")
        )
        voided = JournalEntry.objects.create(
            team=self.team, entry_date=date(2024, 1, 20), description="Void", status=JournalEntry.STATUS_VOID
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=voided, account=self.asset_account, dr_amount=Decimal("9999.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=voided, account=self.equity_account, cr_amount=Decimal("9999.00")
        )

        data = self.service.get_net_worth_trend_data_by_date_range(date(2024, 1, 1), date(2024, 1, 31))

        self.assertEqual(data[0]["assets"], Decimal("1000.00"))
        self.assertEqual(data[0]["net_worth"], Decimal("1000.00"))

    def test_income_statement_no_data(self):
        """Test income statement with no transactions."""
        start_date = date(2024, 12, 1)
        end_date = date(2024, 12, 31)
        data = self.service.get_income_statement_data(start_date, end_date)

        self.assertEqual(len(data["income"]), 0)
        self.assertEqual(len(data["expenses"]), 0)
        self.assertEqual(len(data["income_groups"]), 0)
        self.assertEqual(len(data["expense_groups"]), 0)
        self.assertEqual(data["total_income"], Decimal("0"))
        self.assertEqual(data["total_expenses"], Decimal("0"))
        self.assertEqual(data["net_profit"], Decimal("0"))

    def test_income_statement_grouped_by_account_group(self):
        """Accounts are grouped by account group with per-group subtotals, sorted by group name."""
        housing_group = AccountGroup.objects.create(team=self.team, name="Housing", account_type=ACCOUNT_TYPE_EXPENSE)
        rent_account = Account.objects.create(team=self.team, name="Rent", account_group=housing_group)
        utilities_account = Account.objects.create(team=self.team, name="Utilities", account_group=housing_group)

        def spend(account, amount, day):
            entry = JournalEntry.objects.create(
                team=self.team, entry_date=date(2024, 12, day), description=f"Spend {account.name}"
            )
            JournalLine.objects.create(team=self.team, journal_entry=entry, account=account, dr_amount=amount)
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=amount
            )

        spend(rent_account, Decimal("1200.00"), 1)
        spend(utilities_account, Decimal("150.00"), 5)
        spend(self.expense_account, Decimal("300.00"), 10)

        data = self.service.get_income_statement_data(date(2024, 12, 1), date(2024, 12, 31))

        self.assertEqual(len(data["expense_groups"]), 2)
        # Sorted by group name: "Expenses" before "Housing"
        first, second = data["expense_groups"]
        self.assertEqual(first["group"], self.expense_group)
        self.assertEqual(first["subtotal"], Decimal("300.00"))
        self.assertEqual([item["account"] for item in first["accounts"]], [self.expense_account])
        self.assertEqual(second["group"], housing_group)
        self.assertEqual(second["subtotal"], Decimal("1350.00"))
        self.assertEqual([item["account"] for item in second["accounts"]], [rent_account, utilities_account])
        # Subtotals sum to the report total
        self.assertEqual(data["total_expenses"], Decimal("1650.00"))

    def _record(self, account, amount, when, kind):
        entry = JournalEntry.objects.create(team=self.team, entry_date=when, description="tx")
        if kind == "income":
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=amount
            )
            JournalLine.objects.create(team=self.team, journal_entry=entry, account=account, cr_amount=amount)
        else:
            JournalLine.objects.create(team=self.team, journal_entry=entry, account=account, dr_amount=amount)
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=amount
            )

    def test_income_statement_by_month(self):
        """period='month' adds aligned per-month breakdowns for accounts, groups, and totals."""
        self._record(self.income_account, Decimal("1000.00"), date(2024, 10, 15), "income")
        self._record(self.income_account, Decimal("1100.00"), date(2024, 12, 15), "income")
        self._record(self.expense_account, Decimal("300.00"), date(2024, 11, 5), "expense")

        data = self.service.get_income_statement_data(date(2024, 10, 1), date(2024, 12, 31), period="month")

        self.assertEqual(data["periods"], [date(2024, 10, 1), date(2024, 11, 1), date(2024, 12, 1)])
        self.assertEqual(data["period_labels"], ["Oct 2024", "Nov 2024", "Dec 2024"])

        income_item = data["income"][0]
        self.assertEqual(income_item["per_period"], [Decimal("1000.00"), Decimal("0"), Decimal("1100.00")])
        self.assertEqual(income_item["amount"], Decimal("2100.00"))

        expense_group = data["expense_groups"][0]
        self.assertEqual(expense_group["per_period"], [Decimal("0"), Decimal("300.00"), Decimal("0")])

        self.assertEqual(data["total_income_per_period"], [Decimal("1000.00"), Decimal("0"), Decimal("1100.00")])
        self.assertEqual(data["total_expenses_per_period"], [Decimal("0"), Decimal("300.00"), Decimal("0")])
        self.assertEqual(data["net_profit_per_period"], [Decimal("1000.00"), Decimal("-300.00"), Decimal("1100.00")])

    def test_income_statement_by_quarter(self):
        """period='quarter' buckets amounts into calendar quarters."""
        self._record(self.income_account, Decimal("1000.00"), date(2024, 1, 15), "income")
        self._record(self.income_account, Decimal("500.00"), date(2024, 3, 20), "income")
        self._record(self.expense_account, Decimal("200.00"), date(2024, 5, 5), "expense")

        data = self.service.get_income_statement_data(date(2024, 1, 1), date(2024, 6, 30), period="quarter")

        self.assertEqual(data["periods"], [date(2024, 1, 1), date(2024, 4, 1)])
        self.assertEqual(data["period_labels"], ["Q1 2024", "Q2 2024"])
        self.assertEqual(data["total_income_per_period"], [Decimal("1500.00"), Decimal("0")])
        self.assertEqual(data["total_expenses_per_period"], [Decimal("0"), Decimal("200.00")])

    def test_income_statement_by_year(self):
        """period='year' buckets amounts into calendar years."""
        self._record(self.income_account, Decimal("1000.00"), date(2023, 6, 15), "income")
        self._record(self.income_account, Decimal("2000.00"), date(2024, 2, 15), "income")

        data = self.service.get_income_statement_data(date(2023, 1, 1), date(2024, 12, 31), period="year")

        self.assertEqual(data["periods"], [date(2023, 1, 1), date(2024, 1, 1)])
        self.assertEqual(data["period_labels"], ["2023", "2024"])
        self.assertEqual(data["total_income_per_period"], [Decimal("1000.00"), Decimal("2000.00")])

    def test_income_statement_without_period_has_no_period_keys(self):
        """Default call keeps periods/per-period lists empty and items free of 'per_period'."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 12, 15), description="Sale")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.income_account, cr_amount=Decimal("100.00")
        )

        data = self.service.get_income_statement_data(date(2024, 12, 1), date(2024, 12, 31))

        self.assertEqual(data["periods"], [])
        self.assertEqual(data["period_labels"], [])
        self.assertEqual(data["total_income_per_period"], [])
        self.assertNotIn("per_period", data["income"][0])
        self.assertNotIn("per_period", data["income_groups"][0])

    def _record_transfer(self, dr_account, cr_account, amount, entry_date, description=""):
        entry = JournalEntry.objects.create(team=self.team, entry_date=entry_date, description=description)
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=dr_account, dr_amount=amount)
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=cr_account, cr_amount=amount)
        return entry

    def test_account_activity_asset_running_balance(self):
        """Asset drill-down carries a starting balance and a running balance per transaction."""
        # Before the period: 500 into Cash
        self._record_transfer(self.asset_account, self.equity_account, Decimal("500.00"), date(2024, 5, 10))
        # In the period: +1000 then -300
        self._record_transfer(self.asset_account, self.income_account, Decimal("1000.00"), date(2024, 6, 5))
        self._record_transfer(self.expense_account, self.asset_account, Decimal("300.00"), date(2024, 6, 20))

        data = self.service.get_account_activity(self.asset_account, date(2024, 6, 1), date(2024, 6, 30))

        self.assertTrue(data["is_balance_account"])
        self.assertEqual(data["starting_balance"], Decimal("500.00"))
        self.assertEqual([txn["balance"] for txn in data["transactions"]], [Decimal("1500.00"), Decimal("1200.00")])
        self.assertEqual(data["total"], Decimal("700.00"))
        self.assertEqual(data["ending_balance"], Decimal("1200.00"))

    def test_account_activity_liability_signed_like_balance_sheet(self):
        """Liability amounts are cr - dr so the ending balance matches the balance sheet figure."""
        # Take a 2000 loan before the period, repay 500 during it
        self._record_transfer(self.asset_account, self.liability_account, Decimal("2000.00"), date(2024, 5, 1))
        self._record_transfer(self.liability_account, self.asset_account, Decimal("500.00"), date(2024, 6, 10))

        data = self.service.get_account_activity(self.liability_account, date(2024, 6, 1), date(2024, 6, 30))

        self.assertEqual(data["starting_balance"], Decimal("2000.00"))
        self.assertEqual(data["transactions"][0]["amount"], Decimal("-500.00"))
        self.assertEqual(data["ending_balance"], Decimal("1500.00"))

        balance_sheet = self.service.get_balance_sheet_data(date(2024, 6, 30))
        self.assertEqual(balance_sheet["liabilities"][0]["amount"], data["ending_balance"])

    def test_account_activity_expense_has_no_running_balance(self):
        """Income/expense drill-downs keep their period-total semantics — no balances."""
        self._record_transfer(self.expense_account, self.asset_account, Decimal("300.00"), date(2024, 6, 20))

        data = self.service.get_account_activity(self.expense_account, date(2024, 6, 1), date(2024, 6, 30))

        self.assertFalse(data["is_balance_account"])
        self.assertIsNone(data["starting_balance"])
        self.assertIsNone(data["ending_balance"])
        self.assertNotIn("balance", data["transactions"][0])

    def test_balance_sheet_no_data(self):
        """Test balance sheet with no transactions."""
        as_of_date = date(2024, 12, 31)
        data = self.service.get_balance_sheet_data(as_of_date)

        self.assertEqual(len(data["assets"]), 0)
        self.assertEqual(len(data["liabilities"]), 0)
        self.assertEqual(len(data["equity"]), 0)
        self.assertEqual(data["total_assets"], Decimal("0"))
        self.assertEqual(data["total_liabilities"], Decimal("0"))
        self.assertEqual(data["total_equity"], Decimal("0"))
        self.assertEqual(data["net_worth"], Decimal("0"))


class IncomeStatementDateParamsTest(TestCase):
    """Tests for income statement date parameter handling (React datepicker)."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="IS Param Team", slug="is-param-team")
        cls.user = CustomUser.objects.create_user(username="isuser", email="is@example.com", password="testpass123")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME)
        cls.asset_account = Account.objects.create(team=cls.team, name="Cash", account_group=cls.asset_group)
        cls.income_account = Account.objects.create(team=cls.team, name="Sales", account_group=cls.income_group)

    def setUp(self):
        self.client.login(username="isuser", password="testpass123")

    def test_date_params_parsed_correctly(self):
        """Test that start_date and end_date URL params are parsed and used."""
        # Create a transaction in the date range
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 6, 15), description="June sale")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("500.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.income_account, cr_amount=Decimal("500.00")
        )

        url = reverse("reports:income_statement", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"start_date": "2024-06-01", "end_date": "2024-06-30"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], date(2024, 6, 1))
        self.assertEqual(response.context["end_date"], date(2024, 6, 30))
        self.assertIsNotNone(response.context["report_data"])
        self.assertEqual(response.context["report_data"]["total_income"], Decimal("500.00"))
        # Grouped data and savings rate are exposed for the template
        self.assertEqual(len(response.context["report_data"]["income_groups"]), 1)
        self.assertEqual(response.context["savings_rate"], Decimal("100"))
        self.assertIsNone(response.context["period"])

    def test_monthly_view_param(self):
        """?view=monthly turns on the per-month breakdown and renders month columns."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 6, 15), description="June sale")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("500.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.income_account, cr_amount=Decimal("500.00")
        )

        url = reverse("reports:income_statement", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"start_date": "2024-05-01", "end_date": "2024-07-31", "view": "monthly"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["period"], "month")
        self.assertEqual(
            response.context["report_data"]["periods"],
            [date(2024, 5, 1), date(2024, 6, 1), date(2024, 7, 1)],
        )
        self.assertContains(response, "Jun 2024")
        # The display toggle preserves the date range in every mode
        self.assertIn("view=monthly", response.context["period_view_qs"]["monthly"])
        self.assertIn("view=quarterly", response.context["period_view_qs"]["quarterly"])
        self.assertIn("view=yearly", response.context["period_view_qs"]["yearly"])
        self.assertIn("start_date=2024-05-01", response.context["total_view_qs"])
        self.assertNotIn("view=monthly", response.context["total_view_qs"])

    def test_quarterly_and_yearly_view_params(self):
        """?view=quarterly and ?view=yearly select the matching period."""
        url = reverse("reports:income_statement", kwargs={"team_slug": self.team.slug})

        response = self.client.get(url, {"start_date": "2024-01-01", "end_date": "2024-12-31", "view": "quarterly"})
        self.assertEqual(response.context["period"], "quarter")
        self.assertContains(response, "Q1 2024")

        response = self.client.get(url, {"start_date": "2024-01-01", "end_date": "2024-12-31", "view": "yearly"})
        self.assertEqual(response.context["period"], "year")

        # Unknown view values fall back to the plain total view
        response = self.client.get(url, {"view": "bogus"})
        self.assertIsNone(response.context["period"])

    def test_no_params_defaults_to_current_month(self):
        """Test that no date params defaults to current month."""
        url = reverse("reports:income_statement", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)

        today = date.today()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], today.replace(day=1))
        self.assertEqual(response.context["end_date"], today)

    def test_invalid_date_params_fall_back_to_defaults(self):
        """Test that invalid date params fall back to current month defaults."""
        url = reverse("reports:income_statement", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"start_date": "invalid", "end_date": "bad"})

        today = date.today()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], today.replace(day=1))
        self.assertEqual(response.context["end_date"], today)


class AccountActivityViewTest(TestCase):
    """Tests for the account activity drill-down view."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="AA View Team", slug="aa-view-team")
        cls.user = CustomUser.objects.create_user(username="aauser", email="aa@example.com", password="testpass123")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.expense_group = AccountGroup.objects.create(team=cls.team, name="Living", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.asset_account = Account.objects.create(team=cls.team, name="Cash", account_group=cls.asset_group)
        cls.expense_account = Account.objects.create(team=cls.team, name="Rent", account_group=cls.expense_group)

    def setUp(self):
        self.client.login(username="aauser", password="testpass123")

    def test_account_activity_renders_with_data(self):
        """Happy path: the drill-down renders transactions and totals for the account."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 6, 15), description="June rent")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, dr_amount=Decimal("1200.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=Decimal("1200.00")
        )

        url = reverse(
            "reports:account_activity",
            kwargs={"team_slug": self.team.slug, "account_id": self.expense_account.pk},
        )
        response = self.client.get(url, {"start_date": "2024-06-01", "end_date": "2024-06-30"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/account_activity.html")
        self.assertEqual(response.context["account"], self.expense_account)
        self.assertEqual(response.context["report_data"]["total"], Decimal("1200.00"))
        self.assertContains(response, "Back to Summary")

    def test_account_activity_shows_contra_account_and_source(self):
        """Each row surfaces the other side of the entry plus its source."""
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2024, 6, 15), description="June rent", source=JournalEntry.SOURCE_IMPORT
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, dr_amount=Decimal("1200.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=Decimal("1200.00")
        )

        url = reverse(
            "reports:account_activity",
            kwargs={"team_slug": self.team.slug, "account_id": self.expense_account.pk},
        )
        response = self.client.get(url, {"start_date": "2024-06-01", "end_date": "2024-06-30"})

        txn = response.context["report_data"]["transactions"][0]
        self.assertEqual(txn["contra_accounts"], [{"name": "Cash", "url": self.asset_account.get_absolute_url()}])
        self.assertEqual(txn["source"], "Import")
        self.assertContains(response, "Cash")

    def test_account_activity_balance_account_shows_chart_and_running_balance(self):
        """Asset drill-down gets balance chart data, a starting-balance row, and a Balance column."""
        prior = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 5, 10), description="Opening")
        JournalLine.objects.create(
            team=self.team, journal_entry=prior, account=self.asset_account, dr_amount=Decimal("500.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=prior, account=self.expense_account, cr_amount=Decimal("500.00")
        )
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 6, 15), description="June rent")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, dr_amount=Decimal("1200.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=Decimal("1200.00")
        )

        url = reverse(
            "reports:account_activity",
            kwargs={"team_slug": self.team.slug, "account_id": self.asset_account.pk},
        )
        response = self.client.get(url, {"start_date": "2024-06-01", "end_date": "2024-06-30"})

        self.assertEqual(response.status_code, 200)
        report_data = response.context["report_data"]
        self.assertTrue(report_data["is_balance_account"])
        self.assertEqual(report_data["starting_balance"], Decimal("500.00"))
        self.assertEqual(report_data["ending_balance"], Decimal("-700.00"))
        chart_data = response.context["balance_chart_data"]
        self.assertEqual(chart_data["start_date"], "2024-06-01")
        self.assertEqual(chart_data["end_date"], "2024-06-30")
        self.assertEqual(chart_data["starting_balance"], 500.0)
        self.assertEqual(chart_data["points"], [{"date": "2024-06-15", "balance": -700.0}])
        self.assertContains(response, "Starting Balance")
        self.assertContains(response, "account-balance-chart")

    def test_account_activity_expense_account_has_no_chart_or_balance(self):
        """Income/expense drill-downs keep the plain table — no chart, no Balance column."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 6, 15), description="June rent")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.expense_account, dr_amount=Decimal("1200.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=Decimal("1200.00")
        )

        url = reverse(
            "reports:account_activity",
            kwargs={"team_slug": self.team.slug, "account_id": self.expense_account.pk},
        )
        response = self.client.get(url, {"start_date": "2024-06-01", "end_date": "2024-06-30"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["balance_chart_data"])
        self.assertNotContains(response, "Starting Balance")
        self.assertNotContains(response, "account-balance-chart")

    def test_account_activity_other_team_account(self):
        """Permission: an account from another team is not exposed."""
        other_team = Team.objects.create(name="Other AA Team", slug="other-aa-team")
        other_group = AccountGroup.objects.create(team=other_team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        other_account = Account.objects.create(team=other_team, name="Secret Cash", account_group=other_group)

        url = reverse(
            "reports:account_activity",
            kwargs={"team_slug": self.team.slug, "account_id": other_account.pk},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["account"])
        self.assertIsNone(response.context["report_data"])
        self.assertNotContains(response, "Secret Cash")

    def test_account_activity_back_to_balance_sheet(self):
        """source=balance_sheet links back to the balance sheet with the as-of date."""
        url = reverse(
            "reports:account_activity",
            kwargs={"team_slug": self.team.slug, "account_id": self.asset_account.pk},
        )
        response = self.client.get(
            url,
            {
                "source": "balance_sheet",
                "as_of_date": "2024-12-31",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Back to Balance Sheet")
        expected_back = reverse("reports:balance_sheet", args=[self.team.slug]) + "?as_of_date=2024-12-31"
        self.assertEqual(response.context["back_url"], expected_back)


class BalanceSheetDateParamsTest(TestCase):
    """Tests for balance sheet date parameter handling (React datepicker)."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="BS Param Team", slug="bs-param-team")
        cls.user = CustomUser.objects.create_user(username="bsuser", email="bs@example.com", password="testpass123")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.equity_group = AccountGroup.objects.create(team=cls.team, name="Equity", account_type=ACCOUNT_TYPE_EQUITY)
        cls.asset_account = Account.objects.create(team=cls.team, name="Cash", account_group=cls.asset_group)
        cls.equity_account = Account.objects.create(
            team=cls.team, name="Retained Earnings", account_group=cls.equity_group
        )

    def setUp(self):
        self.client.login(username="bsuser", password="testpass123")

    def test_as_of_date_param_parsed_correctly(self):
        """Test that as_of_date URL param is parsed and used."""
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 12, 15), description="Capital")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.equity_account, cr_amount=Decimal("1000.00")
        )

        url = reverse("reports:balance_sheet", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"as_of_date": "2024-12-31"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["as_of_date"], date(2024, 12, 31))
        self.assertIsNotNone(response.context["report_data"])
        self.assertEqual(response.context["report_data"]["total_assets"], Decimal("1000.00"))
        # Grouped data and drill-down links are exposed for the template
        self.assertEqual(len(response.context["report_data"]["asset_groups"]), 1)
        self.assertEqual(response.context["debt_ratio"], Decimal("0"))
        self.assertIn("source=balance_sheet", response.context["drill_qs"])
        self.assertIn("as_of_date=2024-12-31", response.context["drill_qs"])

    def test_debt_ratio_computed(self):
        """Liabilities as a percentage of assets is exposed for the summary strip."""
        liability_group = AccountGroup.objects.create(team=self.team, name="Debts", account_type=ACCOUNT_TYPE_LIABILITY)
        liability_account = Account.objects.create(team=self.team, name="Loan", account_group=liability_group)
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 12, 15), description="Loan")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=liability_account, cr_amount=Decimal("250.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.equity_account, cr_amount=Decimal("750.00")
        )

        url = reverse("reports:balance_sheet", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"as_of_date": "2024-12-31"})

        self.assertEqual(response.context["debt_ratio"], Decimal("25"))

    def test_no_params_defaults_to_today(self):
        """Test that no as_of_date param defaults to today."""
        url = reverse("reports:balance_sheet", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["as_of_date"], date.today())

    def test_invalid_date_param_falls_back_to_today(self):
        """Test that invalid as_of_date param falls back to today."""
        url = reverse("reports:balance_sheet", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"as_of_date": "not-a-date"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["as_of_date"], date.today())


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
        form_data = {"start_month": "2024-01", "end_month": "2024-12"}
        form = NetWorthTrendForm(data=form_data)
        self.assertTrue(form.is_valid())

        # Check that parsed dates are added to cleaned_data
        self.assertEqual(form.cleaned_data["start_date"], date(2024, 1, 1))
        self.assertEqual(form.cleaned_data["end_date"], date(2024, 12, 31))

    def test_form_validation_start_after_end(self):
        """Test form validation fails when start month is after end month."""
        form_data = {"start_month": "2024-12", "end_month": "2024-01"}
        form = NetWorthTrendForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)

    def test_form_validation_invalid_month_format(self):
        """Test form validation fails with invalid month format."""
        form_data = {"start_month": "invalid", "end_month": "2024-01"}
        form = NetWorthTrendForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)


class ReportViewsTest(TestCase):
    """Tests for report views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="View Test Team", slug="view-test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)

        # Create account groups and accounts for testing
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.asset_account = Account.objects.create(team=cls.team, name="Cash", account_group=cls.asset_group)

    def setUp(self):
        self.client.login(username="testuser", password="testpass123")

    def test_reports_home_view(self):
        """Test reports home view loads successfully."""
        url = reverse("reports:reports_home", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/reports_home.html")

    def test_income_statement_view_get(self):
        """Test income statement view GET request."""
        url = reverse("reports:income_statement", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/income_statement.html")
        # View uses direct date parameters, not a form
        self.assertIn("report_data", response.context)
        self.assertIn("start_date", response.context)
        self.assertIn("end_date", response.context)

    def test_balance_sheet_view_get(self):
        """Test balance sheet view GET request."""
        url = reverse("reports:balance_sheet", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/balance_sheet.html")
        self.assertIn("report_data", response.context)
        self.assertIn("as_of_date", response.context)

    def test_net_worth_trend_view_get(self):
        """Test net worth trend view GET request."""
        url = reverse("reports:net_worth_trend", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/net_worth_trend.html")
        self.assertIn("report_data", response.context)
        self.assertIn("start_date", response.context)
        self.assertIn("end_date", response.context)

    def test_net_worth_trend_view_with_valid_params(self):
        """Test net worth trend view with valid date parameters."""
        url = reverse("reports:net_worth_trend", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"start_month": "2024-01", "end_month": "2024-12"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context.get("report_data"))

    def test_net_worth_trend_stats_and_chart_data(self):
        """The view exposes summary stats, chart series, and month-over-month changes."""
        income_group = AccountGroup.objects.create(team=self.team, name="Income", account_type=ACCOUNT_TYPE_INCOME)
        income_account = Account.objects.create(team=self.team, name="Sales", account_group=income_group)
        for month, amount in [(1, "1000.00"), (2, "500.00")]:
            entry = JournalEntry.objects.create(
                team=self.team, entry_date=date(2024, month, 15), description=f"Sale {month}"
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal(amount)
            )
            JournalLine.objects.create(
                team=self.team, journal_entry=entry, account=income_account, cr_amount=Decimal(amount)
            )

        url = reverse("reports:net_worth_trend", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"start_month": "2024-01", "end_month": "2024-02"})

        trend_stats = response.context["trend_stats"]
        self.assertEqual(trend_stats["latest"]["net_worth"], Decimal("1500.00"))
        self.assertEqual(trend_stats["change"], Decimal("500.00"))
        self.assertEqual(trend_stats["pct_change"], Decimal("50"))
        self.assertEqual(trend_stats["num_months"], 2)

        chart_data = response.context["chart_data"]
        self.assertEqual(chart_data["labels"], ["2024-01-31", "2024-02-29"])
        self.assertEqual(chart_data["net_worth"], [1000.0, 1500.0])
        self.assertEqual(chart_data["assets"], [1000.0, 1500.0])
        self.assertEqual(chart_data["liabilities"], [0.0, 0.0])

        report_data = response.context["report_data"]
        self.assertIsNone(report_data[0]["change"])
        self.assertEqual(report_data[1]["change"], Decimal("500.00"))

    def test_net_worth_trend_view_with_invalid_params(self):
        """Test net worth trend view with invalid date params falls back to defaults."""
        url = reverse("reports:net_worth_trend", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"start_month": "bad", "end_month": "data"})
        self.assertEqual(response.status_code, 200)
        # Falls back to defaults, still generates report data
        self.assertIsNotNone(response.context.get("report_data"))


class BalanceCompositionTest(TestCase):
    """Tests for the balance composition service data (stacked-area chart)."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Comp Team", slug="comp-team")
        cls.bank_group = AccountGroup.objects.create(team=cls.team, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cls.invest_group = AccountGroup.objects.create(
            team=cls.team, name="Investments", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.card_group = AccountGroup.objects.create(team=cls.team, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        cls.equity_group = AccountGroup.objects.create(team=cls.team, name="Equity", account_type=ACCOUNT_TYPE_EQUITY)
        cls.bank = Account.objects.create(team=cls.team, name="Checking", account_group=cls.bank_group)
        cls.invest = Account.objects.create(team=cls.team, name="Brokerage", account_group=cls.invest_group)
        cls.card = Account.objects.create(team=cls.team, name="Visa", account_group=cls.card_group)
        cls.equity = Account.objects.create(team=cls.team, name="Opening", account_group=cls.equity_group)

    def _entry(self, day, dr_account, cr_account, amount):
        entry = JournalEntry.objects.create(team=self.team, entry_date=day, description="t")
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=dr_account, dr_amount=amount)
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=cr_account, cr_amount=amount)

    def test_composition_running_balances_per_group(self):
        # Opening balance before the range
        self._entry(date(2023, 12, 10), self.bank, self.equity, Decimal("1000.00"))
        # January: move 400 into investments, borrow 200 on the card
        self._entry(date(2024, 1, 15), self.invest, self.bank, Decimal("400.00"))
        self._entry(date(2024, 1, 20), self.bank, self.card, Decimal("200.00"))
        # February: invest another 100
        self._entry(date(2024, 2, 5), self.invest, self.bank, Decimal("100.00"))

        service = ReportService(self.team)
        data = service.get_balance_composition_data(date(2024, 1, 1), date(2024, 2, 29))

        self.assertEqual(data["labels"], ["2024-01-31", "2024-02-29"])
        by_name = {s["name"]: s["values"] for s in data["asset_groups"]}
        self.assertEqual(by_name["Banks"], [800.0, 700.0])
        self.assertEqual(by_name["Investments"], [400.0, 500.0])
        self.assertEqual(len(data["liability_groups"]), 1)
        self.assertEqual(data["liability_groups"][0]["name"], "Cards")
        self.assertEqual(data["liability_groups"][0]["values"], [200.0, 200.0])

    def test_composition_drops_zero_groups_and_sorts_by_final_balance(self):
        self._entry(date(2024, 1, 10), self.bank, self.equity, Decimal("100.00"))
        self._entry(date(2024, 1, 12), self.invest, self.equity, Decimal("900.00"))

        service = ReportService(self.team)
        data = service.get_balance_composition_data(date(2024, 1, 1), date(2024, 1, 31))

        self.assertEqual([s["name"] for s in data["asset_groups"]], ["Investments", "Banks"])
        self.assertEqual(data["liability_groups"], [])


class CashFlowViewTest(TestCase):
    """Tests for the cash flow report view."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="CF Team", slug="cf-team")
        cls.user = CustomUser.objects.create_user(username="cfuser", email="cf@example.com", password="testpass123")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME)
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.asset_account = Account.objects.create(team=cls.team, name="Cash", account_group=cls.asset_group)
        cls.income_account = Account.objects.create(team=cls.team, name="Salary", account_group=cls.income_group)
        cls.expense_account = Account.objects.create(team=cls.team, name="Rent", account_group=cls.expense_group)

    def setUp(self):
        self.client.login(username="cfuser", password="testpass123")

    def test_cash_flow_months_and_stats(self):
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 1, 5), description="Pay")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("3000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.income_account, cr_amount=Decimal("3000.00")
        )
        entry2 = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 2, 1), description="Rent")
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.expense_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=entry2, account=self.asset_account, cr_amount=Decimal("1000.00")
        )

        url = reverse("reports:cash_flow", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"start_month": "2024-01", "end_month": "2024-02"})

        self.assertEqual(response.status_code, 200)
        months = response.context["months"]
        self.assertEqual(len(months), 2)
        self.assertEqual(months[0]["income"], Decimal("3000.00"))
        self.assertEqual(months[0]["net"], Decimal("3000.00"))
        self.assertEqual(months[1]["expenses"], Decimal("1000.00"))
        self.assertEqual(months[1]["net"], Decimal("-1000.00"))

        stats = response.context["stats"]
        self.assertEqual(stats["net"], Decimal("2000.00"))
        self.assertEqual(stats["avg_net"], Decimal("1000.00"))

        chart_data = response.context["chart_data"]
        self.assertEqual(chart_data["income"], [3000.0, 0.0])
        self.assertEqual(chart_data["expenses"], [0.0, 1000.0])
        self.assertEqual(chart_data["net"], [3000.0, -1000.0])

    def test_cash_flow_requires_team_membership(self):
        self.client.logout()
        url = reverse("reports:cash_flow", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertNotEqual(response.status_code, 200)


class BudgetVsActualViewTest(TestCase):
    """Tests for the budget vs actual report view."""

    @classmethod
    def setUpTestData(cls):
        from apps.budget.models import Budget

        cls.team = Team.objects.create(name="BVA Team", slug="bva-team")
        cls.user = CustomUser.objects.create_user(username="bvauser", email="bva@example.com", password="testpass123")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.expense_group = AccountGroup.objects.create(team=cls.team, name="Living", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.asset_account = Account.objects.create(team=cls.team, name="Cash", account_group=cls.asset_group)
        cls.rent = Account.objects.create(team=cls.team, name="Rent", account_group=cls.expense_group)
        cls.food = Account.objects.create(team=cls.team, name="Food", account_group=cls.expense_group)
        cls.fun = Account.objects.create(team=cls.team, name="Fun", account_group=cls.expense_group)

        Budget.objects.create(team=cls.team, month=date(2024, 6, 1), category=cls.rent, budget_amount=Decimal("1500"))
        Budget.objects.create(team=cls.team, month=date(2024, 6, 1), category=cls.food, budget_amount=Decimal("400"))

    def setUp(self):
        self.client.login(username="bvauser", password="testpass123")

    def _spend(self, account, amount, day):
        entry = JournalEntry.objects.create(team=self.team, entry_date=day, description="spend")
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=account, dr_amount=amount)
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=amount)

    def test_budget_vs_actual_rows(self):
        self._spend(self.rent, Decimal("1500.00"), date(2024, 6, 1))  # exactly on budget
        self._spend(self.food, Decimal("500.00"), date(2024, 6, 10))  # over budget
        self._spend(self.fun, Decimal("50.00"), date(2024, 6, 15))  # unbudgeted

        url = reverse("reports:budget_vs_actual", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"month": "2024-06"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["month"], date(2024, 6, 1))
        groups = response.context["expense_groups"]
        self.assertEqual(len(groups), 1)
        rows = {row["account"].name: row for row in groups[0]["rows"]}

        self.assertFalse(rows["Rent"]["over"])
        self.assertEqual(rows["Rent"]["pct"], 100.0)
        self.assertTrue(rows["Food"]["over"])
        self.assertEqual(rows["Food"]["remaining"], Decimal("-100.00"))
        self.assertTrue(rows["Fun"]["unbudgeted"])
        self.assertIsNone(rows["Fun"]["pct"])

        totals = response.context["expense_totals"]
        self.assertEqual(totals["budget"], Decimal("1900"))
        self.assertEqual(totals["actual"], Decimal("2050.00"))
        self.assertEqual(totals["over_count"], 2)  # Food over, Fun unbudgeted-with-spend

    def test_budgeted_category_without_activity_still_listed(self):
        url = reverse("reports:budget_vs_actual", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"month": "2024-06"})

        rows = {row["account"].name: row for row in response.context["expense_groups"][0]["rows"]}
        self.assertEqual(rows["Rent"]["actual"], Decimal("0"))
        self.assertEqual(rows["Rent"]["pct_capped"], 0)


class GoalProgressViewTest(TestCase):
    """Tests for the goal progress report view."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="GP Team", slug="gp-team")
        cls.user = CustomUser.objects.create_user(username="gpuser", email="gp@example.com", password="testpass123")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)

    def setUp(self):
        self.client.login(username="gpuser", password="testpass123")

    def test_goal_progress_chart_and_pace(self):
        from apps.budget.models import Goal, GoalAllocation

        today_month = date.today().replace(day=1)

        def add_months(month, n):
            total = month.year * 12 + (month.month - 1) + n
            return date(total // 12, total % 12 + 1, 1)

        goal = Goal.objects.create(
            team=self.team,
            name="Vacation",
            target_amount=Decimal("1200.00"),
            target_date=add_months(today_month, 4),
        )
        GoalAllocation.objects.create(
            team=self.team, goal=goal, month=add_months(today_month, -2), amount=Decimal("100")
        )
        GoalAllocation.objects.create(
            team=self.team, goal=goal, month=add_months(today_month, -1), amount=Decimal("100")
        )

        url = reverse("reports:goal_progress", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        chart_data = response.context["chart_data"]
        # Axis runs from the first allocation to the target date
        self.assertEqual(chart_data["labels"][0], add_months(today_month, -2).isoformat())
        self.assertEqual(chart_data["labels"][-1], add_months(today_month, 4).isoformat())

        goal_series = chart_data["goals"][0]
        # Cumulative record: 100 then 200, carried through the current month
        self.assertEqual(goal_series["actual"][0], 100.0)
        self.assertEqual(goal_series["actual"][1], 200.0)
        self.assertEqual(goal_series["actual"][2], 200.0)  # today
        self.assertIsNone(goal_series["actual"][3])  # future months are not "actual"
        # Projection anchors at today's saved amount and ends at the target
        self.assertEqual(goal_series["projection"][2], 200.0)
        self.assertEqual(goal_series["projection"][-1], 1200.0)

        row = response.context["goal_rows"][0]
        self.assertEqual(row["saved"], Decimal("200"))
        self.assertEqual(row["months_left"], 4)
        self.assertEqual(row["needed_per_month"], Decimal("250"))

    def test_goal_progress_no_goals(self):
        url = reverse("reports:goal_progress", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["goal_rows"], [])
        self.assertIsNone(response.context["chart_data"])


class IncomeStatementTrendChartTest(TestCase):
    """The spending-trends chart data is exposed only with a period breakdown."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Trend Team", slug="trend-team")
        cls.user = CustomUser.objects.create_user(username="tuser", email="t@example.com", password="testpass123")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.expense_group = AccountGroup.objects.create(team=cls.team, name="Living", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.asset_account = Account.objects.create(team=cls.team, name="Cash", account_group=cls.asset_group)
        cls.rent = Account.objects.create(team=cls.team, name="Rent", account_group=cls.expense_group)

    def setUp(self):
        self.client.login(username="tuser", password="testpass123")
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 6, 1), description="rent")
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=self.rent, dr_amount=Decimal("1000"))
        JournalLine.objects.create(
            team=self.team, journal_entry=entry, account=self.asset_account, cr_amount=Decimal("1000")
        )

    def test_trend_chart_data_with_monthly_view(self):
        url = reverse("reports:income_statement", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"start_date": "2024-05-01", "end_date": "2024-07-31", "view": "monthly"})

        trend = response.context["trend_chart_data"]
        self.assertEqual(trend["labels"], ["May 2024", "Jun 2024", "Jul 2024"])
        self.assertEqual(trend["expense_groups"], [{"name": "Living", "values": [0.0, 1000.0, 0.0]}])

    def test_no_trend_chart_data_without_period(self):
        url = reverse("reports:income_statement", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url, {"start_date": "2024-06-01", "end_date": "2024-06-30"})
        self.assertIsNone(response.context["trend_chart_data"])
