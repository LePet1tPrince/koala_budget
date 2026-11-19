"""`GET /a/{team}/{book}/api/home/`: the dashboard's figures, from the same builder as the page."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.books.context import current_book
from apps.books.tests.factories import build_book_data, second_book
from apps.budget.ledger import set_goal_allocation
from apps.budget.models import Goal
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_MEMBER
from apps.users.models import CustomUser
from apps.utils.months import format_month


class BookHomeApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Home API", slug="home-api")
        cls.user = CustomUser.objects.create_user(username="home-api@example.com", password="pass", first_name="Ada")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_MEMBER})
        cls.a = build_book_data(cls.team.default_book, "QQHOMEAQQ", cls.user)
        cls.b = build_book_data(second_book(cls.team), "QQHOMEBQQ", cls.user)
        for book in (cls.a.book, cls.b.book):
            onboarding, _created = OnboardingState.objects.get_or_create(book=book)
            onboarding.complete()
            onboarding.save()
        cls.url = reverse("book_api:home", args=cls.a.book.url_args)

    def setUp(self):
        self.client.force_login(self.user)

    def test_dashboard_figures(self):
        with current_book(self.a.book):
            goal = Goal.objects.create(book=self.a.book, name="Roof", target_amount=Decimal("500.00"))
            set_goal_allocation(self.a.book, goal, date(2026, 1, 1), Decimal("200.00"))

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["month"], format_month(date.today()))
        self.assertIn("Ada", data["greeting"])
        self.assertEqual(data["book_label"], self.a.book.name)  # the team has two books
        self.assertTrue(data["onboarding_finished"])
        self.assertEqual(data["net_worth"], "-42.00")
        self.assertEqual(data["income_ytd"]["start_date"], date(date.today().year, 1, 1).isoformat())
        roof = next(g for g in data["goals"] if g["name"] == "Roof")
        self.assertEqual((roof["id"], roof["allocated"], roof["target_amount"]), (goal.id, "200.00", "500.00"))
        # The trend runs from the book's first activity (March 2026) to today.
        self.assertEqual(data["net_worth_trend"][0]["date"], "2026-03-31")
        self.assertEqual(data["net_worth_trend"][-1]["date"], date.today().isoformat())
        self.assertEqual(data["ynab_import"], {"offered": False, "state": ""})
        self.assertNotIn("QQHOMEBQQ", response.content.decode())

    def test_unfinished_walkthrough_still_answers(self):
        OnboardingState.objects.filter(book=self.a.book).update(completed_at=None, skipped_at=None, phase="welcome")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["onboarding_finished"])

    def test_the_page_draws_its_chart_from_the_api(self):
        response = self.client.get(reverse("web_book:home", args=self.a.book.url_args))
        self.assertContains(response, 'id="home-net-worth-chart"')
        self.assertContains(response, 'id="book-base"')
        self.assertNotContains(response, "home-net-worth-data")

    def test_non_member_is_refused(self):
        self.client.force_login(CustomUser.objects.create_user(username="outsider-home@example.com", password="p"))
        self.assertIn(self.client.get(self.url).status_code, (403, 404))

    def test_anonymous_is_refused(self):
        self.client.logout()
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_unknown_book_is_a_404(self):
        response = self.client.get(reverse("book_api:home", args=[self.team.slug, "no-such-book"]))
        self.assertEqual(response.status_code, 404)
