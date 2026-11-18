"""Shared fixtures for the rules tests: one book, a chequing feed, a savings feed, a few categories."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.rules.models import Rule
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

TODAY = date.today()


class RulesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Rules Team", slug="rules-team")
        cls.book = cls.team.default_book
        cls.admin = CustomUser.objects.create_user(username="admin@example.com", password="pass")
        cls.member = CustomUser.objects.create_user(username="member@example.com", password="pass")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

        banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        spend = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        earn = AccountGroup.objects.create(book=cls.book, name="Earning", account_type=ACCOUNT_TYPE_INCOME)
        cls.chequing = Account.objects.create(book=cls.book, name="Chequing", account_group=banks, has_feed=True)
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=banks, has_feed=True)
        cls.insurance = Account.objects.create(book=cls.book, name="Car Insurance", account_group=spend)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=spend)
        cls.dining = Account.objects.create(book=cls.book, name="Dining", account_group=spend)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=earn)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)

    def url(self, path):
        return f"/a/{self.team.slug}/{self.book.slug}/{path}"

    def tx(self, description="Purchase", amount="50.00", payee=None, account=None, **kwargs):
        return BankTransaction.objects.create(
            book=self.book,
            account=account or self.chequing,
            posted_date=kwargs.pop("posted_date", TODAY),
            description=description,
            merchant_name=payee,
            amount=Decimal(amount),
            source=kwargs.pop("source", BankTransaction.SOURCE_CSV),
            **kwargs,
        )

    def rule(self, name="Insurance", conditions=None, category=None, accounts=(), **kwargs):
        rule = Rule.objects.create(
            book=self.book,
            name=name,
            conditions=conditions
            if conditions is not None
            else [{"field": "description", "op": "contains", "value": "insurance"}],
            category=category if category is not None else self.insurance,
            **kwargs,
        )
        rule.accounts.set(accounts)
        return rule

    def category_of(self, tx):
        tx.refresh_from_db()
        if not tx.journal_entry_id:
            return None
        lines = [line for line in tx.journal_entry.lines.all() if line.account_id != tx.account_id]
        return lines[0].account if len(lines) == 1 else [line.account for line in lines]
