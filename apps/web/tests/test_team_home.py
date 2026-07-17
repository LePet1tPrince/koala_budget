from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_MEMBER
from apps.users.models import CustomUser


class TeamHomeDashboardTest(TestCase):
    """Tests for the team home dashboard view."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_MEMBER})
        cls.other_user = CustomUser.objects.create_user(username="outsider@example.com", password="testpass123")
        cls.url = reverse("web_team:home", kwargs={"team_slug": cls.team.slug})

    def setUp(self):
        self.client.login(username="testuser@example.com", password="testpass123")

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_non_member_gets_404(self):
        self.client.logout()
        self.client.login(username="outsider@example.com", password="testpass123")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_dashboard_renders_for_member(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web/app_home.html")
        self.assertIn("net_worth_card", response.context)
        self.assertIn("goals", response.context)
        self.assertIn("income_ytd", response.context)
        self.assertIn("amount_to_reach_goals", response.context)
        self.assertIn("greeting", response.context)

    def test_dashboard_shows_goals(self):
        with current_team(self.team):
            goal = Goal.objects.create(team=self.team, name="Vacation", target_amount=Decimal("1000.00"))
            GoalAllocation.objects.create(team=self.team, goal=goal, month=date(2026, 1, 1), amount=Decimal("250.00"))
        response = self.client.get(self.url)
        self.assertContains(response, "Vacation")

    def test_greeting_includes_first_name(self):
        self.user.first_name = "Timmy"
        self.user.save()
        response = self.client.get(self.url)
        self.assertIn("Timmy", response.context["greeting"])

    def test_amount_to_reach_all_goals_sums_remaining(self):
        with current_team(self.team):
            goal1 = Goal.objects.create(team=self.team, name="Vacation", target_amount=Decimal("1000.00"))
            GoalAllocation.objects.create(team=self.team, goal=goal1, month=date(2026, 1, 1), amount=Decimal("250.00"))
            goal2 = Goal.objects.create(team=self.team, name="Emergency Fund", target_amount=Decimal("500.00"))
            GoalAllocation.objects.create(team=self.team, goal=goal2, month=date(2026, 1, 1), amount=Decimal("500.00"))
        response = self.client.get(self.url)
        # goal1 needs 750 more; goal2 is fully funded (0 remaining, clamped at 0)
        self.assertEqual(response.context["amount_to_reach_goals"], Decimal("750.00"))

    def test_onboarding_shown_for_empty_team(self):
        response = self.client.get(self.url)
        self.assertTrue(response.context["show_onboarding"])
        self.assertContains(response, "Get set up")

    def test_inbox_count_in_context(self):
        with current_team(self.team):
            group = AccountGroup.objects.create(team=self.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
            account = Account.objects.create(team=self.team, name="Checking", account_group=group)
            BankTransaction.objects.create(
                team=self.team,
                account=account,
                amount=Decimal("10.00"),
                posted_date="2026-01-15",
                description="Coffee",
            )
        response = self.client.get(self.url)
        self.assertEqual(response.context["inbox_count"], 1)
        self.assertContains(response, "transaction to review")

    def test_onboarding_hidden_once_set_up(self):
        with current_team(self.team):
            group = AccountGroup.objects.create(team=self.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE)
            account = Account.objects.create(team=self.team, name="Groceries", account_group=group)
            asset_group = AccountGroup.objects.create(team=self.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
            bank = Account.objects.create(team=self.team, name="Checking", account_group=asset_group)
            BankTransaction.objects.create(
                team=self.team,
                account=bank,
                amount=Decimal("10.00"),
                posted_date="2026-01-15",
                description="Coffee",
            )
            Budget.objects.create(team=self.team, category=account, month="2026-01-01", budget_amount=Decimal("100.00"))
        response = self.client.get(self.url)
        self.assertFalse(response.context["show_onboarding"])
