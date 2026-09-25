"""
Tests for accounts app.
Tests models, views, forms, and API endpoints.
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.books.context import current_book
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.services.opening import OpeningRow, create_opening_balances
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

from .forms import AccountForm, AccountGroupForm, PayeeForm
from .models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    Account,
    AccountGroup,
    Payee,
)


class AccountGroupModelTest(TestCase):
    """Tests for AccountGroup model."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book

    def test_create_account_group(self):
        """Test creating an account group."""
        with current_book(self.book):
            account_group = AccountGroup.objects.create(
                book=self.book,
                name="Cash Accounts",
                account_type=ACCOUNT_TYPE_ASSET,
                description="Cash and equivalents",
            )
            self.assertEqual(account_group.name, "Cash Accounts")
            self.assertEqual(account_group.account_type, ACCOUNT_TYPE_ASSET)
            self.assertEqual(str(account_group), "Cash Accounts")

    def test_account_group_ordering(self):
        """Test that account groups are ordered by name."""
        with current_book(self.book):
            AccountGroup.objects.create(book=self.book, name="Zebra", account_type=ACCOUNT_TYPE_ASSET)
            AccountGroup.objects.create(book=self.book, name="Alpha", account_type=ACCOUNT_TYPE_ASSET)
            groups = list(AccountGroup.for_book.all())
            self.assertEqual(groups[0].name, "Alpha")
            self.assertEqual(groups[1].name, "Zebra")

    def test_account_group_unique_together(self):
        """Test that team and name must be unique together."""
        AccountGroup.objects.create(book=self.book, name="Duplicate", account_type=ACCOUNT_TYPE_ASSET)
        with self.assertRaises(IntegrityError):
            AccountGroup.objects.create(book=self.book, name="Duplicate", account_type=ACCOUNT_TYPE_ASSET)

    def test_get_absolute_url(self):
        """Test get_absolute_url method."""
        account_group = AccountGroup.objects.create(book=self.book, name="Test", account_type=ACCOUNT_TYPE_ASSET)
        expected_url = reverse(
            "accounts:accountgroup_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account_group.pk},
        )
        self.assertEqual(account_group.get_absolute_url(), expected_url)


class AccountModelTest(TestCase):
    """Tests for Account model."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.account_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )

    def test_create_account(self):
        """Test creating an account."""
        with current_book(self.book):
            account = Account.objects.create(book=self.book, name="Checking Account", account_group=self.account_group)
            self.assertEqual(account.name, "Checking Account")
            self.assertEqual(str(account), "Checking Account")

    def test_account_ordering(self):
        """Test that accounts are ordered by name."""
        with current_book(self.book):
            Account.objects.create(book=self.book, name="Zebra Account", account_group=self.account_group)
            Account.objects.create(book=self.book, name="Alpha Account", account_group=self.account_group)
            accounts = list(Account.for_book.all())
            self.assertEqual(accounts[0].name, "Alpha Account")
            self.assertEqual(accounts[1].name, "Zebra Account")

    def test_account_has_feed_default(self):
        """Test that has_feed defaults to False."""
        account = Account.objects.create(book=self.book, name="Test Account", account_group=self.account_group)
        self.assertFalse(account.has_feed)

    def test_get_absolute_url(self):
        """Test get_absolute_url method."""
        account = Account.objects.create(book=self.book, name="Test Account", account_group=self.account_group)
        expected_url = reverse(
            "accounts:account_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        self.assertEqual(account.get_absolute_url(), expected_url)


class PayeeModelTest(TestCase):
    """Tests for Payee model."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book

    def test_create_payee(self):
        """Test creating a payee."""
        with current_book(self.book):
            payee = Payee.objects.create(book=self.book, name="Amazon")
            self.assertEqual(payee.name, "Amazon")
            self.assertEqual(str(payee), "Amazon")

    def test_payee_ordering(self):
        """Test that payees are ordered by name."""
        with current_book(self.book):
            Payee.objects.create(book=self.book, name="Zebra Corp")
            Payee.objects.create(book=self.book, name="Alpha Inc")
            payees = list(Payee.for_book.all())
            self.assertEqual(payees[0].name, "Alpha Inc")
            self.assertEqual(payees[1].name, "Zebra Corp")

    def test_payee_unique_together(self):
        """Test that team and name must be unique together."""
        Payee.objects.create(book=self.book, name="Duplicate")
        with self.assertRaises(IntegrityError):
            Payee.objects.create(book=self.book, name="Duplicate")

    def test_get_absolute_url(self):
        """Test get_absolute_url method."""
        payee = Payee.objects.create(book=self.book, name="Test Payee")
        expected_url = reverse(
            "accounts:payee_detail", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": payee.pk}
        )
        self.assertEqual(payee.get_absolute_url(), expected_url)


