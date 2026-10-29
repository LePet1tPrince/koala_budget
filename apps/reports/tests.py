"""
Tests for reports app.
Tests services and views.
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
from apps.budget.ledger import set_budget
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .services import ReportService


class ReportServiceTest(TestCase):
    """Tests for ReportService."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Report Test Team", slug="report-test-team")
        cls.book = cls.team.default_book
        # These tests budget income before it arrives.
        cls.book.budget_future_income = True
        cls.book.save()

        # Create account groups
        cls.asset_group = AccountGroup.objects.create(book=cls.book, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.liability_group = AccountGroup.objects.create(
            book=cls.book, name="Liabilities", account_type=ACCOUNT_TYPE_LIABILITY
        )
        cls.equity_group = AccountGroup.objects.create(book=cls.book, name="Equity", account_type=ACCOUNT_TYPE_EQUITY)
        cls.income_group = AccountGroup.objects.create(book=cls.book, name="Income", account_type=ACCOUNT_TYPE_INCOME)
        cls.expense_group = AccountGroup.objects.create(
            book=cls.book, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )

        # Create accounts
        cls.asset_account = Account.objects.create(book=cls.book, name="Cash", account_group=cls.asset_group)
        cls.liability_account = Account.objects.create(book=cls.book, name="Loans", account_group=cls.liability_group)
        cls.equity_account = Account.objects.create(
            book=cls.book, name="Retained Earnings", account_group=cls.equity_group
        )
        cls.income_account = Account.objects.create(book=cls.book, name="Sales Revenue", account_group=cls.income_group)
        cls.expense_account = Account.objects.create(
            book=cls.book, name="Operating Expenses", account_group=cls.expense_group
        )

    def setUp(self):
        self.service = ReportService(self.book)

    def test_income_statement_data_basic(self):
        """Test basic income statement data calculation."""
        # Create income transaction
        entry = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 12, 15), description="Sales revenue")
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.income_account, cr_amount=Decimal("1000.00")
        )

        # Create expense transaction
        entry2 = JournalEntry.objects.create(
            book=self.book, entry_date=date(2024, 12, 20), description="Operating expenses"
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry2, account=self.expense_account, dr_amount=Decimal("300.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry2, account=self.asset_account, cr_amount=Decimal("300.00")
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
            book=self.book, entry_date=date(2024, 12, 15), description="Initial capital"
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("5000.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.equity_account, cr_amount=Decimal("5000.00")
        )

        # Create liability transaction
        entry2 = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 12, 20), description="Loan taken")
        JournalLine.objects.create(
            book=self.book, journal_entry=entry2, account=self.asset_account, dr_amount=Decimal("2000.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry2, account=self.liability_account, cr_amount=Decimal("2000.00")
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
        entry1 = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 1, 15), description="Jan capital")
        JournalLine.objects.create(
            book=self.book, journal_entry=entry1, account=self.asset_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry1, account=self.equity_account, cr_amount=Decimal("1000.00")
        )

        # February transaction
        entry2 = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 2, 15), description="Feb loan")
        JournalLine.objects.create(
            book=self.book, journal_entry=entry2, account=self.asset_account, dr_amount=Decimal("500.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry2, account=self.liability_account, cr_amount=Decimal("500.00")
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
        entry = JournalEntry.objects.create(book=self.book, entry_date=date(2023, 6, 15), description="Old capital")
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("2000.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.equity_account, cr_amount=Decimal("2000.00")
        )
        entry2 = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 3, 10), description="Mar loan")
        JournalLine.objects.create(
            book=self.book, journal_entry=entry2, account=self.asset_account, dr_amount=Decimal("300.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry2, account=self.liability_account, cr_amount=Decimal("300.00")
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
        entry = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 1, 15), description="Capital")
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("1000.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.equity_account, cr_amount=Decimal("1000.00")
        )
        voided = JournalEntry.objects.create(
            book=self.book, entry_date=date(2024, 1, 20), description="Void", status=JournalEntry.STATUS_VOID
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=voided, account=self.asset_account, dr_amount=Decimal("9999.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=voided, account=self.equity_account, cr_amount=Decimal("9999.00")
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
        housing_group = AccountGroup.objects.create(book=self.book, name="Housing", account_type=ACCOUNT_TYPE_EXPENSE)
        rent_account = Account.objects.create(book=self.book, name="Rent", account_group=housing_group)
        utilities_account = Account.objects.create(book=self.book, name="Utilities", account_group=housing_group)

        def spend(account, amount, day):
            entry = JournalEntry.objects.create(
                book=self.book, entry_date=date(2024, 12, day), description=f"Spend {account.name}"
            )
            JournalLine.objects.create(book=self.book, journal_entry=entry, account=account, dr_amount=amount)
            JournalLine.objects.create(
                book=self.book, journal_entry=entry, account=self.asset_account, cr_amount=amount
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
        entry = JournalEntry.objects.create(book=self.book, entry_date=when, description="tx")
        if kind == "income":
            JournalLine.objects.create(
                book=self.book, journal_entry=entry, account=self.asset_account, dr_amount=amount
            )
            JournalLine.objects.create(book=self.book, journal_entry=entry, account=account, cr_amount=amount)
        else:
            JournalLine.objects.create(book=self.book, journal_entry=entry, account=account, dr_amount=amount)
            JournalLine.objects.create(
                book=self.book, journal_entry=entry, account=self.asset_account, cr_amount=amount
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
        entry = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 12, 15), description="Sale")
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.asset_account, dr_amount=Decimal("100.00")
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.income_account, cr_amount=Decimal("100.00")
        )

        data = self.service.get_income_statement_data(date(2024, 12, 1), date(2024, 12, 31))

        self.assertEqual(data["periods"], [])
        self.assertEqual(data["period_labels"], [])
        self.assertEqual(data["total_income_per_period"], [])
        self.assertNotIn("per_period", data["income"][0])
        self.assertNotIn("per_period", data["income_groups"][0])

    def _record_transfer(self, dr_account, cr_account, amount, entry_date, description=""):
        entry = JournalEntry.objects.create(book=self.book, entry_date=entry_date, description=description)
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=dr_account, dr_amount=amount)
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=cr_account, cr_amount=amount)
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

    def test_budget_vs_actual_chart_expense_with_rollover(self):
        """Expense chart: per-month budgeted/actual, Available rolls forward from pre-range months."""

        set_budget(self.book, self.expense_account, date(2024, 5, 1), Decimal("100.00"))
        set_budget(self.book, self.expense_account, date(2024, 6, 1), Decimal("100.00"))
        set_budget(self.book, self.expense_account, date(2024, 7, 1), Decimal("150.00"))
        # May: spend 80 of 100 (rolls 20 into June); June: spend 120
        self._record_transfer(self.expense_account, self.asset_account, Decimal("80.00"), date(2024, 5, 10))
        self._record_transfer(self.expense_account, self.asset_account, Decimal("120.00"), date(2024, 6, 15))

        data = self.service.get_budget_vs_actual_chart_data(self.expense_account, date(2024, 6, 1), date(2024, 7, 31))

        self.assertEqual(data["labels"], ["Jun 2024", "Jul 2024"])
        self.assertEqual(data["budgeted"], [100.0, 150.0])
        self.assertEqual(data["actual"], [120.0, 0.0])
        # June: 20 (May leftover) + 100 - 120 = 0; July: 0 + 150 - 0 = 150
        self.assertEqual(data["available"], [0.0, 150.0])
        self.assertEqual(data["account_type"], "expense")

    def test_budget_vs_actual_chart_income_sign(self):
        """Income chart: Available = Actual - Budget (earning above plan is positive)."""

        set_budget(self.book, self.income_account, date(2024, 6, 1), Decimal("1000.00"))
        self._record_transfer(self.asset_account, self.income_account, Decimal("1200.00"), date(2024, 6, 5))

        data = self.service.get_budget_vs_actual_chart_data(self.income_account, date(2024, 6, 1), date(2024, 6, 30))

        self.assertEqual(data["budgeted"], [1000.0])
        self.assertEqual(data["actual"], [1200.0])
        self.assertEqual(data["available"], [200.0])
        self.assertEqual(data["account_type"], "income")

    def test_budget_vs_actual_chart_none_for_balance_accounts(self):
        """Balance-type accounts get no budget chart."""
        self.assertIsNone(
            self.service.get_budget_vs_actual_chart_data(self.asset_account, date(2024, 6, 1), date(2024, 6, 30))
        )
        self.assertIsNone(
            self.service.get_budget_vs_actual_chart_data(self.liability_account, date(2024, 6, 1), date(2024, 6, 30))
        )

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


