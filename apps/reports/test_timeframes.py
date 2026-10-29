"""A book's default report timeframe (`Book.report_timeframe`) and the reports that open on it."""

from datetime import date
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import ACCOUNT_TYPE_ASSET, Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.books.models import ReportTimeframe
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .timeframes import timeframe_range

TODAY = date(2026, 10, 16)


class TimeframeRangeTest(TestCase):
    def test_every_choice(self):
        expected = {
            ReportTimeframe.THIS_MONTH: (date(2026, 10, 1), TODAY),
            ReportTimeframe.LAST_MONTH: (date(2026, 9, 1), date(2026, 9, 30)),
            ReportTimeframe.LAST_3_MONTHS: (date(2026, 7, 1), date(2026, 9, 30)),
            ReportTimeframe.LAST_6_MONTHS: (date(2026, 4, 1), date(2026, 9, 30)),
            ReportTimeframe.LAST_12_MONTHS: (date(2025, 10, 1), date(2026, 9, 30)),
            ReportTimeframe.THIS_YEAR: (date(2026, 1, 1), TODAY),
            ReportTimeframe.LAST_YEAR: (date(2025, 1, 1), date(2025, 12, 31)),
        }
        for timeframe, rng in expected.items():
            with self.subTest(timeframe):
                self.assertEqual(timeframe_range(timeframe, TODAY), rng)

    def test_report_default_defers_to_the_report(self):
        self.assertIsNone(timeframe_range(ReportTimeframe.REPORT, TODAY))
        self.assertIsNone(timeframe_range("not-a-timeframe", TODAY))

    def test_full_months_cross_the_year(self):
        self.assertEqual(
            timeframe_range(ReportTimeframe.LAST_3_MONTHS, date(2026, 1, 31)),
            (date(2025, 10, 1), date(2025, 12, 31)),
        )
        self.assertEqual(
            timeframe_range(ReportTimeframe.LAST_MONTH, date(2026, 3, 1)),
            (date(2026, 2, 1), date(2026, 2, 28)),
        )


@mock.patch("apps.reports.timeframes.date", wraps=date)
class ReportDefaultsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Timeframes", slug="timeframes")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="tf", email="tf@example.com", password="pw123456!")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)
        group = AccountGroup.objects.create(book=cls.book, name="Tf Bank", account_type=ACCOUNT_TYPE_ASSET)
        cls.bank = Account.objects.create(book=cls.book, name="Tf Checking", account_group=group)

    def setUp(self):
        self.client.login(username="tf", password="pw123456!")

    def set_timeframe(self, timeframe):
        self.book.report_timeframe = timeframe
        self.book.save()

    def range_of(self, name, *args, **params):
        response = self.client.get(reverse(name, args=[*self.book.url_args, *args]), params)
        self.assertEqual(response.status_code, 200)
        return response.context["start_date"], response.context["end_date"]

    def test_date_range_reports_open_on_the_books_timeframe(self, mock_date):
        mock_date.today.return_value = TODAY
        self.set_timeframe(ReportTimeframe.LAST_3_MONTHS)
        expected = (date(2026, 7, 1), date(2026, 9, 30))
        self.assertEqual(self.range_of("reports:income_statement"), expected)
        self.assertEqual(self.range_of("reports:spending"), expected)
        self.assertEqual(self.range_of("reports:account_activity", self.bank.pk), expected)
        self.assertEqual(self.range_of("accounts:account_detail", self.bank.pk), expected)

    def test_month_range_reports_open_on_the_books_timeframe(self, mock_date):
        mock_date.today.return_value = TODAY
        self.set_timeframe(ReportTimeframe.LAST_YEAR)
        expected = (date(2025, 1, 1), date(2025, 12, 31))
        self.assertEqual(self.range_of("reports:net_worth_trend"), expected)
        self.assertEqual(self.range_of("reports:cash_flow"), expected)
        self.assertEqual(self.range_of("reports:net_worth"), expected)

    def test_the_address_wins_over_the_setting(self, mock_date):
        mock_date.today.return_value = TODAY
        self.set_timeframe(ReportTimeframe.LAST_YEAR)
        self.assertEqual(
            self.range_of("reports:income_statement", start_date="2026-02-01", end_date="2026-02-10"),
            (date(2026, 2, 1), date(2026, 2, 10)),
        )
        self.assertEqual(
            self.range_of("reports:cash_flow", start_month="2026-02", end_month="2026-03"),
            (date(2026, 2, 1), date(2026, 3, 31)),
        )

    def test_report_default_keeps_each_reports_own(self, mock_date):
        today = date.today()
        self.assertEqual(self.book.report_timeframe, ReportTimeframe.REPORT)
        self.assertEqual(self.range_of("reports:income_statement"), (today.replace(day=1), today))
        self.assertEqual(self.range_of("reports:spending"), (date(today.year, 1, 1), today))
        self.assertEqual(self.range_of("reports:cash_flow"), (date(today.year - 1, today.month, 1), today))

    def test_the_picker_is_given_the_range_the_report_shows(self, mock_date):
        mock_date.today.return_value = TODAY
        self.set_timeframe(ReportTimeframe.LAST_MONTH)
        income = self.client.get(reverse("reports:income_statement", args=self.book.url_args))
        self.assertContains(income, 'data-start-date="2026-09-01" data-end-date="2026-09-30"')
        trend = self.client.get(reverse("reports:net_worth_trend", args=self.book.url_args))
        self.assertContains(trend, 'data-start-month="2026-09" data-end-month="2026-09"')


class BookTimeframeSettingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Tf Settings", slug="tf-settings")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="tfs", email="tfs@example.com", password="pw123456!")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)

    def setUp(self):
        self.client.login(username="tfs", password="pw123456!")

    def post(self, **extra):
        data = {"name": self.book.name, "slug": self.book.slug, **extra}
        return self.client.post(reverse("books:settings", args=self.book.url_args), data)

    def test_saves_and_records_the_change(self):
        self.post(report_timeframe=ReportTimeframe.THIS_YEAR)
        self.book.refresh_from_db()
        self.assertEqual(self.book.report_timeframe, ReportTimeframe.THIS_YEAR)
        event = AuditEvent.objects.get(event_type=AuditEvent.BOOK_SETTINGS_CHANGED, book=self.book)
        self.assertEqual(event.metadata, {"report_timeframe": "this_year"})

    def test_a_post_without_it_keeps_it(self):
        self.book.report_timeframe = ReportTimeframe.LAST_MONTH
        self.book.save()
        self.post()
        self.book.refresh_from_db()
        self.assertEqual(self.book.report_timeframe, ReportTimeframe.LAST_MONTH)

    def test_an_unknown_choice_is_refused(self):
        response = self.post(report_timeframe="fortnight")
        self.assertEqual(response.status_code, 200)
        self.book.refresh_from_db()
        self.assertEqual(self.book.report_timeframe, ReportTimeframe.REPORT)