class AccountGroupFormTest(TestCase):
    """Tests for AccountGroupForm."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book

    def test_valid_form(self):
        """Test form with valid data."""
        form_data = {"name": "Test Group", "account_type": ACCOUNT_TYPE_ASSET, "description": "Test description"}
        form = AccountGroupForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_missing_required_fields(self):
        """Test form with missing required fields."""
        form = AccountGroupForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)
        self.assertIn("account_type", form.errors)


class AccountFormTest(TestCase):
    """Tests for AccountForm."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.account_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )

    def test_valid_form(self):
        """Test form with valid data."""
        form_data = {
            "name": "Test Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
            "has_feed": False,
        }
        with current_book(self.book):
            form = AccountForm(data=form_data, book=self.book)
            self.assertTrue(form.is_valid())

    def test_missing_required_fields(self):
        """Test form with missing required fields."""
        with current_book(self.book):
            form = AccountForm(data={}, book=self.book)
            self.assertFalse(form.is_valid())
            self.assertIn("name", form.errors)

    def test_account_type_mismatch(self):
        """Test form validation when account_group doesn't match account_type."""
        expense_group = AccountGroup.objects.create(
            book=self.book, name="Expense Group", account_type=ACCOUNT_TYPE_EXPENSE
        )
        form_data = {
            "name": "Test Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": expense_group.pk,
            "has_feed": False,
        }
        with current_book(self.book):
            form = AccountForm(data=form_data, book=self.book)
            self.assertFalse(form.is_valid())
            # The form filters account_group choices by account_type, so selecting a mismatched
            # group will result in an "invalid choice" error on the account_group field
            self.assertIn("account_group", form.errors)

    def test_form_filters_account_groups_by_type(self):
        """Test that form filters account groups based on selected account_type."""
        expense_group = AccountGroup.objects.create(
            book=self.book, name="Expense Group", account_type=ACCOUNT_TYPE_EXPENSE
        )
        form_data = {
            "name": "Test Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
        }
        with current_book(self.book):
            form = AccountForm(data=form_data, book=self.book)
            # The queryset should only include asset account groups
            account_group_ids = list(form.fields["account_group"].queryset.values_list("pk", flat=True))
            self.assertIn(self.account_group.pk, account_group_ids)
            self.assertNotIn(expense_group.pk, account_group_ids)

    def test_create_form_hides_has_feed(self):
        """Test that create form does not expose has_feed field."""
        with current_book(self.book):
            form = AccountForm(data={}, book=self.book, is_create=True)
            self.assertNotIn("has_feed", form.fields)

    def test_create_form_hides_institution_for_expense(self):
        """Test that create form hides institution for non-asset/liability types."""
        form_data = {
            "name": "Test Account",
            "account_type": ACCOUNT_TYPE_EXPENSE,
            "account_group": self.account_group.pk,
        }
        with current_book(self.book):
            form = AccountForm(data=form_data, book=self.book, is_create=True)
            self.assertNotIn("institution", form.fields)


class PayeeFormTest(TestCase):
    """Tests for PayeeForm."""

    def test_valid_form(self):
        """Test form with valid data."""
        form_data = {"name": "Test Payee"}
        form = PayeeForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_missing_required_fields(self):
        """Test form with missing required fields."""
        form = PayeeForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)


