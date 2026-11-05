"""
Recurring manual transactions: the schedule arithmetic, creating one from the
feed API, writing what is due, and the management page.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.bank_feed.models import BankTransaction, RecurringTransaction
from apps.bank_feed.services import recurring
from apps.bank_feed.tasks import generate_recurring_transactions
from apps.books.context import current_book
from apps.journal.models import JournalEntry
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

TODAY = date(2026, 11, 5)  # a Thursday


def rule(frequency, start, **fields):
    """An unsaved schedule, for the date arithmetic alone."""
    return RecurringTransaction(frequency=frequency, start_date=start, interval=fields.pop("interval", 1), **fields)


def dates(r, count):
    out, current = [], r.start_date
    for _ in range(count):
        current = recurring.following(r, current)
        if current is None:
            break
        out.append(current)
    return out


class ScheduleTest(SimpleTestCase):
    def test_every_two_weeks_on_wednesday_from_a_wednesday(self):
        r = rule("weekly", date(2026, 11, 4), interval=2, weekday=2)
        self.assertEqual(dates(r, 3), [date(2026, 11, 18), date(2026, 12, 2), date(2026, 12, 16)])

    def test_weekly_starting_before_the_weekday_lands_in_the_same_week(self):
        # Monday start, Wednesday schedule: the first is two days later.
        r = rule("weekly", date(2026, 11, 2), interval=2, weekday=2)
        self.assertEqual(dates(r, 2), [date(2026, 11, 4), date(2026, 11, 18)])

    def test_weekly_starting_after_the_weekday_skips_to_the_next_period(self):
        # Thursday start: that week's Wednesday has passed, so two weeks on.
        r = rule("weekly", date(2026, 11, 5), interval=2, weekday=2)
        self.assertEqual(dates(r, 2), [date(2026, 11, 18), date(2026, 12, 2)])

    def test_the_17th_of_every_month(self):
        r = rule("monthly", date(2026, 11, 5), day_of_month=17)
        self.assertEqual(dates(r, 3), [date(2026, 11, 17), date(2026, 12, 17), date(2027, 1, 17)])

    def test_monthly_day_the_month_lacks_falls_on_its_last_day(self):
        r = rule("monthly", date(2027, 1, 31), day_of_month=31)
        self.assertEqual(dates(r, 3), [date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)])

    def test_last_day_of_the_month(self):
        r = rule("monthly", date(2028, 1, 31), day_of_month=-1)
        self.assertEqual(dates(r, 2), [date(2028, 2, 29), date(2028, 3, 31)])

    def test_every_three_months(self):
        r = rule("monthly", date(2026, 1, 15), interval=3, day_of_month=15)
        self.assertEqual(dates(r, 2), [date(2026, 4, 15), date(2026, 7, 15)])

    def test_daily_and_yearly(self):
        self.assertEqual(dates(rule("daily", date(2026, 12, 30), interval=2), 2), [date(2027, 1, 1), date(2027, 1, 3)])
        self.assertEqual(dates(rule("yearly", date(2028, 2, 29)), 2), [date(2029, 2, 28), date(2030, 2, 28)])

    def test_end_date_finishes_the_schedule(self):
        r = rule("monthly", date(2026, 11, 17), day_of_month=17, end_date=date(2027, 1, 17))
        self.assertEqual(dates(r, 5), [date(2026, 12, 17), date(2027, 1, 17)])

    def test_following_from_far_ahead_jumps_straight_there(self):
        r = rule("weekly", date(2026, 1, 7), weekday=2)
        self.assertEqual(recurring.following(r, date(2030, 6, 1)), date(2030, 6, 5))

    def test_describe(self):
        self.assertEqual(recurring.describe(rule("weekly", TODAY, interval=2, weekday=2)), "Every 2 weeks on Wednesday")
        self.assertEqual(recurring.describe(rule("monthly", TODAY, day_of_month=17)), "Every month on day 17")
        self.assertEqual(recurring.describe(rule("monthly", TODAY, day_of_month=-1)), "Every month on the last day")
        self.assertEqual(recurring.describe(rule("daily", TODAY)), "Every day")
        self.assertEqual(recurring.describe(rule("yearly", TODAY)), "Every year on November 5")


class RecurringFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="admin", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.member = CustomUser.objects.create_user(username="member", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

        asset_group = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        expense_group = AccountGroup.objects.create(book=cls.book, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.bank = Account.objects.create(book=cls.book, name="Checking", account_group=asset_group, has_feed=True)
        cls.rent = Account.objects.create(book=cls.book, name="Rent", account_group=expense_group)
        cls.fun = Account.objects.create(book=cls.book, name="Fun", account_group=expense_group)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)
        patcher = mock.patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def create(self, **body):
        payload = {"account": self.bank.id, "outflow": "1200.00", "payee": "Landlord", **body}
        with current_book(self.book):
            return self.api.post(f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/", payload, format="json")

    def make_rule(self, **fields):
        with current_book(self.book):
            return recurring.create_rule(
                book=self.book,
                account=self.bank,
                amount=Decimal("9.99"),
                payee_name="Streaming",
                description="",
                category=self.fun,
                legs=None,
                **{"frequency": "monthly", "start_date": date(2026, 9, 5), **fields},
            )


class CreateRecurringTest(RecurringFixture):
    def test_create_saves_the_schedule_and_links_the_first_transaction(self):
        response = self.create(
            date="2026-11-05", category=self.rent.id, recurrence={"frequency": "monthly", "day_of_month": 17}
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        r = RecurringTransaction.objects.get()
        self.assertEqual((r.book, r.account, r.category), (self.book, self.bank, self.rent))
        self.assertEqual(r.amount, Decimal("1200.00"))
        self.assertEqual(r.payee_name, "Landlord")
        self.assertEqual((r.frequency, r.interval, r.day_of_month, r.weekday), ("monthly", 1, 17, None))
        self.assertEqual(r.next_date, date(2026, 11, 17))
        # Only the one the user entered: the 17th has not come yet.
        tx = BankTransaction.objects.get()
        self.assertEqual(tx.recurring, r)
        self.assertEqual(response.data["recurring_id"], r.id)

    def test_weekly_defaults_to_the_dates_weekday(self):
        self.create(date="2026-11-04", recurrence={"frequency": "weekly", "interval": 2})
        r = RecurringTransaction.objects.get()
        self.assertEqual((r.weekday, r.next_date), (2, date(2026, 11, 18)))

    def test_a_schedule_started_in_the_past_catches_up_at_once(self):
        response = self.create(
            date="2026-08-17", category=self.rent.id, recurrence={"frequency": "monthly", "day_of_month": 17}
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rows = BankTransaction.objects.order_by("posted_date")
        self.assertEqual(
            [tx.posted_date for tx in rows],
            [date(2026, 8, 17), date(2026, 9, 17), date(2026, 10, 17)],
        )
        for tx in rows:
            self.assertEqual(tx.source, BankTransaction.SOURCE_MANUAL)
            self.assertEqual(tx.amount, Decimal("1200.00"))
            self.assertTrue(tx.journal_entry.is_balanced)
            self.assertEqual({line.account for line in tx.journal_entry.lines.all()}, {self.bank, self.rent})
        self.assertEqual(RecurringTransaction.objects.get().next_date, date(2026, 11, 17))

    def test_a_split_repeats_as_a_split(self):
        self.create(
            date="2026-10-01",
            splits=[{"category": self.rent.id, "amount": "1000.00"}, {"category": self.fun.id, "amount": "200.00"}],
            recurrence={"frequency": "monthly"},
        )

        generated = BankTransaction.objects.get(posted_date=date(2026, 11, 1))
        legs = {line.account_id: line.dr_amount for line in generated.journal_entry.lines.exclude(account=self.bank)}
        self.assertEqual(legs, {self.rent.id: Decimal("1000.00"), self.fun.id: Decimal("200.00")})

    def test_uncategorized_repeats_uncategorized(self):
        self.create(date="2026-10-29", recurrence={"frequency": "weekly"})
        generated = BankTransaction.objects.get(posted_date=date(2026, 11, 5))
        self.assertIsNone(generated.journal_entry)

    def test_invalid_schedules_are_refused_and_write_nothing(self):
        for recurrence in (
            {"frequency": "hourly"},
            {"frequency": "monthly", "day_of_month": 0},
            {"frequency": "monthly", "day_of_month": 32},
            {"frequency": "weekly", "weekday": 7},
            {"frequency": "daily", "interval": 0},
            {"frequency": "daily", "end_date": "2026-11-01"},
        ):
            with self.subTest(recurrence=recurrence):
                response = self.create(date="2026-11-05", recurrence=recurrence)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(RecurringTransaction.objects.exists())
        self.assertFalse(BankTransaction.objects.exists())

    def test_a_start_more_than_a_year_back_is_refused(self):
        response = self.create(date="2025-11-01", recurrence={"frequency": "daily"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(BankTransaction.objects.exists())

    def test_without_recurrence_nothing_repeats(self):
        response = self.create(date="2026-11-05", category=self.rent.id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(RecurringTransaction.objects.exists())
        self.assertIsNone(response.data["recurring_id"])


class MaterializeTest(RecurringFixture):
    def test_running_twice_writes_each_occurrence_once(self):
        r = self.make_rule()
        self.assertEqual(recurring.materialize(r), 2)  # Oct 5, Nov 5
        self.assertEqual(recurring.materialize(r), 0)
        self.assertEqual(BankTransaction.objects.filter(recurring=r).count(), 2)
        self.assertEqual(r.next_date, date(2026, 12, 5))

    def test_the_nightly_task_covers_every_book(self):
        other_team = Team.objects.create(name="Other", slug="other")
        other_book = other_team.default_book
        group = AccountGroup.objects.create(book=other_book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        other_bank = Account.objects.create(book=other_book, name="Checking", account_group=group, has_feed=True)
        self.make_rule()
        recurring.create_rule(
            book=other_book,
            account=other_bank,
            amount=Decimal("5"),
            payee_name="",
            description="",
            category=None,
            legs=None,
            frequency="daily",
            start_date=date(2026, 11, 3),
        )

        self.assertEqual(generate_recurring_transactions(), 4)  # Oct 5, Nov 5; Nov 4, Nov 5
        self.assertEqual(BankTransaction.objects.filter(book=other_book).count(), 2)

    def test_a_category_no_longer_allowed_writes_the_occurrence_uncategorized(self):
        r = self.make_rule()
        self.fun.delete()
        r.refresh_from_db()
        recurring.materialize(r)
        self.assertEqual(BankTransaction.objects.filter(recurring=r, journal_entry__isnull=True).count(), 2)

    def test_end_date_stops_it(self):
        r = self.make_rule(end_date=date(2026, 10, 31))
        recurring.materialize(r)
        self.assertEqual(BankTransaction.objects.filter(recurring=r).count(), 1)
        self.assertIsNone(r.next_date)

    def test_opening_the_bank_feed_writes_what_is_due(self):
        r = self.make_rule()
        self.client.force_login(self.user)
        response = self.client.get(reverse("bank_feed:bank_feed_home", args=self.book.url_args))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(BankTransaction.objects.filter(recurring=r).count(), 2)
        self.assertEqual(JournalEntry.objects.count(), 2)


class RecurringPageTest(RecurringFixture):
    def setUp(self):
        super().setUp()
        self.r = self.make_rule()
        recurring.materialize(self.r)

    def test_list_shows_the_schedule(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("bank_feed:recurring_list", args=self.book.url_args))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Streaming")
        self.assertContains(response, "Every month on day 5")
        self.assertContains(response, 'data-testid="recurring-stop"')

    def test_a_member_stops_a_schedule_and_keeps_its_transactions(self):
        self.client.force_login(self.member)
        url = reverse("bank_feed:recurring_delete", args=[*self.book.url_args, self.r.pk])
        response = self.client.post(url)
        self.assertRedirects(response, reverse("bank_feed:recurring_list", args=self.book.url_args))
        self.assertFalse(RecurringTransaction.objects.exists())
        self.assertEqual(BankTransaction.objects.filter(recurring__isnull=True).count(), 2)

    def test_someone_outside_the_team_cannot_see_or_stop_a_schedule(self):
        outsider = CustomUser.objects.create_user(username="outsider", password="pass")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse("bank_feed:recurring_list", args=self.book.url_args)).status_code, 404)
        url = reverse("bank_feed:recurring_delete", args=[*self.book.url_args, self.r.pk])
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(RecurringTransaction.objects.exists())

    def test_stop_is_post_only(self):
        self.client.force_login(self.user)
        url = reverse("bank_feed:recurring_delete", args=[*self.book.url_args, self.r.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(RecurringTransaction.objects.exists())
