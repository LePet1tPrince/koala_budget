"""Shared fixture: a team with a chequing account, a credit card, cash and a couple of categories."""

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
from apps.books.context import current_book
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser


class ReconciliationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Rec Team", slug="rec-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="rec-admin", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.member = CustomUser.objects.create_user(username="rec-member", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

        cls.banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cls.cards = AccountGroup.objects.create(book=cls.book, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        cls.spend = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.earn = AccountGroup.objects.create(book=cls.book, name="Earnings", account_type=ACCOUNT_TYPE_INCOME)

        cls.chequing = Account.objects.create(book=cls.book, name="Chequing", account_group=cls.banks, has_feed=True)
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=cls.banks, has_feed=True)
        cls.cash = Account.objects.create(book=cls.book, name="Cash", account_group=cls.banks, has_feed=False)
        cls.card = Account.objects.create(book=cls.book, name="Visa", account_group=cls.cards, has_feed=True)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=cls.spend)
        cls.coffee = Account.objects.create(book=cls.book, name="Coffee", account_group=cls.spend)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=cls.earn)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # --- ledger helpers ------------------------------------------------------

    def entry(self, account, category, amount, *, on=date(2026, 8, 15), description="Tx", reconciled=False, feed=False):
        """
        One posted two-line entry. `amount` is the effect on `account` in LEDGER
        sign (dr - cr): +50 debits the account, -50 credits it.
        """
        amount = Decimal(amount)
        je = JournalEntry.objects.create(
            book=self.book,
            entry_date=on,
            description=description,
            status=JournalEntry.STATUS_POSTED,
        )
        line = JournalLine.objects.create(
            journal_entry=je,
            book=self.book,
            account=account,
            dr_amount=amount if amount > 0 else Decimal("0"),
            cr_amount=-amount if amount < 0 else Decimal("0"),
            is_reconciled=reconciled,
        )
        JournalLine.objects.create(
            journal_entry=je,
            book=self.book,
            account=category,
            dr_amount=-amount if amount < 0 else Decimal("0"),
            cr_amount=amount if amount > 0 else Decimal("0"),
        )
        if feed:
            BankTransaction.objects.create(
                book=self.book,
                account=account,
                amount=-amount,
                posted_date=on,
                description=description,
                source=BankTransaction.SOURCE_CSV,
                journal_entry=je,
            )
        return line

    def feed_tx(self, account, amount, *, on=date(2026, 8, 15), description="Feed"):
        """An uncategorized feed row; `amount` in feed convention (positive = outflow)."""
        return BankTransaction.objects.create(
            book=self.book,
            account=account,
            amount=Decimal(amount),
            posted_date=on,
            description=description,
            source=BankTransaction.SOURCE_CSV,
        )

    def url(self, path):
        return f"/a/{self.team.slug}/{self.book.slug}/{path}"

    def api(self, method, path, data=None, user=None):
        if user is not None:
            self.client.force_authenticate(user=user)
        with current_book(self.book):
            return getattr(self.client, method)(self.url(path), data or {}, format="json")
