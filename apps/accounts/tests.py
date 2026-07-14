"""
Tests for accounts app.
Tests models, views, forms, and API endpoints.
"""

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

from .forms import AccountForm, AccountGroupForm, PayeeForm
from .models import (
    ACCOUNT_TYPE_ASSET,
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

    def test_create_account_group(self):
        """Test creating an account group."""
        with current_team(self.team):
            account_group = AccountGroup.objects.create(
                team=self.team,
                name="Cash Accounts",
                account_type=ACCOUNT_TYPE_ASSET,
                description="Cash and equivalents",
            )
            self.assertEqual(account_group.name, "Cash Accounts")
            self.assertEqual(account_group.account_type, ACCOUNT_TYPE_ASSET)
            self.assertEqual(str(account_group), "Cash Accounts")

    def test_account_group_ordering(self):
        """Test that account groups are ordered by name."""
        with current_team(self.team):
            AccountGroup.objects.create(team=self.team, name="Zebra", account_type=ACCOUNT_TYPE_ASSET)
            AccountGroup.objects.create(team=self.team, name="Alpha", account_type=ACCOUNT_TYPE_ASSET)
            groups = list(AccountGroup.for_team.all())
            self.assertEqual(groups[0].name, "Alpha")
            self.assertEqual(groups[1].name, "Zebra")

    def test_account_group_unique_together(self):
        """Test that team and name must be unique together."""
        AccountGroup.objects.create(team=self.team, name="Duplicate", account_type=ACCOUNT_TYPE_ASSET)
        with self.assertRaises(IntegrityError):
            AccountGroup.objects.create(team=self.team, name="Duplicate", account_type=ACCOUNT_TYPE_ASSET)

    def test_get_absolute_url(self):
        """Test get_absolute_url method."""
        account_group = AccountGroup.objects.create(team=self.team, name="Test", account_type=ACCOUNT_TYPE_ASSET)
        expected_url = reverse(
            "accounts:accountgroup_detail", kwargs={"team_slug": self.team.slug, "pk": account_group.pk}
        )
        self.assertEqual(account_group.get_absolute_url(), expected_url)


class AccountModelTest(TestCase):
    """Tests for Account model."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.account_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )

    def test_create_account(self):
        """Test creating an account."""
        with current_team(self.team):
            account = Account.objects.create(team=self.team, name="Checking Account", account_group=self.account_group)
            self.assertEqual(account.name, "Checking Account")
            self.assertEqual(str(account), "Checking Account")

    def test_account_ordering(self):
        """Test that accounts are ordered by name."""
        with current_team(self.team):
            Account.objects.create(team=self.team, name="Zebra Account", account_group=self.account_group)
            Account.objects.create(team=self.team, name="Alpha Account", account_group=self.account_group)
            accounts = list(Account.for_team.all())
            self.assertEqual(accounts[0].name, "Alpha Account")
            self.assertEqual(accounts[1].name, "Zebra Account")

    def test_account_has_feed_default(self):
        """Test that has_feed defaults to False."""
        account = Account.objects.create(team=self.team, name="Test Account", account_group=self.account_group)
        self.assertFalse(account.has_feed)

    def test_get_absolute_url(self):
        """Test get_absolute_url method."""
        account = Account.objects.create(team=self.team, name="Test Account", account_group=self.account_group)
        expected_url = reverse("accounts:account_detail", kwargs={"team_slug": self.team.slug, "pk": account.pk})
        self.assertEqual(account.get_absolute_url(), expected_url)


class PayeeModelTest(TestCase):
    """Tests for Payee model."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")

    def test_create_payee(self):
        """Test creating a payee."""
        with current_team(self.team):
            payee = Payee.objects.create(team=self.team, name="Amazon")
            self.assertEqual(payee.name, "Amazon")
            self.assertEqual(str(payee), "Amazon")

    def test_payee_ordering(self):
        """Test that payees are ordered by name."""
        with current_team(self.team):
            Payee.objects.create(team=self.team, name="Zebra Corp")
            Payee.objects.create(team=self.team, name="Alpha Inc")
            payees = list(Payee.for_team.all())
            self.assertEqual(payees[0].name, "Alpha Inc")
            self.assertEqual(payees[1].name, "Zebra Corp")

    def test_payee_unique_together(self):
        """Test that team and name must be unique together."""
        Payee.objects.create(team=self.team, name="Duplicate")
        with self.assertRaises(IntegrityError):
            Payee.objects.create(team=self.team, name="Duplicate")

    def test_get_absolute_url(self):
        """Test get_absolute_url method."""
        payee = Payee.objects.create(team=self.team, name="Test Payee")
        expected_url = reverse("accounts:payee_detail", kwargs={"team_slug": self.team.slug, "pk": payee.pk})
        self.assertEqual(payee.get_absolute_url(), expected_url)


