"""
Spotting recurring transactions (`services/recurring_detection.py`) and turning a
suggestion into a schedule (`recurring.create_rule_from_transaction`, the
`recurring` API's `suggestions` / `from_transaction` / `dismiss_suggestion`).
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.bank_feed.models import BankTransaction, RecurringSuggestionDismissal, RecurringTransaction
from apps.bank_feed.services.manual import create_manual_transaction
from apps.bank_feed.services.recurring_detection import find_suggestions, payee_key
from apps.books.context import current_book
from apps.plaid.models import PlaidAccount, PlaidItem
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

TODAY = date(2026, 11, 5)


class DetectionFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Detect", slug="detect")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="admin", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.member = CustomUser.objects.create_user(username="member", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        spend = AccountGroup.objects.create(book=cls.book, name="Spend", account_type=ACCOUNT_TYPE_EXPENSE)
        income = AccountGroup.objects.create(book=cls.book, name="Income", account_type=ACCOUNT_TYPE_INCOME)
        cls.bank = Account.objects.create(book=cls.book, name="Checking", account_group=banks, has_feed=True)
        cls.card = Account.objects.create(book=cls.book, name="Card", account_group=banks, has_feed=True)
        cls.streaming = Account.objects.create(book=cls.book, name="Streaming", account_group=spend)
        cls.food = Account.objects.create(book=cls.book, name="Food", account_group=spend)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=income)

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = APIClient()
        self.api.force_authenticate(user=self.member)

    def add(self, when, amount, name, account=None, category=None, legs=None):
        account = account or self.bank
        if category is not None:
            legs = [(category, Decimal(amount))]
        with current_book(self.book):
            return create_manual_transaction(
                book=self.book, account=account, date=when, amount=Decimal(amount), payee_name=name, legs=legs
            )

    def netflix(self, account=None):
        for i, when in enumerate([date(2026, 8, 3), date(2026, 9, 3), date(2026, 10, 2), date(2026, 11, 3)]):
            last = self.add(when, "15.99", f"NETFLIX.COM {8800 + i}", account=account, category=self.streaming)
        return last

    def suggestions(self, **kwargs):
        return find_suggestions(self.book, today=TODAY, **kwargs)

    def url(self, action=""):
        return f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/recurring/{action}"


class DetectionTest(DetectionFixture):
    def test_payee_key_ignores_case_digits_and_punctuation(self):
        self.assertEqual(payee_key("NETFLIX.COM 8812"), "netflix com")
        self.assertEqual(payee_key("Netflix.com #9921"), "netflix com")
        self.assertEqual(payee_key("1234"), "")
        self.assertEqual(payee_key("AMAZON PRIME*AB12CD"), payee_key("Amazon Prime*XY34ZZ"))
        self.assertEqual(payee_key("AMAZON PRIME*AB12CD"), "amazon prime")
        self.assertEqual(payee_key("POS PURCHASE NETFLIX 11/03 LOS GATOS CA"), "pos purchase netflix los")

    def test_older_irregular_history_does_not_hide_the_current_run(self):
        # A skipped month in the spring, a price change and a one-off purchase from
        # the same payee: the latest three months still read as monthly.
        for when, amount in [
            (date(2026, 3, 3), "11.99"),
            (date(2026, 5, 3), "11.99"),  # April skipped
            (date(2026, 8, 3), "15.99"),
            (date(2026, 9, 3), "15.99"),
            (date(2026, 9, 18), "64.00"),  # a one-off
            (date(2026, 10, 3), "15.99"),
        ]:
            self.add(when, amount, "NETFLIX.COM")
        [s] = self.suggestions()
        self.assertEqual((s["frequency"], s["day_of_month"], s["occurrences"]), ("monthly", 3, 3))
        self.assertEqual(s["outflow"], Decimal("15.99"))

    def test_freshness_is_measured_against_the_accounts_latest_transaction(self):
        # This account's import stops in August; its pattern is still current there.
        for when in (date(2026, 5, 10), date(2026, 6, 10), date(2026, 7, 10)):
            self.add(when, "50", "Gym", account=self.card)
        self.add(date(2026, 8, 1), "5", "Coffee", account=self.card)
        [s] = self.suggestions()
        self.assertEqual((s["payee"], s["next_date"]), ("Gym", date(2026, 8, 10)))

    def test_weekly_wins_over_every_two_weeks(self):
        for days in range(0, 35, 7):
            self.add(date(2026, 10, 1) + timedelta(days=days), "20", "Cleaner")
        [s] = self.suggestions()
        self.assertEqual((s["frequency"], s["interval"], s["occurrences"]), ("weekly", 1, 5))

    def test_a_monthly_subscription_is_suggested(self):
        last = self.netflix()
        [s] = self.suggestions()
        self.assertEqual((s["frequency"], s["interval"], s["day_of_month"]), ("monthly", 1, 3))
        self.assertEqual(s["transaction_id"], last.id)
        self.assertEqual(s["payee"], "NETFLIX.COM 8803")
        self.assertEqual(s["category"], self.streaming)
        self.assertEqual(s["outflow"], Decimal("15.99"))
        self.assertEqual((s["occurrences"], s["last_date"], s["next_date"]), (4, date(2026, 11, 3), date(2026, 12, 3)))
        self.assertEqual(s["schedule"], "Every month on day 3")
        self.assertFalse(s["bank_synced"])

    def test_a_biweekly_paycheque_is_suggested_as_an_inflow(self):
        for days in (0, 14, 28, 42):
            self.add(date(2026, 9, 25) + timedelta(days=days), "-2000", "ACME PAYROLL", category=self.salary)
        [s] = self.suggestions()
        self.assertEqual((s["frequency"], s["interval"], s["weekday"]), ("weekly", 2, 4))
        self.assertEqual((s["inflow"], s["outflow"]), (Decimal("2000"), Decimal("0")))
        self.assertEqual(s["schedule"], "Every 2 weeks on Friday")

    def test_month_end_runs_repeat_on_the_last_day(self):
        for when in (date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30), date(2026, 10, 31)):
            self.add(when, "1200", "Landlord")
        [s] = self.suggestions()
        self.assertEqual(s["day_of_month"], -1)
        self.assertEqual(s["next_date"], date(2026, 11, 30))

    def test_what_is_not_recurring(self):
        cases = {
            "two only": [(date(2026, 9, 3), "10"), (date(2026, 10, 3), "10")],
            "irregular": [(date(2026, 8, 3), "10"), (date(2026, 8, 20), "10"), (date(2026, 10, 30), "10")],
            "amount varies": [(date(2026, 8, 3), "10"), (date(2026, 9, 3), "30"), (date(2026, 10, 3), "10")],
            "stopped": [(date(2026, 6, 3), "10"), (date(2026, 7, 3), "10"), (date(2026, 8, 3), "10")],
        }
        for name, rows in cases.items():
            for when, amount in rows:
                self.add(when, amount, f"Shop {name}")
        self.assertEqual(self.suggestions(), [])

    def test_same_payee_other_direction_or_account_is_its_own_run(self):
        self.netflix()
        self.add(date(2026, 10, 3), "-15.99", "NETFLIX.COM")  # a refund
        self.add(date(2026, 10, 3), "15.99", "NETFLIX.COM", account=self.card)
        self.assertEqual(len(self.suggestions()), 1)

    def test_scheduled_and_dismissed_runs_are_not_suggested(self):
        self.netflix()
        RecurringSuggestionDismissal.objects.create(
            book=self.book, account=self.bank, direction="out", payee_key="netflix com"
        )
        self.assertEqual(self.suggestions(), [])

        for when in (date(2026, 8, 10), date(2026, 9, 10), date(2026, 10, 10)):
            self.add(when, "50", "Gym")
        self.assertEqual(len(self.suggestions()), 1)
        RecurringTransaction.objects.create(
            book=self.book,
            account=self.bank,
            amount=Decimal("50"),
            payee_name="GYM",
            frequency="monthly",
            day_of_month=10,
            start_date=date(2026, 10, 10),
            next_date=date(2026, 11, 10),
        )
        self.assertEqual(self.suggestions(), [])

    def test_account_filter_and_bank_synced_flag(self):
        self.netflix(account=self.card)
        item = PlaidItem.objects.create(book=self.book, plaid_item_id="i", access_token="t", institution_name="B")
        PlaidAccount.objects.create(
            book=self.book, plaid_account_id="a", item=item, account=self.card, name="Card", type="credit"
        )
        self.assertEqual(self.suggestions(account_ids=[self.bank.id]), [])
        [s] = self.suggestions(account_ids=[self.card.id])
        self.assertTrue(s["bank_synced"])


class SuggestionApiTest(DetectionFixture):
    def test_list(self):
        self.netflix()
        response = self.api.get(self.url("suggestions/"), {"account": str(self.bank.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        [s] = response.data
        self.assertEqual(s["key"], f"{self.bank.id}:out:netflix com")
        self.assertEqual(s["next_date"], "2026-12-03")
        self.assertEqual(s["category"]["id"], self.streaming.id)

    def test_make_recurring_from_the_latest_occurrence(self):
        last = self.netflix()
        response = self.api.post(
            self.url("from_transaction/"),
            {"transaction": last.id, "frequency": "monthly", "day_of_month": 3},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        rule = RecurringTransaction.objects.get()
        self.assertEqual((rule.account, rule.category, rule.amount), (self.bank, self.streaming, Decimal("15.99")))
        self.assertEqual((rule.start_date, rule.next_date), (date(2026, 11, 3), date(2026, 12, 3)))
        self.assertEqual(rule.payee_name, "NETFLIX.COM 8803")
        last.refresh_from_db()
        self.assertEqual(last.recurring, rule)
        self.assertEqual(response.data["next_date"], "2026-12-03")
        # Nothing was due yet, and the run is no longer suggested.
        self.assertEqual(BankTransaction.objects.count(), 4)
        self.assertEqual(self.api.get(self.url("suggestions/")).data, [])

    def test_an_overdue_occurrence_is_written_at_once(self):
        last = self.add(date(2026, 10, 1), "40", "Phone", category=self.food)
        self.api.post(self.url("from_transaction/"), {"transaction": last.id, "frequency": "monthly"}, format="json")
        rule = RecurringTransaction.objects.get()
        written = BankTransaction.objects.get(posted_date=date(2026, 11, 1))
        self.assertEqual(written.recurring, rule)
        self.assertEqual(written.journal_entry.lines.exclude(account=self.bank).get().account, self.food)
        self.assertEqual(rule.next_date, date(2026, 12, 1))

    def test_a_split_repeats_as_a_split(self):
        last = self.add(
            date(2026, 11, 1), "100", "Costco", legs=[(self.food, Decimal("70")), (self.streaming, Decimal("30"))]
        )
        self.api.post(self.url("from_transaction/"), {"transaction": last.id, "frequency": "weekly"}, format="json")
        rule = RecurringTransaction.objects.get()
        self.assertIsNone(rule.category)
        self.assertEqual(
            rule.splits,
            [{"category": self.food.id, "amount": "70.00"}, {"category": self.streaming.id, "amount": "30.00"}],
        )

    def test_refusals(self):
        last = self.netflix()
        void = self.add(date(2026, 11, 1), "5", "Void")
        BankTransaction.objects.filter(pk=void.pk).update(is_void=True)
        mirror = self.add(date(2026, 11, 1), "5", "Mirror")
        BankTransaction.objects.filter(pk=mirror.pk).update(is_transfer_mirror=True)
        for body in (
            {"transaction": void.id, "frequency": "monthly"},
            {"transaction": mirror.id, "frequency": "monthly"},
            {"transaction": last.id, "frequency": "monthly", "end_date": "2026-10-01"},
            {"transaction": last.id, "frequency": "hourly"},
        ):
            with self.subTest(body=body):
                response = self.api.post(self.url("from_transaction/"), body, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(RecurringTransaction.objects.exists())

        self.api.post(self.url("from_transaction/"), {"transaction": last.id, "frequency": "monthly"}, format="json")
        again = self.api.post(
            self.url("from_transaction/"), {"transaction": last.id, "frequency": "monthly"}, format="json"
        )
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(RecurringTransaction.objects.count(), 1)

    def test_dismiss(self):
        self.netflix()
        key = f"{self.bank.id}:out:netflix com"
        response = self.api.post(self.url("dismiss_suggestion/"), {"key": key}, format="json")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.api.post(self.url("dismiss_suggestion/"), {"key": key}, format="json").status_code, 204)
        self.assertEqual(RecurringSuggestionDismissal.objects.count(), 1)
        self.assertEqual(self.api.get(self.url("suggestions/")).data, [])

    def test_dismiss_refuses_a_bad_key(self):
        for key in ("nope", "999999:out:x", f"{self.bank.id}:sideways:x", f"{self.bank.id}:out:"):
            with self.subTest(key=key):
                response = self.api.post(self.url("dismiss_suggestion/"), {"key": key}, format="json")
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(RecurringSuggestionDismissal.objects.exists())

    def test_outsiders_are_refused(self):
        last = self.netflix()
        self.api.force_authenticate(user=CustomUser.objects.create_user(username="outsider", password="pass"))
        self.assertIn(self.api.get(self.url("suggestions/")).status_code, (403, 404))
        response = self.api.post(
            self.url("from_transaction/"), {"transaction": last.id, "frequency": "monthly"}, format="json"
        )
        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(RecurringTransaction.objects.exists())
