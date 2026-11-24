"""The range a report opens on: the dates in its address, else the report's own default."""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class ReportDefaultsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Timeframes", slug="timeframes")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="tf", email="tf@example.com", password="pw123456!")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)

    def setUp(self):
        self.client.login(username="tf", password="pw123456!")

    def range_of(self, name, **params):
        response = self.client.get(reverse(name, args=self.book.url_args), params)
        self.assertEqual(response.status_code, 200)
        return response.context["start_date"], response.context["end_date"]

    def test_each_report_opens_on_its_own_default(self):
        today = date.today()
        self.assertEqual(self.range_of("reports:spending"), (date(today.year, 1, 1), today))
        self.assertEqual(self.range_of("reports:net_worth"), (date(today.year - 1, today.month, 1), today))

    def test_the_address_wins(self):
        self.assertEqual(
            self.range_of("reports:spending", start_date="2026-02-01", end_date="2026-02-10"),
            (date(2026, 2, 1), date(2026, 2, 10)),
        )
        self.assertEqual(
            self.range_of("reports:net_worth", start_month="2026-02", end_month="2026-03"),
            (date(2026, 2, 1), date(2026, 3, 31)),
        )
