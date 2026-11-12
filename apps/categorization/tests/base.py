"""A book with a chequing and a savings feed account, a card, and a few categories."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
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
from apps.categorization.models import CategorizationRule
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser


class RuleTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Rules Team", slug="rules-team")
        cls.book = cls.team.default_book
        cls.admin = CustomUser.objects.create_user(username="rules-admin", password="pass")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.member = CustomUser.objects.create_user(username="rules-member", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

        banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cards = AccountGroup.objects.create(book=cls.book, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        spending = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        work = AccountGroup.objects.create(book=cls.book, name="Work", account_type=ACCOUNT_TYPE_INCOME)
        cls.chequing = Account.objects.create(book=cls.book, name="Chequing", account_group=banks, has_feed=True)
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=banks, has_feed=True)
        cls.visa = Account.objects.create(book=cls.book, name="Visa", account_group=cards, has_feed=True)
        cls.coffee = Account.objects.create(book=cls.book, name="Coffee", account_group=spending)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=spending)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=work)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def row(self, description="SQ *BLUE BOTTLE 4417", amount="4.50", account=None, merchant=None, **extra):
        return BankTransaction.objects.create(
            book=self.book,
            account=account or self.chequing,
            posted_date=extra.pop("posted_date", date(2026, 3, 4)),
            description=description,
            merchant_name=merchant,
            amount=Decimal(amount),
            source=extra.pop("source", BankTransaction.SOURCE_CSV),
            **extra,
        )

    def rule(self, category=None, **fields):
        defaults = {
            "name": fields.pop("name", f"Rule {CategorizationRule.objects.count() + 1}"),
            "description_match": "words",
            "description_value": "blue bottle",
        }
        defaults.update(fields)
        return CategorizationRule.objects.create(book=self.book, category=category or self.coffee, **defaults)

    def category_of(self, row):
        row.refresh_from_db()
        if row.journal_entry_id is None:
            return None
        lines = [line for line in row.journal_entry.lines.all() if line.account_id != row.account_id]
        return lines[0].account if len(lines) == 1 else None

    def url(self, path=""):
        return f"/a/{self.team.slug}/{self.book.slug}/bankfeed/rules/{path}"
