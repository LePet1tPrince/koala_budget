"""
The sidebar's sub-items: which one is shaded, and the Inbox accounts' balances.

A sub-item page shades its sub-item and not the parent, so the tests read the
rendered page's nav markup for both.
"""

import re
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.books.context import current_book
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


def _active_testids(nav):
    """data-testids of the nav links rendered with side-link-active."""
    return set(re.findall(r'class="side-link[^"]*side-link-active[^"]*"[^>]*data-testid="([^"]+)"', nav))


class NavTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="admin@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        onboarding = OnboardingState.objects.create(book=cls.book)
        onboarding.complete()
        onboarding.save()

    def setUp(self):
        self.client.force_login(self.user)

    def _nav(self, url):
        """The whole page: the nav needs the view's own `active_tab`."""
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


class NavSubItemActiveTest(NavTestBase):
    def test_monthly_review_shades_its_sub_item_not_reports(self):
        response = self.client.get(reverse("monthly_review:home", args=self.book.url_args))
        self.assertEqual(response.context["nav_item"], "monthly-review")
        nav = self._nav(reverse("monthly_review:home", args=self.book.url_args))
        self.assertIn("nav-monthly-review", _active_testids(nav))
        reports_url = reverse("reports:reports_home", args=self.book.url_args)
        reports_link = re.search(rf'<a href="{reports_url}"\s+class="([^"]*)"', nav)
        self.assertNotIn("side-link-active", reports_link.group(1))

    def test_each_report_shades_only_its_own_sub_item(self):
        cases = {
            "reports:dollar_map": "nav-report-dollar-map",
            "reports:income_statement": "nav-report-income-statement",
            "reports:balance_sheet": "nav-report-balance-sheet",
            "reports:net_worth_trend": "nav-report-net-worth-trend",
            "reports:cash_flow": "nav-report-cash-flow",
            "reports:budget_vs_actual": "nav-report-budget-vs-actual",
            "reports:goal_progress": "nav-report-goal-progress",
            "reconciliation:hub": "nav-report-reconciliation",
        }
        for url_name, testid in cases.items():
            with self.subTest(url_name=url_name):
                self.assertEqual(_active_testids(self._nav(reverse(url_name, args=self.book.url_args))), {testid})

    def test_reports_home_shades_the_parent(self):
        url = reverse("reports:reports_home", args=self.book.url_args)
        nav = self._nav(url)
        self.assertEqual(_active_testids(nav), set())
        self.assertRegex(nav, rf'<a href="{url}"\s+class="side-link flex-1 side-link-active"')

    def test_nav_lists_every_report_on_the_reports_page(self):
        nav = self._nav(reverse("reports:reports_home", args=self.book.url_args))
        for url_name in ("reports:dollar_map", "reconciliation:hub"):
            with self.subTest(url_name=url_name):
                self.assertIn(reverse(url_name, args=self.book.url_args), nav)

    def test_accounts_sub_pages_shade_their_sub_item(self):
        cases = {
            "accounts:accounts_home": "nav-accounts-list",
            "accounts:accountgroup_list": "nav-accounts-groups",
            "accounts:payee_list": "nav-accounts-payees",
            "accounts:institution_list": "nav-accounts-institutions",
        }
        for url_name, testid in cases.items():
            with self.subTest(url_name=url_name):
                self.assertEqual(_active_testids(self._nav(reverse(url_name, args=self.book.url_args))), {testid})

    def test_balance_sheet_drill_down_shades_balance_sheet(self):
        with current_book(self.book):
            group = AccountGroup.objects.create(book=self.book, name="Cash", account_type=ACCOUNT_TYPE_ASSET)
            account = Account.objects.create(book=self.book, name="Checking", account_group=group)
        url = reverse("reports:account_activity", args=[*self.book.url_args, account.id]) + "?source=balance_sheet"
        self.assertEqual(_active_testids(self._nav(url)), {"nav-report-balance-sheet"})


class NavInboxBalanceTest(NavTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with current_book(cls.book):
            cls._seed()

    @classmethod
    def _seed(cls):
        assets = AccountGroup.objects.create(book=cls.book, name="Cash", account_type=ACCOUNT_TYPE_ASSET)
        expenses = AccountGroup.objects.create(book=cls.book, name="Food", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=assets, has_feed=True)
        groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=expenses)
        entry = JournalEntry.objects.create(book=cls.book, entry_date=date(2026, 9, 1), description="Deposit")
        amount = Decimal("1234.50")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=cls.checking, dr_amount=amount)
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=groceries, cr_amount=amount)

    def test_inbox_account_shows_its_balance(self):
        nav = self._nav(reverse("web_book:home", args=self.book.url_args))
        self.assertRegex(nav, rf'data-testid="nav-inbox-account-balance-{self.checking.id}">\$1,234\.50<')

    def test_feed_page_shades_the_selected_account(self):
        url = reverse("bank_feed:bank_feed_home", args=self.book.url_args) + f"?account={self.checking.id}"
        self.assertEqual(_active_testids(self._nav(url)), {f"nav-inbox-account-{self.checking.id}"})


class SidebarShellTest(NavTestBase):
    """
    The resize handle and collapse toggle are driven by common/sidebar.js; what
    the server owes it is the hooks, and a `.side-label` on every top-level item
    so collapsing can hide the words while keeping each link's accessible name.
    """

    def test_sidebar_carries_resize_and_collapse_hooks(self):
        page = self._nav(reverse("web_book:home", args=self.book.url_args))
        self.assertIn("data-sidebar-root", page)
        self.assertIn('data-testid="sidebar-resizer"', page)
        self.assertIn('data-testid="sidebar-toggle"', page)
        # Applied before first paint, so a reload never flashes the default width.
        self.assertIn("koala.sidebar.collapsed", page)

    def test_top_level_items_have_labels_and_submenus_are_marked(self):
        page = self._nav(reverse("web_book:home", args=self.book.url_args))
        for label in ("Home", "Inbox", "Transactions", "Budget", "Reports", "Accounts", "Ask Koala"):
            with self.subTest(label=label):
                self.assertIn(f'<span class="side-label">{label}</span>', page)
        self.assertIn('class="side-sub ', page)
