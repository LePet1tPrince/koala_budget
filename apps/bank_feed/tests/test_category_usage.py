"""How often each category is chosen, by direction (`services/category_usage.py`), and the pickers that carry it."""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.categorize import create_entry
from apps.bank_feed.services.category_usage import USAGE_WINDOW_DAYS, category_usage
from apps.books.context import current_book
from apps.journal.services import voiding
from apps.teams.models import Team
from apps.teams.roles import ROLE_MEMBER
from apps.users.models import CustomUser

TODAY = date(2026, 11, 20)


class CategoryUsageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Usage", slug="usage")
        cls.book = cls.team.default_book
        banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cards = AccountGroup.objects.create(book=cls.book, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        spend = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        earn = AccountGroup.objects.create(book=cls.book, name="Earnings", account_type=ACCOUNT_TYPE_INCOME)
        cls.chequing = Account.objects.create(book=cls.book, name="Chequing", account_group=banks, has_feed=True)
        cls.visa = Account.objects.create(book=cls.book, name="Visa", account_group=cards, has_feed=True)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=spend)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=earn)
        cls.member = CustomUser.objects.create_user(username="usage-member", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

    def row(self, amount, category, *, account=None, days_ago=1):
        tx = BankTransaction.objects.create(
            book=self.book,
            account=account or self.chequing,
            amount=Decimal(amount),
            posted_date=TODAY - timedelta(days=days_ago),
            description="Row",
            source="csv",
        )
        with current_book(self.book):
            create_entry(tx, category)
        tx.refresh_from_db()
        return tx

    def usage(self):
        return {u["account_id"]: (u["outflow"], u["inflow"]) for u in category_usage(self.book, today=TODAY)}

    def test_counts_each_category_by_direction(self):
        self.row("12.00", self.groceries)
        self.row("30.00", self.groceries)
        self.row("-5.00", self.groceries)  # a refund
        self.row("-2000.00", self.salary)
        self.assertEqual(self.usage(), {self.groceries.id: (2, 1), self.salary.id: (0, 1)})

    def test_a_transfer_counts_for_the_other_account_on_each_side(self):
        self.row("250.00", self.visa)  # chequing pays the card
        # Chequing's row (money out) chose Visa; the mirror row in Visa's feed
        # (money in) has Chequing at the other end. Neither counts its own account.
        self.assertEqual(self.usage(), {self.visa.id: (1, 0), self.chequing.id: (0, 1)})

    def test_old_and_void_rows_are_left_out(self):
        self.row("12.00", self.groceries, days_ago=USAGE_WINDOW_DAYS + 1)
        void = self.row("12.00", self.groceries)
        with current_book(self.book):
            voiding.void(rows=[void])
        self.assertEqual(self.usage(), {})

    def test_the_pickers_carry_it(self):
        self.row("12.00", self.groceries, days_ago=0)
        api = APIClient()
        api.force_authenticate(user=self.member)
        response = api.get(reverse("bank_feed:bank-feed-pickers", args=self.book.url_args))
        self.assertEqual(response.status_code, 200)
        usage = {u["account_id"]: u for u in response.json()["category_usage"]}
        self.assertEqual(usage[self.groceries.id]["outflow"], 1)