class ReportViewsTest(TestCase):
    """Tests for report views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="View Test Team", slug="view-test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)

        # Create account groups and accounts for testing
        cls.asset_group = AccountGroup.objects.create(book=cls.book, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.asset_account = Account.objects.create(book=cls.book, name="Cash", account_group=cls.asset_group)

    def setUp(self):
        self.client.login(username="testuser", password="testpass123")

    def test_reports_home_view(self):
        """Test reports home view loads successfully."""
        url = reverse("reports:reports_home", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/reports_home.html")

    def test_reports_home_lists_the_four_reports(self):
        """Reports home links Monthly Review and the three reports, and none of the retired ones."""
        url = reverse("reports:reports_home", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        for testid in ("monthly-review", "spending", "net-worth", "budget-goals"):
            self.assertContains(response, f'data-testid="report-link-{testid}"')
        self.assertContains(response, 'data-testid="report-link-', count=4)

    def test_report_nav_lists_the_four_reports(self):
        """The sidebar's Reports popout carries the same four reports, the open one highlighted."""
        url = reverse("reports:net_worth", args=self.book.url_args)
        response = self.client.get(url)
        for testid in ("nav-monthly-review", "nav-report-spending", "nav-report-net-worth", "nav-report-budget-goals"):
            self.assertContains(response, f'data-testid="{testid}"')
        # The menu renders twice: the desktop sidebar and the mobile dropdown.
        self.assertContains(response, 'data-testid="nav-report-', count=6)
        self.assertContains(response, 'side-link-active" data-testid="nav-report-net-worth"')

    def test_retired_reports_are_gone(self):
        from django.urls import NoReverseMatch

        for name in (
            "income_statement",
            "account_activity",
            "balance_sheet",
            "net_worth_trend",
            "cash_flow",
            "budget_vs_actual",
            "goal_progress",
            "dollar_map",
        ):
            with self.assertRaises(NoReverseMatch):
                reverse(f"reports:{name}", args=self.book.url_args)