class AccountGroupFormTest(TestCase):
    """Tests for AccountGroupForm."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")

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
        cls.account_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )

    def test_valid_form(self):
        """Test form with valid data."""
        form_data = {
            "name": "Test Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
            "has_feed": False,
        }
        with current_team(self.team):
            form = AccountForm(data=form_data, team=self.team)
            self.assertTrue(form.is_valid())

    def test_missing_required_fields(self):
        """Test form with missing required fields."""
        with current_team(self.team):
            form = AccountForm(data={}, team=self.team)
            self.assertFalse(form.is_valid())
            self.assertIn("name", form.errors)

    def test_account_type_mismatch(self):
        """Test form validation when account_group doesn't match account_type."""
        expense_group = AccountGroup.objects.create(
            team=self.team, name="Expense Group", account_type=ACCOUNT_TYPE_EXPENSE
        )
        form_data = {
            "name": "Test Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": expense_group.pk,
            "has_feed": False,
        }
        with current_team(self.team):
            form = AccountForm(data=form_data, team=self.team)
            self.assertFalse(form.is_valid())
            # The form filters account_group choices by account_type, so selecting a mismatched
            # group will result in an "invalid choice" error on the account_group field
            self.assertIn("account_group", form.errors)

    def test_form_filters_account_groups_by_type(self):
        """Test that form filters account groups based on selected account_type."""
        expense_group = AccountGroup.objects.create(
            team=self.team, name="Expense Group", account_type=ACCOUNT_TYPE_EXPENSE
        )
        form_data = {
            "name": "Test Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
        }
        with current_team(self.team):
            form = AccountForm(data=form_data, team=self.team)
            # The queryset should only include asset account groups
            account_group_ids = list(form.fields["account_group"].queryset.values_list("pk", flat=True))
            self.assertIn(self.account_group.pk, account_group_ids)
            self.assertNotIn(expense_group.pk, account_group_ids)

    def test_create_form_hides_has_feed(self):
        """Test that create form does not expose has_feed field."""
        with current_team(self.team):
            form = AccountForm(data={}, team=self.team, is_create=True)
            self.assertNotIn("has_feed", form.fields)

    def test_create_form_hides_institution_for_expense(self):
        """Test that create form hides institution for non-asset/liability types."""
        form_data = {
            "name": "Test Account",
            "account_type": ACCOUNT_TYPE_EXPENSE,
            "account_group": self.account_group.pk,
        }
        with current_team(self.team):
            form = AccountForm(data=form_data, team=self.team, is_create=True)
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
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_MEMBER})

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_accounts_home_view_requires_login(self):
        """Test that accounts home view requires login."""
        self.client.logout()
        url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_accounts_home_view_success(self):
        """Test accounts home view with authenticated user."""
        url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/accounts_home.html")

    def test_accounts_home_view_context(self):
        """Test that accounts home view includes counts in context."""
        with current_team(self.team):
            AccountGroup.objects.create(team=self.team, name="Test Group", account_type=ACCOUNT_TYPE_ASSET)
            Payee.objects.create(team=self.team, name="Test Payee")

        url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.context["account_groups_count"], 1)
        self.assertEqual(response.context["accounts_count"], 0)
        self.assertEqual(response.context["payees_count"], 1)

    def test_accounts_home_groups_accounts_by_type(self):
        """Accounts are grouped by type, in balance-sheet order, with balances."""
        with current_team(self.team):
            asset_group = AccountGroup.objects.create(team=self.team, name="Cash", account_type=ACCOUNT_TYPE_ASSET)
            expense_group = AccountGroup.objects.create(
                team=self.team, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE
            )
            Account.objects.create(team=self.team, name="Groceries", account_group=expense_group)
            Account.objects.create(team=self.team, name="Checking", account_group=asset_group)

        url = reverse("accounts:accounts_home", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        grouped = response.context["grouped_accounts"]
        self.assertEqual([g["type"] for g in grouped], [ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE])
        self.assertEqual([a.name for a in grouped[0]["accounts"]], ["Checking"])
        self.assertEqual(grouped[0]["accounts"][0].balance, 0)


class AccountGroupViewTest(TestCase):
    """Tests for AccountGroup views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_account_group_list_view(self):
        """Test account group list view."""
        with current_team(self.team):
            AccountGroup.objects.create(team=self.team, name="Test Group", account_type=ACCOUNT_TYPE_ASSET)

        url = reverse("accounts:accountgroup_list", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Group")

    def test_account_group_create_view_get(self):
        """Test account group create view GET request."""
        url = reverse("accounts:accountgroup_create", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], AccountGroupForm)

    def test_account_group_create_view_post(self):
        """Test account group create view POST request."""
        url = reverse("accounts:accountgroup_create", kwargs={"team_slug": self.team.slug})
        data = {"name": "New Group", "account_type": ACCOUNT_TYPE_ASSET, "description": "Test"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)  # Redirect after success
        with current_team(self.team):
            self.assertTrue(AccountGroup.for_team.filter(name="New Group").exists())

    def test_account_group_detail_view(self):
        """Test account group detail view."""
        account_group = AccountGroup.objects.create(team=self.team, name="Test Group", account_type=ACCOUNT_TYPE_ASSET)
        url = reverse("accounts:accountgroup_detail", kwargs={"team_slug": self.team.slug, "pk": account_group.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object"], account_group)

    def test_account_group_update_view(self):
        """Test account group update view."""
        account_group = AccountGroup.objects.create(team=self.team, name="Old Name", account_type=ACCOUNT_TYPE_ASSET)
        url = reverse("accounts:accountgroup_update", kwargs={"team_slug": self.team.slug, "pk": account_group.pk})
        data = {"name": "New Name", "account_type": ACCOUNT_TYPE_ASSET, "description": "Updated"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        account_group.refresh_from_db()
        self.assertEqual(account_group.name, "New Name")

    def test_account_group_delete_view(self):
        """Test account group delete view."""
        account_group = AccountGroup.objects.create(team=self.team, name="To Delete", account_type=ACCOUNT_TYPE_ASSET)
        url = reverse("accounts:accountgroup_delete", kwargs={"team_slug": self.team.slug, "pk": account_group.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        with current_team(self.team):
            self.assertFalse(AccountGroup.for_team.filter(pk=account_group.pk).exists())


class AccountViewTest(TestCase):
    """Tests for Account views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.account_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_account_list_view(self):
        """Test account list view."""
        with current_team(self.team):
            Account.objects.create(team=self.team, name="Checking", account_group=self.account_group)

        url = reverse("accounts:account_list", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Checking")

    def test_account_create_view_get(self):
        """Test account create view GET request."""
        url = reverse("accounts:account_create", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], AccountForm)

    def test_account_create_view_post(self):
        """Test account create view POST request."""
        url = reverse("accounts:account_create", kwargs={"team_slug": self.team.slug})
        data = {
            "name": "New Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        with current_team(self.team):
            self.assertTrue(Account.for_team.filter(name="New Account").exists())

    def test_account_create_sets_has_feed_for_asset(self):
        """Test that creating an asset account automatically sets has_feed=True."""
        url = reverse("accounts:account_create", kwargs={"team_slug": self.team.slug})
        data = {
            "name": "Savings Account",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
        }
        self.client.post(url, data)
        with current_team(self.team):
            account = Account.for_team.get(name="Savings Account")
            self.assertTrue(account.has_feed)

    def test_account_create_sets_has_feed_false_for_expense(self):
        """Test that creating an expense account automatically sets has_feed=False."""
        expense_group = AccountGroup.objects.create(team=self.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE)
        url = reverse("accounts:account_create", kwargs={"team_slug": self.team.slug})
        data = {
            "name": "Office Supplies",
            "account_type": ACCOUNT_TYPE_EXPENSE,
            "account_group": expense_group.pk,
        }
        self.client.post(url, data)
        with current_team(self.team):
            account = Account.for_team.get(name="Office Supplies")
            self.assertFalse(account.has_feed)

    def test_account_detail_view(self):
        """Test account detail view."""
        account = Account.objects.create(team=self.team, name="Test Account", account_group=self.account_group)
        url = reverse("accounts:account_detail", kwargs={"team_slug": self.team.slug, "pk": account.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object"], account)

    def test_account_detail_view_activity_section(self):
        """The detail view embeds the activity section: report data, chart data, and date range."""
        from datetime import date
        from decimal import Decimal

        from apps.journal.models import JournalEntry, JournalLine

        expense_group = AccountGroup.objects.create(team=self.team, name="Living", account_type=ACCOUNT_TYPE_EXPENSE)
        account = Account.objects.create(team=self.team, name="Detail Cash", account_group=self.account_group)
        expense = Account.objects.create(team=self.team, name="Detail Rent", account_group=expense_group)

        prior = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 5, 10), description="Opening")
        JournalLine.objects.create(team=self.team, journal_entry=prior, account=account, dr_amount=Decimal("500.00"))
        JournalLine.objects.create(team=self.team, journal_entry=prior, account=expense, cr_amount=Decimal("500.00"))
        entry = JournalEntry.objects.create(team=self.team, entry_date=date(2024, 6, 15), description="Rent")
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=expense, dr_amount=Decimal("1200.00"))
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=account, cr_amount=Decimal("1200.00"))

        url = reverse("accounts:account_detail", kwargs={"team_slug": self.team.slug, "pk": account.pk})
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

    def test_account_detail_view_defaults_to_current_month(self):
        """Without date params the activity section defaults to the current month."""
        from datetime import date

        account = Account.objects.create(team=self.team, name="Default Range", account_group=self.account_group)
        url = reverse("accounts:account_detail", kwargs={"team_slug": self.team.slug, "pk": account.pk})
        response = self.client.get(url)

        today = date.today()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], today.replace(day=1))
        self.assertEqual(response.context["end_date"], today)

    def test_account_update_view(self):
        """Test account update view."""
        account = Account.objects.create(team=self.team, name="Old Name", account_group=self.account_group)
        url = reverse("accounts:account_update", kwargs={"team_slug": self.team.slug, "pk": account.pk})
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
        account = Account.objects.create(team=self.team, name="To Delete", account_group=self.account_group)
        url = reverse("accounts:account_delete", kwargs={"team_slug": self.team.slug, "pk": account.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        with current_team(self.team):
            self.assertFalse(Account.for_team.filter(pk=account.pk).exists())


class PayeeViewTest(TestCase):
    """Tests for Payee views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_payee_list_view(self):
        """Test payee list view."""
        with current_team(self.team):
            Payee.objects.create(team=self.team, name="Amazon")

        url = reverse("accounts:payee_list", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Amazon")

    def test_payee_create_view_get(self):
        """Test payee create view GET request."""
        url = reverse("accounts:payee_create", kwargs={"team_slug": self.team.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], PayeeForm)

    def test_payee_create_view_post(self):
        """Test payee create view POST request."""
        url = reverse("accounts:payee_create", kwargs={"team_slug": self.team.slug})
        data = {"name": "New Payee"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        with current_team(self.team):
            self.assertTrue(Payee.for_team.filter(name="New Payee").exists())

    def test_payee_detail_view(self):
        """Test payee detail view."""
        payee = Payee.objects.create(team=self.team, name="Test Payee")
        url = reverse("accounts:payee_detail", kwargs={"team_slug": self.team.slug, "pk": payee.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object"], payee)

    def test_payee_update_view(self):
        """Test payee update view."""
        payee = Payee.objects.create(team=self.team, name="Old Name")
        url = reverse("accounts:payee_update", kwargs={"team_slug": self.team.slug, "pk": payee.pk})
        data = {"name": "New Name"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        payee.refresh_from_db()
        self.assertEqual(payee.name, "New Name")

    def test_payee_delete_view(self):
        """Test payee delete view."""
        payee = Payee.objects.create(team=self.team, name="To Delete")
        url = reverse("accounts:payee_delete", kwargs={"team_slug": self.team.slug, "pk": payee.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        with current_team(self.team):
            self.assertFalse(Payee.for_team.filter(pk=payee.pk).exists())


class TeamIsolationTest(TestCase):
    """Tests for team isolation in accounts app."""

    @classmethod
    def setUpTestData(cls):
        cls.team1 = Team.objects.create(name="Team 1", slug="team-1")
        cls.team2 = Team.objects.create(name="Team 2", slug="team-2")
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team1.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.team2.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def test_account_groups_isolated_by_team(self):
        """Test that account groups are isolated by team."""
        with current_team(self.team1):
            AccountGroup.objects.create(team=self.team1, name="Team 1 Group", account_type=ACCOUNT_TYPE_ASSET)

        with current_team(self.team2):
            AccountGroup.objects.create(team=self.team2, name="Team 2 Group", account_type=ACCOUNT_TYPE_ASSET)

        with current_team(self.team1):
            groups = list(AccountGroup.for_team.all())
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].name, "Team 1 Group")

        with current_team(self.team2):
            groups = list(AccountGroup.for_team.all())
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].name, "Team 2 Group")

    def test_accounts_isolated_by_team(self):
        """Test that accounts are isolated by team."""
        group1 = AccountGroup.objects.create(team=self.team1, name="Group 1", account_type=ACCOUNT_TYPE_ASSET)
        group2 = AccountGroup.objects.create(team=self.team2, name="Group 2", account_type=ACCOUNT_TYPE_ASSET)

        with current_team(self.team1):
            Account.objects.create(team=self.team1, name="Team 1 Account", account_group=group1)

        with current_team(self.team2):
            Account.objects.create(team=self.team2, name="Team 2 Account", account_group=group2)

        with current_team(self.team1):
            accounts = list(Account.for_team.all())
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0].name, "Team 1 Account")

        with current_team(self.team2):
            accounts = list(Account.for_team.all())
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0].name, "Team 2 Account")

    def test_payees_isolated_by_team(self):
        """Test that payees are isolated by team."""
        with current_team(self.team1):
            Payee.objects.create(team=self.team1, name="Team 1 Payee")

        with current_team(self.team2):
            Payee.objects.create(team=self.team2, name="Team 2 Payee")

        with current_team(self.team1):
            payees = list(Payee.for_team.all())
            self.assertEqual(len(payees), 1)
            self.assertEqual(payees[0].name, "Team 1 Payee")

        with current_team(self.team2):
            payees = list(Payee.for_team.all())
            self.assertEqual(len(payees), 1)
            self.assertEqual(payees[0].name, "Team 2 Payee")


class AccountReturnTypeTest(TestCase):
    """Tests for return_type filter persistence in Account views."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.account_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.account = Account.objects.create(team=cls.team, name="Checking", account_group=cls.account_group)

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_detail_view_passes_return_type_to_context(self):
        """Test that detail view passes return_type from GET to template context."""
        url = reverse("accounts:account_detail", kwargs={"team_slug": self.team.slug, "pk": self.account.pk})
        response = self.client.get(url, {"return_type": "asset"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["return_type"], "asset")

    def test_detail_view_no_return_type_is_empty_string(self):
        """Test that detail view context has empty return_type when not provided."""
        url = reverse("accounts:account_detail", kwargs={"team_slug": self.team.slug, "pk": self.account.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["return_type"], "")

    def test_update_view_passes_return_type_to_context(self):
        """Test that update view passes return_type from GET to template context."""
        url = reverse("accounts:account_update", kwargs={"team_slug": self.team.slug, "pk": self.account.pk})
        response = self.client.get(url, {"return_type": "asset"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["return_type"], "asset")

    def test_update_view_success_url_with_return_type_redirects_to_filtered_list(self):
        """Test that saving edit with return_type redirects to filtered account list."""
        url = reverse("accounts:account_update", kwargs={"team_slug": self.team.slug, "pk": self.account.pk})
        data = {
            "name": "Checking Updated",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
            "has_feed": False,
            "return_type": "asset",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        list_url = reverse("accounts:account_list", kwargs={"team_slug": self.team.slug})
        self.assertRedirects(response, f"{list_url}?type=asset", fetch_redirect_response=False)
        # Restore name for other tests
        self.account.refresh_from_db()
        self.account.name = "Checking"
        self.account.save()

    def test_update_view_success_url_without_return_type_redirects_to_detail(self):
        """Test that saving edit without return_type redirects to account detail page."""
        url = reverse("accounts:account_update", kwargs={"team_slug": self.team.slug, "pk": self.account.pk})
        data = {
            "name": "Checking",
            "account_type": ACCOUNT_TYPE_ASSET,
            "account_group": self.account_group.pk,
            "has_feed": False,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        detail_url = reverse("accounts:account_detail", kwargs={"team_slug": self.team.slug, "pk": self.account.pk})
        self.assertRedirects(response, detail_url, fetch_redirect_response=False)

    def test_delete_view_success_url_with_return_type_redirects_to_filtered_list(self):
        """Test that deleting an account with return_type redirects to filtered account list."""
        account_to_delete = Account.objects.create(team=self.team, name="To Delete", account_group=self.account_group)
        url = reverse("accounts:account_delete", kwargs={"team_slug": self.team.slug, "pk": account_to_delete.pk})
        response = self.client.post(url, {}, QUERY_STRING="return_type=asset")
        self.assertEqual(response.status_code, 302)
        list_url = reverse("accounts:account_list", kwargs={"team_slug": self.team.slug})
        self.assertRedirects(response, f"{list_url}?type=asset", fetch_redirect_response=False)

    def test_delete_view_success_url_without_return_type_redirects_to_list(self):
        """Test that deleting without return_type redirects to plain account list."""
        account_to_delete = Account.objects.create(team=self.team, name="To Delete 2", account_group=self.account_group)
        url = reverse("accounts:account_delete", kwargs={"team_slug": self.team.slug, "pk": account_to_delete.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        list_url = reverse("accounts:account_list", kwargs={"team_slug": self.team.slug})
        self.assertRedirects(response, list_url, fetch_redirect_response=False)

    def test_delete_view_passes_return_type_to_context(self):
        """Test that delete confirm view passes return_type to template context."""
        url = reverse("accounts:account_delete", kwargs={"team_slug": self.team.slug, "pk": self.account.pk})
        response = self.client.get(url, {"return_type": "asset"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["return_type"], "asset")
