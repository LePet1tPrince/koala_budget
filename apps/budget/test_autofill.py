"""Unit tests for `apps/budget/autofill.py`: the sidebar's Auto-Assign actions, without a request."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.books.context import current_book
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team

from . import autofill
from .ledger import budgeted_in_month, set_budget

APRIL, MAY = date(2026, 4, 1), date(2026, 5, 1)


class AutofillTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.book = Team.objects.create(name="Autofill", slug="autofill").default_book
        cls.book.budget_future_income = True
        cls.book.save()
        expenses = AccountGroup.objects.create(book=cls.book, name="Home", account_type=ACCOUNT_TYPE_EXPENSE)
        income = AccountGroup.objects.create(book=cls.book, name="Pay", account_type=ACCOUNT_TYPE_INCOME)
        banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cls.bank = Account.objects.create(book=cls.book, name="Checking", account_group=banks)
        cls.rent = Account.objects.create(book=cls.book, name="Rent", account_group=expenses)
        cls.food = Account.objects.create(book=cls.book, name="Food", account_group=expenses)
        cls.hidden = Account.objects.create(book=cls.book, name="Old", account_group=expenses, hidden_from_budget=True)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=income)

    def setUp(self):
        context = current_book(self.book)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def _spend(self, account, amount, day):
        entry = JournalEntry.objects.create(book=self.book, entry_date=day, status=JournalEntry.STATUS_POSTED)
        JournalLine.objects.create(journal_entry=entry, book=self.book, account=account, dr_amount=amount)
        JournalLine.objects.create(journal_entry=entry, book=self.book, account=self.bank, cr_amount=amount)

    def test_categories_follow_the_tab_and_leave_hidden_ones_out(self):
        self.assertEqual(
            {c.pk for c in autofill.autofill_categories(self.book)}, {self.rent.pk, self.food.pk, self.salary.pk}
        )
        self.assertEqual(
            {c.pk for c in autofill.autofill_categories(self.book, "expense")}, {self.rent.pk, self.food.pk}
        )

    def test_categories_follow_an_explicit_selection_even_when_empty(self):
        self.assertEqual(autofill.autofill_categories(self.book, "expense", {str(self.food.pk)}), [self.food])
        self.assertEqual(autofill.autofill_categories(self.book, "expense", set()), [])

    def test_assigned_last_month(self):
        set_budget(self.book, self.rent, APRIL, Decimal("900"))
        amounts = autofill.autofill(self.book, autofill.ASSIGNED_LAST_MONTH, MAY, [self.rent, self.food])
        self.assertEqual(amounts, {self.rent.pk: Decimal("900"), self.food.pk: Decimal("0")})
        self.assertEqual(budgeted_in_month(self.book, MAY), {self.rent.pk: Decimal("900")})

    def test_spent_last_month(self):
        self._spend(self.food, Decimal("123.45"), date(2026, 4, 10))
        autofill.autofill(self.book, autofill.SPENT_LAST_MONTH, MAY, [self.food])
        self.assertEqual(budgeted_in_month(self.book, MAY), {self.food.pk: Decimal("123.45")})

    def test_reset_available_to_zero(self):
        set_budget(self.book, self.food, APRIL, Decimal("100"))  # 100 rolls into May
        self._spend(self.food, Decimal("30"), date(2026, 5, 3))
        amounts = autofill.autofill(self.book, autofill.RESET_AVAILABLE_ZERO, MAY, [self.food])
        self.assertEqual(amounts, {self.food.pk: Decimal("-70")})

    def test_unknown_action_writes_nothing(self):
        set_budget(self.book, self.rent, MAY, Decimal("5"))
        self.assertEqual(autofill.autofill(self.book, "nope", MAY, [self.rent]), {})
        self.assertEqual(budgeted_in_month(self.book, MAY), {self.rent.pk: Decimal("5")})