class AccountsHomeViewTest(TestCase):
    """Tests for AccountsHomeView."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_MEMBER})

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_accounts_home_view_requires_login(self):
        """Test that accounts home view requires login."""
        self.client.logout()
        url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_accounts_home_view_success(self):
        """Test accounts home view with authenticated user."""
        url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/accounts_home.html")

    def test_accounts_home_groups_accounts_by_type(self):
        """Board props group accounts by type, in balance-sheet order, with balances."""
        with current_book(self.book):
            asset_group = AccountGroup.objects.create(book=self.book, name="Cash", account_type=ACCOUNT_TYPE_ASSET)
            expense_group = AccountGroup.objects.create(
                book=self.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE
            )
            Account.objects.create(book=self.book, name="Groceries", account_group=expense_group)
            Account.objects.create(book=self.book, name="Checking", account_group=asset_group)

        url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        sections = response.context["manage_props"]["types"]
        self.assertEqual([s["key"] for s in sections], ["asset", "liability", "income", "expense", "goal", "equity"])
        by_key = {s["key"]: s for s in sections}
        asset_accounts = by_key[ACCOUNT_TYPE_ASSET]["groups"][0]["accounts"]
        self.assertEqual([a["name"] for a in asset_accounts], ["Checking"])
        self.assertEqual(asset_accounts[0]["balance"], "0")


class AccountGroupViewTest(TestCase):
    """Tests for AccountGroup views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_account_group_list_view(self):
        """Test account group list view."""
        with current_book(self.book):
            AccountGroup.objects.create(book=self.book, name="Test Group", account_type=ACCOUNT_TYPE_ASSET)

        url = reverse("accounts:accountgroup_list", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Group")

    def test_account_group_create_view_get(self):
        """Test account group create view GET request."""
        url = reverse("accounts:accountgroup_create", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], AccountGroupForm)

    def test_account_group_create_view_post(self):
        """Test account group create view POST request."""
        url = reverse("accounts:accountgroup_create", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        data = {"name": "New Group", "account_type": ACCOUNT_TYPE_ASSET, "description": "Test"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)  # Redirect after success
        with current_book(self.book):
            self.assertTrue(AccountGroup.for_book.filter(name="New Group").exists())

    def test_account_group_detail_view(self):
        """Test account group detail view."""
        account_group = AccountGroup.objects.create(book=self.book, name="Test Group", account_type=ACCOUNT_TYPE_ASSET)
        url = reverse(
            "accounts:accountgroup_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account_group.pk},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object"], account_group)

    def test_account_group_update_view(self):
        """Test account group update view."""
        account_group = AccountGroup.objects.create(book=self.book, name="Old Name", account_type=ACCOUNT_TYPE_ASSET)
        url = reverse(
            "accounts:accountgroup_update",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account_group.pk},
        )
        data = {"name": "New Name", "account_type": ACCOUNT_TYPE_ASSET, "description": "Updated"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        account_group.refresh_from_db()
        self.assertEqual(account_group.name, "New Name")

    def test_account_group_delete_view(self):
        """Test account group delete view."""
        account_group = AccountGroup.objects.create(book=self.book, name="To Delete", account_type=ACCOUNT_TYPE_ASSET)
        url = reverse(
            "accounts:accountgroup_delete",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account_group.pk},
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        with current_book(self.book):
            self.assertFalse(AccountGroup.for_book.filter(pk=account_group.pk).exists())


class AccountViewTest(TestCase):
    """Tests for Account views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.account_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_accounts_home_view(self):
        """Test the accounts home (board) view includes accounts in its props."""
        with current_book(self.book):
            Account.objects.create(book=self.book, name="Checking", account_group=self.account_group)

        url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Checking")
        sections = {section["key"]: section for section in response.context["manage_props"]["types"]}
        group_names = [g["name"] for g in sections[ACCOUNT_TYPE_ASSET]["groups"]]
        self.assertIn("Bank Accounts", group_names)

    def test_account_create_view_get(self):
        """Test account create view GET request."""
        url = reverse("accounts:account_create", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], AccountForm)

    def test_account_create_view_post(self):
        """Test account create view POST request."""
        url = reverse("accounts:account_create", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        data = {
            "name": "New Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        with current_book(self.book):
            self.assertTrue(Account.for_book.filter(name="New Account").exists())

    def test_account_create_sets_has_feed_for_asset(self):
        """Test that creating an asset account automatically sets has_feed=True."""
        url = reverse("accounts:account_create", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        data = {
            "name": "Savings Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
        }
        self.client.post(url, data)
        with current_book(self.book):
            account = Account.for_book.get(name="Savings Account")
            self.assertTrue(account.has_feed)

    def test_account_create_sets_has_feed_false_for_expense(self):
        """Test that creating an expense account automatically sets has_feed=False."""
        expense_group = AccountGroup.objects.create(book=self.book, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE)
        url = reverse("accounts:account_create", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        data = {
            "name": "Office Supplies",
            "account_type": ACCOUNT_TYPE_EXPENSE,
            "account_group": expense_group.pk,
        }
        self.client.post(url, data)
        with current_book(self.book):
            account = Account.for_book.get(name="Office Supplies")
            self.assertFalse(account.has_feed)

    def test_account_detail_view(self):
        """Test account detail view."""
        account = Account.objects.create(book=self.book, name="Test Account", account_group=self.account_group)
        url = reverse(
            "accounts:account_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object"], account)

    def test_account_detail_view_activity_section(self):
        """The detail view embeds the activity section: report data, chart data, and date range."""
        from datetime import date
        from decimal import Decimal

        from apps.journal.models import JournalEntry, JournalLine

        expense_group = AccountGroup.objects.create(book=self.book, name="Living", account_type=ACCOUNT_TYPE_EXPENSE)
        account = Account.objects.create(book=self.book, name="Detail Cash", account_group=self.account_group)
        expense = Account.objects.create(book=self.book, name="Detail Rent", account_group=expense_group)

        prior = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 5, 10), description="Opening")
        JournalLine.objects.create(book=self.book, journal_entry=prior, account=account, dr_amount=Decimal("500.00"))
        JournalLine.objects.create(book=self.book, journal_entry=prior, account=expense, cr_amount=Decimal("500.00"))
        entry = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 6, 15), description="Rent")
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=expense, dr_amount=Decimal("1200.00"))
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=account, cr_amount=Decimal("1200.00"))

        url = reverse(
            "accounts:account_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        response = self.client.get(url, {"start_date": "2024-06-01", "end_date": "2024-06-30"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], date(2024, 6, 1))
        self.assertEqual(response.context["end_date"], date(2024, 6, 30))
        report_data = response.context["report_data"]
        self.assertEqual(report_data["starting_balance"], Decimal("500.00"))
        self.assertEqual(report_data["ending_balance"], Decimal("-700.00"))
        chart_data = response.context["balance_chart_data"]
        self.assertEqual(chart_data["points"], [{"date": "2024-06-15", "balance": -700.0}])
        self.assertContains(response, "Starting Balance")
        self.assertContains(response, "account-balance-chart")
        self.assertContains(response, "date-range-picker")

    def test_account_detail_view_expense_budget_chart(self):
        """Expense account detail embeds the budget-vs-actual chart instead of the balance chart."""
        from datetime import date
        from decimal import Decimal

        from apps.budget.models import Budget
        from apps.journal.models import JournalEntry, JournalLine

        expense_group = AccountGroup.objects.create(book=self.book, name="Bills", account_type=ACCOUNT_TYPE_EXPENSE)
        asset = Account.objects.create(book=self.book, name="Chart Cash", account_group=self.account_group)
        expense = Account.objects.create(book=self.book, name="Chart Rent", account_group=expense_group)
        Budget.objects.create(
            book=self.book, category=expense, month=date(2024, 6, 1), budget_amount=Decimal("1500.00")
        )
        entry = JournalEntry.objects.create(book=self.book, entry_date=date(2024, 6, 15), description="Rent")
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=expense, dr_amount=Decimal("1200.00"))
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=asset, cr_amount=Decimal("1200.00"))

        url = reverse(
            "accounts:account_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": expense.pk},
        )
        response = self.client.get(url, {"start_date": "2024-06-01", "end_date": "2024-06-30"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["balance_chart_data"])
        budget_chart = response.context["budget_chart_data"]
        self.assertEqual(budget_chart["budgeted"], [1500.0])
        self.assertEqual(budget_chart["actual"], [1200.0])
        self.assertEqual(budget_chart["available"], [300.0])
        self.assertContains(response, "account-budget-chart")
        self.assertNotContains(response, "account-balance-chart")

    def test_account_detail_view_defaults_to_current_year(self):
        """Without date params the activity section defaults to the current year."""
        from datetime import date

        account = Account.objects.create(book=self.book, name="Default Range", account_group=self.account_group)
        url = reverse(
            "accounts:account_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        response = self.client.get(url)

        today = date.today()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], today.replace(month=1, day=1))
        self.assertEqual(response.context["end_date"], today)

    def test_account_update_view(self):
        """Test account update view."""
        account = Account.objects.create(book=self.book, name="Old Name", account_group=self.account_group)
        url = reverse(
            "accounts:account_update",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        data = {
            "name": "New Name",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
            "has_feed": True,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        account.refresh_from_db()
        self.assertEqual(account.name, "New Name")
        self.assertTrue(account.has_feed)

    def test_account_delete_view(self):
        """Test account delete view."""
        account = Account.objects.create(book=self.book, name="To Delete", account_group=self.account_group)
        url = reverse(
            "accounts:account_delete",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        with current_book(self.book):
            self.assertFalse(Account.for_book.filter(pk=account.pk).exists())

    def test_account_delete_view_get_redirects_to_detail(self):
        """Deletion is confirmed via a dialog on the detail page, not a separate page -- a GET bounces back to it."""
        account = Account.objects.create(book=self.book, name="Still Here", account_group=self.account_group)
        url = reverse(
            "accounts:account_delete",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        response = self.client.get(url)
        detail_url = reverse(
            "accounts:account_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        self.assertRedirects(response, detail_url, fetch_redirect_response=False)
        self.assertTrue(Account.objects.filter(pk=account.pk).exists())

    def test_account_detail_view_has_delete_confirmation_dialog(self):
        """The detail page carries its own delete-confirmation dialog rather than linking to a separate page."""
        account = Account.objects.create(book=self.book, name="Has Dialog", account_group=self.account_group)
        url = reverse(
            "accounts:account_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        response = self.client.get(url)
        self.assertContains(response, 'id="delete-account-modal"')
        self.assertContains(response, 'id="delete-account-btn"')
        delete_url = reverse(
            "accounts:account_delete",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account.pk},
        )
        self.assertContains(response, f'action="{delete_url}"')


class PayeeViewTest(TestCase):
    """Tests for Payee views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_payee_list_view(self):
        """Test payee list view."""
        with current_book(self.book):
            Payee.objects.create(book=self.book, name="Amazon")

        url = reverse("accounts:payee_list", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Amazon")

    def test_payee_create_view_get(self):
        """Test payee create view GET request."""
        url = reverse("accounts:payee_create", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], PayeeForm)

    def test_payee_create_view_post(self):
        """Test payee create view POST request."""
        url = reverse("accounts:payee_create", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        data = {"name": "New Payee"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        with current_book(self.book):
            self.assertTrue(Payee.for_book.filter(name="New Payee").exists())

    def test_payee_detail_view(self):
        """Test payee detail view."""
        payee = Payee.objects.create(book=self.book, name="Test Payee")
        url = reverse(
            "accounts:payee_detail", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": payee.pk}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object"], payee)

    def test_payee_update_view(self):
        """Test payee update view."""
        payee = Payee.objects.create(book=self.book, name="Old Name")
        url = reverse(
            "accounts:payee_update", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": payee.pk}
        )
        data = {"name": "New Name"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        payee.refresh_from_db()
        self.assertEqual(payee.name, "New Name")

    def test_payee_delete_view(self):
        """Test payee delete view."""
        payee = Payee.objects.create(book=self.book, name="To Delete")
        url = reverse(
            "accounts:payee_delete", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": payee.pk}
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        with current_book(self.book):
            self.assertFalse(Payee.for_book.filter(pk=payee.pk).exists())


class TeamIsolationTest(TestCase):
    """Tests for team isolation in accounts app."""

    @classmethod
    def setUpTestData(cls):
        cls.team1 = Team.objects.create(name="Team 1", slug="team-1")
        cls.book1 = cls.team1.default_book
        cls.team2 = Team.objects.create(name="Team 2", slug="team-2")
        cls.book2 = cls.team2.default_book
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team1.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.team2.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def test_account_groups_isolated_by_team(self):
        """Test that account groups are isolated by team."""
        with current_book(self.book1):
            AccountGroup.objects.create(book=self.book1, name="Team 1 Group", account_type=ACCOUNT_TYPE_ASSET)

        with current_book(self.book2):
            AccountGroup.objects.create(book=self.book2, name="Team 2 Group", account_type=ACCOUNT_TYPE_ASSET)

        with current_book(self.book1):
            groups = list(AccountGroup.for_book.all())
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].name, "Team 1 Group")

        with current_book(self.book2):
            groups = list(AccountGroup.for_book.all())
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].name, "Team 2 Group")

    def test_accounts_isolated_by_team(self):
        """Test that accounts are isolated by team."""
        group1 = AccountGroup.objects.create(book=self.book1, name="Group 1", account_type=ACCOUNT_TYPE_ASSET)
        group2 = AccountGroup.objects.create(book=self.book2, name="Group 2", account_type=ACCOUNT_TYPE_ASSET)

        with current_book(self.book1):
            Account.objects.create(book=self.book1, name="Team 1 Account", account_group=group1)

        with current_book(self.book2):
            Account.objects.create(book=self.book2, name="Team 2 Account", account_group=group2)

        with current_book(self.book1):
            accounts = list(Account.for_book.all())
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0].name, "Team 1 Account")

        with current_book(self.book2):
            accounts = list(Account.for_book.all())
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0].name, "Team 2 Account")

    def test_payees_isolated_by_team(self):
        """Test that payees are isolated by team."""
        with current_book(self.book1):
            Payee.objects.create(book=self.book1, name="Team 1 Payee")

        with current_book(self.book2):
            Payee.objects.create(book=self.book2, name="Team 2 Payee")

        with current_book(self.book1):
            payees = list(Payee.for_book.all())
            self.assertEqual(len(payees), 1)
            self.assertEqual(payees[0].name, "Team 1 Payee")

        with current_book(self.book2):
            payees = list(Payee.for_book.all())
            self.assertEqual(len(payees), 1)
            self.assertEqual(payees[0].name, "Team 2 Payee")


