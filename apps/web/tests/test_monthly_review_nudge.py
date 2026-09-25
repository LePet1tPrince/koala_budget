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
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="nudgeuser@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_MEMBER})
        cls.url = reverse("web_book:home", args=cls.book.url_args)

        onboarding = OnboardingState.objects.create(book=cls.book)
        onboarding.complete()
        onboarding.save()

        cls.asset_group = AccountGroup.objects.create(book=cls.book, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.income_group = AccountGroup.objects.create(book=cls.book, name="Pay", account_type=ACCOUNT_TYPE_INCOME)
        cls.chequing = Account.objects.create(book=cls.book, name="Chequing", account_group=cls.asset_group)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=cls.income_group)

    def setUp(self):
        self.client.login(username="nudgeuser@example.com", password="testpass123")

    def _give_last_month_activity(self):
        last_month = _prev_month(date.today().replace(day=1))
        entry = JournalEntry.objects.create(
            book=self.book, entry_date=last_month, description="pay", status=JournalEntry.STATUS_POSTED
        )
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=self.chequing, dr_amount=Decimal("500"))
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=self.salary, cr_amount=Decimal("500"))
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
        state = MonthlyReviewState.objects.create(book=self.book, month=last_month)
        state.complete()
        state.save()
        response = self.client.get(self.url)
        self.assertFalse(response.context["show_monthly_review_nudge"])

    def test_nudge_hidden_once_dismissed(self):
        last_month = self._give_last_month_activity()
        state = MonthlyReviewState.objects.create(book=self.book, month=last_month)
        state.dismiss()
        state.save()
        response = self.client.get(self.url)
        self.assertFalse(response.context["show_monthly_review_nudge"])