class BalanceCompositionTest(TestCase):
    """Tests for the balance composition service data (stacked-area chart)."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Comp Team", slug="comp-team")
        cls.book = cls.team.default_book
        cls.bank_group = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cls.invest_group = AccountGroup.objects.create(
            book=cls.book, name="Investments", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.card_group = AccountGroup.objects.create(book=cls.book, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        cls.equity_group = AccountGroup.objects.create(book=cls.book, name="Equity", account_type=ACCOUNT_TYPE_EQUITY)
        cls.bank = Account.objects.create(book=cls.book, name="Checking", account_group=cls.bank_group)
        cls.invest = Account.objects.create(book=cls.book, name="Brokerage", account_group=cls.invest_group)
        cls.card = Account.objects.create(book=cls.book, name="Visa", account_group=cls.card_group)
        cls.equity = Account.objects.create(book=cls.book, name="Opening", account_group=cls.equity_group)

    def _entry(self, day, dr_account, cr_account, amount):
        entry = JournalEntry.objects.create(book=self.book, entry_date=day, description="t")
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=dr_account, dr_amount=amount)
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=cr_account, cr_amount=amount)

    def test_composition_running_balances_per_group(self):
        # Opening balance before the range
        self._entry(date(2023, 12, 10), self.bank, self.equity, Decimal("1000.00"))
        # January: move 400 into investments, borrow 200 on the card
        self._entry(date(2024, 1, 15), self.invest, self.bank, Decimal("400.00"))
        self._entry(date(2024, 1, 20), self.bank, self.card, Decimal("200.00"))
        # February: invest another 100
        self._entry(date(2024, 2, 5), self.invest, self.bank, Decimal("100.00"))

        service = ReportService(self.book)
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

        service = ReportService(self.book)
        data = service.get_balance_composition_data(date(2024, 1, 1), date(2024, 1, 31))

        self.assertEqual([s["name"] for s in data["asset_groups"]], ["Investments", "Banks"])
        self.assertEqual(data["liability_groups"], [])