class AccountRedirectTest(TestCase):
    """Tests for post-save/post-delete redirects in Account views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.account_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.account = Account.objects.create(book=cls.book, name="Checking", account_group=cls.account_group)

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_update_view_redirects_to_detail(self):
        """Saving an edit redirects to the account detail page."""
        url = reverse(
            "accounts:account_update",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": self.account.pk},
        )
        data = {
            "name": "Checking",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
            "has_feed": False,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        detail_url = reverse(
            "accounts:account_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": self.account.pk},
        )
        self.assertRedirects(response, detail_url, fetch_redirect_response=False)

    def test_delete_view_redirects_to_accounts_home(self):
        """Deleting an account redirects to the accounts home board."""
        account_to_delete = Account.objects.create(book=self.book, name="To Delete", account_group=self.account_group)
        url = reverse(
            "accounts:account_delete",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account_to_delete.pk},
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        home_url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        self.assertRedirects(response, home_url, fetch_redirect_response=False)

    def test_delete_view_removes_opening_balance_and_account(self):
        """An account whose only journal activity is its own opening balance can be deleted."""
        equity_group = AccountGroup.objects.create(
            book=self.book, name="Equity", account_type=ACCOUNT_TYPE_EQUITY, is_system=True
        )
        Account.objects.create(
            book=self.book, name="Reconciliation Adjustments", account_group=equity_group, is_system=True
        )
        account_to_delete = Account.objects.create(book=self.book, name="Savings", account_group=self.account_group)
        create_opening_balances(
            self.book, [OpeningRow(account=account_to_delete, amount=Decimal("100.00"))], date.today()
        )
        self.assertTrue(JournalLine.objects.filter(account=account_to_delete).exists())

        url = reverse(
            "accounts:account_delete",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account_to_delete.pk},
        )
        response = self.client.post(url)

        home_url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        self.assertRedirects(response, home_url, fetch_redirect_response=False)
        self.assertFalse(Account.objects.filter(pk=account_to_delete.pk).exists())
        self.assertFalse(JournalLine.objects.filter(account_id=account_to_delete.pk).exists())

    def test_delete_view_blocks_account_with_real_transactions(self):
        """An account with a real (non-opening-balance) transaction cannot be deleted."""
        account_to_delete = Account.objects.create(book=self.book, name="Savings", account_group=self.account_group)
        expense_group = AccountGroup.objects.create(
            book=self.book, name="Groceries Group", account_type=ACCOUNT_TYPE_EXPENSE
        )
        expense_account = Account.objects.create(book=self.book, name="Groceries", account_group=expense_group)
        entry = JournalEntry.objects.create(
            book=self.book,
            entry_date=date.today(),
            description="Grocery run",
            status=JournalEntry.STATUS_POSTED,
        )
        JournalLine.objects.create(
            book=self.book,
            journal_entry=entry,
            account=account_to_delete,
            dr_amount=Decimal("0"),
            cr_amount=Decimal("50.00"),
        )
        JournalLine.objects.create(
            book=self.book,
            journal_entry=entry,
            account=expense_account,
            dr_amount=Decimal("50.00"),
            cr_amount=Decimal("0"),
        )

        url = reverse(
            "accounts:account_delete",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account_to_delete.pk},
        )
        response = self.client.post(url, follow=True)

        detail_url = reverse(
            "accounts:account_detail",
            kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, "pk": account_to_delete.pk},
        )
        self.assertRedirects(response, detail_url)
        self.assertTrue(Account.objects.filter(pk=account_to_delete.pk).exists())
        messages_list = list(response.context["messages"])
        self.assertTrue(any("Please delete all associated transactions" in str(m) for m in messages_list))
        self.assertTrue(any("modal" in m.extra_tags for m in messages_list))


class AccountsBoardApiTest(TestCase):
    """Tests for the drag-and-drop board JSON API (reorder / move / inline create)."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.other_team = Team.objects.create(name="Other Team", slug="other-team")
        cls.other_book = cls.other_team.default_book
        cls.other_user = CustomUser.objects.create_user(username="other@example.com", password="testpass123")
        cls.other_team.members.add(cls.other_user, through_defaults={"role": ROLE_ADMIN})

        cls.bank_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET, sort_order=0
        )
        cls.invest_group = AccountGroup.objects.create(
            book=cls.book, name="Investments", account_type=ACCOUNT_TYPE_ASSET, sort_order=1
        )
        cls.expense_group = AccountGroup.objects.create(
            book=cls.book, name="Living", account_type=ACCOUNT_TYPE_EXPENSE, sort_order=0
        )
        cls.checking = Account.objects.create(
            book=cls.book, name="Checking", account_group=cls.bank_group, sort_order=0
        )
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=cls.bank_group, sort_order=1)
        cls.groceries = Account.objects.create(
            book=cls.book, name="Groceries", account_group=cls.expense_group, sort_order=0
        )
        cls.other_group = AccountGroup.objects.create(
            book=cls.other_book, name="Other Bank", account_type=ACCOUNT_TYPE_ASSET
        )

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def _post(self, url_name, payload):
        url = reverse(f"accounts:{url_name}", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        return self.client.post(url, payload, content_type="application/json")

    def test_reorder_accounts_within_group(self):
        response = self._post(
            "api_reorder_accounts",
            {"groups": [{"group_id": self.bank_group.pk, "account_ids": [self.savings.pk, self.checking.pk]}]},
        )
        self.assertEqual(response.status_code, 200)
        self.savings.refresh_from_db()
        self.checking.refresh_from_db()
        self.assertEqual(self.savings.sort_order, 0)
        self.assertEqual(self.checking.sort_order, 1)

    def test_move_account_to_other_group_same_type(self):
        response = self._post(
            "api_reorder_accounts",
            {
                "groups": [
                    {"group_id": self.bank_group.pk, "account_ids": [self.checking.pk]},
                    {"group_id": self.invest_group.pk, "account_ids": [self.savings.pk]},
                ]
            },
        )
        self.assertEqual(response.status_code, 200)
        self.savings.refresh_from_db()
        self.assertEqual(self.savings.account_group, self.invest_group)
        self.assertEqual(self.savings.sort_order, 0)

    def test_move_account_across_types_is_rejected(self):
        response = self._post(
            "api_reorder_accounts",
            {"groups": [{"group_id": self.expense_group.pk, "account_ids": [self.checking.pk]}]},
        )
        self.assertEqual(response.status_code, 400)
        self.checking.refresh_from_db()
        self.assertEqual(self.checking.account_group, self.bank_group)

    def test_reorder_rejects_other_teams_objects(self):
        response = self._post(
            "api_reorder_accounts",
            {"groups": [{"group_id": self.other_group.pk, "account_ids": [self.checking.pk]}]},
        )
        self.assertEqual(response.status_code, 400)

    def test_reorder_requires_membership(self):
        self.client.login(username="other@example.com", password="testpass123")
        url = reverse(
            "accounts:api_reorder_accounts", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug}
        )
        response = self.client.post(
            url,
            {"groups": [{"group_id": self.bank_group.pk, "account_ids": [self.checking.pk]}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_reorder_groups(self):
        response = self._post(
            "api_reorder_groups",
            {"account_type": ACCOUNT_TYPE_ASSET, "group_ids": [self.invest_group.pk, self.bank_group.pk]},
        )
        self.assertEqual(response.status_code, 200)
        self.invest_group.refresh_from_db()
        self.bank_group.refresh_from_db()
        self.assertEqual(self.invest_group.sort_order, 0)
        self.assertEqual(self.bank_group.sort_order, 1)

    def test_reorder_groups_rejects_wrong_type(self):
        response = self._post(
            "api_reorder_groups",
            {"account_type": ACCOUNT_TYPE_ASSET, "group_ids": [self.expense_group.pk]},
        )
        self.assertEqual(response.status_code, 400)

    def test_create_account_appends_to_group(self):
        response = self._post("api_create_account", {"name": "Chequing 2", "group_id": self.bank_group.pk})
        self.assertEqual(response.status_code, 201)
        account = Account.objects.get(book=self.book, name="Chequing 2")
        self.assertEqual(account.account_group, self.bank_group)
        self.assertEqual(account.sort_order, 2)  # after Checking (0) and Savings (1)
        self.assertTrue(account.has_feed)  # asset accounts get a feed
        self.assertEqual(response.json()["account"]["name"], "Chequing 2")

    def test_create_expense_account_has_no_feed(self):
        response = self._post("api_create_account", {"name": "Utilities", "group_id": self.expense_group.pk})
        self.assertEqual(response.status_code, 201)
        account = Account.objects.get(book=self.book, name="Utilities")
        self.assertFalse(account.has_feed)

    def test_create_account_duplicate_name_rejected(self):
        response = self._post("api_create_account", {"name": "Checking", "group_id": self.invest_group.pk})
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["error"])

    def test_create_group_appends_to_type(self):
        response = self._post("api_create_group", {"name": "Property", "account_type": ACCOUNT_TYPE_ASSET})
        self.assertEqual(response.status_code, 201)
        group = AccountGroup.objects.get(book=self.book, name="Property")
        self.assertEqual(group.account_type, ACCOUNT_TYPE_ASSET)
        self.assertEqual(group.sort_order, 2)  # after Bank Accounts (0) and Investments (1)

    def test_create_group_duplicate_name_rejected(self):
        response = self._post("api_create_group", {"name": "Bank Accounts", "account_type": ACCOUNT_TYPE_ASSET})
        self.assertEqual(response.status_code, 400)

    def test_set_feed_turns_inbox_off_and_on(self):
        self.checking.has_feed = True
        self.checking.save()
        response = self._post("api_set_feed", {"account_id": self.checking.pk, "has_feed": False})
        self.assertEqual(response.status_code, 200)
        self.checking.refresh_from_db()
        self.assertFalse(self.checking.has_feed)

        response = self._post("api_set_feed", {"account_id": self.checking.pk, "has_feed": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["hasFeed"])
        self.checking.refresh_from_db()
        self.assertTrue(self.checking.has_feed)

    def test_set_feed_refuses_expense_account(self):
        response = self._post("api_set_feed", {"account_id": self.groceries.pk, "has_feed": True})
        self.assertEqual(response.status_code, 400)
        self.groceries.refresh_from_db()
        self.assertFalse(self.groceries.has_feed)

    def test_set_feed_rejects_bad_body_and_other_books_account(self):
        self.assertEqual(
            self._post("api_set_feed", {"account_id": self.checking.pk, "has_feed": "no"}).status_code, 400
        )
        other = Account.objects.create(
            book=self.other_book, name="Theirs", account_group=self.other_group, has_feed=True
        )
        response = self._post("api_set_feed", {"account_id": other.pk, "has_feed": False})
        self.assertEqual(response.status_code, 400)
        other.refresh_from_db()
        self.assertTrue(other.has_feed)

    def test_set_feed_requires_membership(self):
        self.client.login(username="other@example.com", password="testpass123")
        response = self._post("api_set_feed", {"account_id": self.checking.pk, "has_feed": True})
        self.assertEqual(response.status_code, 404)

    def test_board_props_mark_feedable_accounts(self):
        url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug})
        types = self.client.get(url).context["manage_props"]["types"]
        rows = {a["name"]: a for t in types for g in t["groups"] for a in g["accounts"]}
        self.assertTrue(rows["Checking"]["canHaveFeed"])
        self.assertFalse(rows["Groceries"]["canHaveFeed"])

    def test_custom_order_flows_into_default_queryset(self):
        """Account.Meta.ordering follows group sort_order then account sort_order."""
        self._post(
            "api_reorder_accounts",
            {"groups": [{"group_id": self.bank_group.pk, "account_ids": [self.savings.pk, self.checking.pk]}]},
        )
        self._post(
            "api_reorder_groups",
            {"account_type": ACCOUNT_TYPE_ASSET, "group_ids": [self.invest_group.pk, self.bank_group.pk]},
        )
        names = list(
            Account.objects.filter(book=self.book, account_group__account_type=ACCOUNT_TYPE_ASSET).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(names, ["Savings", "Checking"])


class ManagementPagesTest(TestCase):
    """Groups, payees and institutions pages: guarded deletes, duplicate names, detail content."""

    @classmethod
    def setUpTestData(cls):
        from .models import ACCOUNT_TYPE_LIABILITY, Institution

        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.bank = Institution.objects.create(book=cls.book, name="TD")
        cls.assets = AccountGroup.objects.create(book=cls.book, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        cls.cards = AccountGroup.objects.create(book=cls.book, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        cls.food = AccountGroup.objects.create(book=cls.book, name="Food", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.chequing = Account.objects.create(
            book=cls.book, name="Chequing", account_group=cls.assets, institution=cls.bank
        )
        cls.card = Account.objects.create(book=cls.book, name="Visa", account_group=cls.cards, institution=cls.bank)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=cls.food)
        cls.metro = Payee.objects.create(book=cls.book, name="Metro")
        # $80 of groceries on the card: the card owes 80, the bank holds nothing
        entry = JournalEntry.objects.create(
            book=cls.book, entry_date=date(2026, 3, 5), payee=cls.metro, description="Food", status="posted"
        )
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=cls.groceries, dr_amount=Decimal("80"))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=cls.card, cr_amount=Decimal("80"))

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def url(self, name, *args):
        return reverse(f"accounts:{name}", args=[*self.book.url_args, *args])

    def test_deleting_group_with_accounts_is_refused_not_500(self):
        response = self.client.post(self.url("accountgroup_delete", self.assets.pk))
        self.assertRedirects(response, self.assets.get_absolute_url(), fetch_redirect_response=False)
        self.assertTrue(AccountGroup.objects.filter(pk=self.assets.pk).exists())

    def test_deleting_payee_in_use_is_refused_not_500(self):
        response = self.client.post(self.url("payee_delete", self.metro.pk))
        self.assertRedirects(response, self.metro.get_absolute_url(), fetch_redirect_response=False)
        self.assertTrue(Payee.objects.filter(pk=self.metro.pk).exists())

    def test_deleting_unused_payee_goes_to_list(self):
        unused = Payee.objects.create(book=self.book, name="Nobody")
        response = self.client.post(self.url("payee_delete", unused.pk))
        self.assertRedirects(response, self.url("payee_list"), fetch_redirect_response=False)
        self.assertFalse(Payee.objects.filter(pk=unused.pk).exists())

    def test_deleting_institution_unlinks_its_accounts(self):
        self.client.post(self.url("institution_delete", self.bank.pk))
        self.chequing.refresh_from_db()
        self.assertIsNone(self.chequing.institution)

    def test_duplicate_names_are_form_errors_not_500(self):
        for name, data in (
            ("payee_create", {"name": "Metro"}),
            ("institution_create", {"name": "TD"}),
            ("accountgroup_create", {"name": "Bank", "account_type": ACCOUNT_TYPE_ASSET, "description": ""}),
        ):
            with self.subTest(name):
                response = self.client.post(self.url(name), data)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "already exists")

    def test_renaming_to_own_name_is_allowed(self):
        response = self.client.post(self.url("payee_update", self.metro.pk), {"name": "Metro"})
        self.assertRedirects(response, self.metro.get_absolute_url(), fetch_redirect_response=False)

    def test_group_type_is_locked_while_it_has_accounts(self):
        self.client.post(
            self.url("accountgroup_update", self.assets.pk),
            {"name": "Bank", "account_type": ACCOUNT_TYPE_EXPENSE, "description": ""},
        )
        self.assets.refresh_from_db()
        self.assertEqual(self.assets.account_type, ACCOUNT_TYPE_ASSET)

    def test_institution_detail_nets_what_is_owed(self):
        response = self.client.get(self.url("institution_detail", self.bank.pk))
        rows = {row["account"].name: row["amount"] for row in response.context["rows"]}
        self.assertEqual(rows["Visa"], Decimal("80"))  # owed, shown positive
        self.assertEqual(response.context["net_balance"], Decimal("-80"))

    def test_expense_group_shows_this_years_activity(self):
        response = self.client.get(self.url("accountgroup_detail", self.food.pk))
        self.assertEqual(response.context["amount_label"], "This year")

    def test_payee_pages_show_usage_and_link_to_transactions(self):
        response = self.client.get(self.url("payee_list"))
        self.assertContains(response, "1 transaction")
        response = self.client.get(self.url("payee_detail", self.metro.pk))
        self.assertEqual(len(response.context["recent"]), 1)
        self.assertEqual(response.context["recent"][0]["amount"], Decimal("80"))
        self.assertIn("f_payee=Metro", response.context["transactions_url"])

    def test_transactions_page_opens_filtered_by_payee(self):
        url = reverse("journal:transactions_home", args=self.book.url_args)
        response = self.client.get(url, {"f_payee": ["Metro", "Unknown"]})
        self.assertEqual(response.context["initial_filters"], {"payee": [{"value": "Metro", "label": "Metro"}]})

    def test_liability_balance_reads_as_owed(self):
        response = self.client.get(self.card.get_absolute_url())
        self.assertEqual(response.context["current_balance"]["label"], "Balance owed")
        self.assertEqual(response.context["current_balance"]["amount"], Decimal("80"))

    def test_sections_highlight_their_sidebar_item(self):
        pages = (("accountgroup_list", "groups"), ("payee_list", "payees"), ("institution_list", "institutions"))
        for name, section in pages:
            with self.subTest(name):
                self.assertEqual(self.client.get(self.url(name)).context["accounts_section"], section)


class ReturnToNavigationTest(TestCase):
    """A page opened with ?return_to links back there, through edit and cancel."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.group = AccountGroup.objects.create(book=cls.book, name="Food", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.account = Account.objects.create(book=cls.book, name="Groceries", account_group=cls.group)
        cls.report = reverse("reports:account_activity", args=[*cls.book.url_args, cls.account.pk]) + "?source=x"

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_back_link_defaults_to_parent(self):
        response = self.client.get(self.account.get_absolute_url())
        self.assertEqual(response.context["back"]["url"], reverse("accounts:accounts_home", args=self.book.url_args))
        self.assertEqual(response.context["back"]["label"], "Back to Accounts")

    def test_back_link_returns_to_report(self):
        response = self.client.get(self.account.get_absolute_url(), {"return_to": self.report})
        self.assertEqual(response.context["back"], {"url": self.report, "label": "Back to Groceries report"})

    def test_back_link_labels_group_page(self):
        response = self.client.get(self.account.get_absolute_url(), {"return_to": self.group.get_absolute_url()})
        self.assertEqual(response.context["back"]["label"], "Back to Food")

    def test_off_site_return_to_is_ignored(self):
        for bad in ("https://evil.example/", "//evil.example/", "javascript:alert(1)"):
            with self.subTest(bad):
                response = self.client.get(self.account.get_absolute_url(), {"return_to": bad})
                self.assertEqual(response.context["back"]["label"], "Back to Accounts")

    def test_edit_keeps_return_to_through_save(self):
        url = reverse("accounts:account_update", args=[*self.book.url_args, self.account.pk])
        response = self.client.post(
            f"{url}?return_to={self.report}",
            {"name": "Food shopping", "account_type": ACCOUNT_TYPE_EXPENSE, "account_group": self.group.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(self.account.get_absolute_url() + "?return_to="))

    def test_edit_cancel_goes_to_detail_not_board(self):
        url = reverse("accounts:account_update", args=[*self.book.url_args, self.account.pk])
        response = self.client.get(url)
        self.assertEqual(response.context["cancel_url"], self.account.get_absolute_url())

    def test_create_from_group_returns_to_group(self):
        url = reverse("accounts:account_create", args=self.book.url_args)
        group_url = self.group.get_absolute_url()
        response = self.client.get(url, {"return_to": group_url})
        self.assertEqual(response.context["cancel_url"], group_url)
        response = self.client.post(
            f"{url}?return_to={group_url}",
            {"name": "Snacks", "account_type": ACCOUNT_TYPE_EXPENSE, "account_group": self.group.pk},
        )
        created = Account.objects.get(book=self.book, name="Snacks")
        self.assertTrue(response["Location"].startswith(created.get_absolute_url() + "?return_to="))

    def test_activity_links_carry_the_page_as_return_to(self):
        other = Account.objects.create(book=self.book, name="Visa", account_group=self.group)
        entry = JournalEntry.objects.create(book=self.book, entry_date=date.today(), description="x", status="posted")
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=self.account, dr_amount=Decimal("5"))
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=other, cr_amount=Decimal("5"))
        response = self.client.get(self.account.get_absolute_url())
        self.assertContains(response, f'href="{other.get_absolute_url()}?return_to=')
