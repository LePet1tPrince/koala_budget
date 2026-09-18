from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.journal.models import JournalEntry, JournalLine
from apps.monthly_review.models import MonthlyReviewState
from apps.monthly_review.services.budget import _prev_month
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_MEMBER
from apps.users.models import CustomUser


class MonthlyReviewNudgeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Nudge Team", slug="nudge-team")
        cls.user = CustomUser.objects.create_user(username="nudgeuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_MEMBER})
        cls.url = reverse("web_team:home", kwargs={"team_slug": cls.team.slug})

        onboarding = OnboardingState.objects.create(team=cls.team)
        onboarding.complete()
        onboarding.save()

        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Pay", account_type=ACCOUNT_TYPE_INCOME)
        cls.chequing = Account.objects.create(team=cls.team, name="Chequing", account_group=cls.asset_group)
        cls.salary = Account.objects.create(team=cls.team, name="Salary", account_group=cls.income_group)

    def setUp(self):
        self.client.login(username="nudgeuser@example.com", password="testpass123")

    def _give_last_month_activity(self):
        last_month = _prev_month(date.today().replace(day=1))
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=last_month, description="pay", status=JournalEntry.STATUS_POSTED
        )
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=self.chequing, dr_amount=Decimal("500"))
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=self.salary, cr_amount=Decimal("500"))
        return last_month

    def test_no_nudge_without_activity(self):
        response = self.client.get(self.url)
        self.assertFalse(response.context["show_monthly_review_nudge"])
        self.assertNotContains(response, "monthly-review-nudge")

    def test_nudge_shown_when_unreviewed(self):
        self._give_last_month_activity()
        response = self.client.get(self.url)
        self.assertTrue(response.context["show_monthly_review_nudge"])
        self.assertContains(response, "monthly-review-nudge")

    def test_nudge_hidden_once_completed(self):
        last_month = self._give_last_month_activity()
        state = MonthlyReviewState.objects.create(team=self.team, month=last_month)
        state.complete()
        state.save()
        response = self.client.get(self.url)
        self.assertFalse(response.context["show_monthly_review_nudge"])

    def test_nudge_hidden_once_dismissed(self):
        last_month = self._give_last_month_activity()
        state = MonthlyReviewState.objects.create(team=self.team, month=last_month)
        state.dismiss()
        state.save()
        response = self.client.get(self.url)
        self.assertFalse(response.context["show_monthly_review_nudge"])
