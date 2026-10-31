"""Unit tests for `services/manual.py`: adding and editing a feed transaction without a request."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services import manual
from apps.bank_feed.services.errors import FeedError
from apps.books.context import current_book
from apps.journal.models import JournalLine
from apps.teams.models import Team


class ManualServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Manual Svc", slug="manual-svc")
        cls.book = cls.team.default_book
        assets = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        expenses = AccountGroup.objects.create(book=cls.book, name="Spend", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.bank = Account.objects.create(book=cls.book, name="Checking", account_group=assets, has_feed=True)
        cls.food = Account.objects.create(book=cls.book, name="Food", account_group=expenses)
        cls.fuel = Account.objects.create(book=cls.book, name="Fuel", account_group=expenses)

    def setUp(self):
        context = current_book(self.book)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def _create(self, **kwargs):
        fields = {"account_id": self.bank.pk, "date": date(2026, 3, 1), "outflow": Decimal("40")}
        return manual.create_transaction(self.book, **{**fields, **kwargs})

    def test_create_without_category_has_no_entry(self):
        tx = self._create(payee="Corner Shop")
        self.assertIsNone(tx.journal_entry_id)
        self.assertEqual(tx.amount, Decimal("40"))
        self.assertEqual(tx.merchant_name, "Corner Shop")

    def test_create_with_category_books_both_sides(self):
        tx = self._create(category_id=self.food.pk, inflow=Decimal("0"))
        lines = {line.account_id: (line.dr_amount, line.cr_amount) for line in tx.journal_entry.lines.all()}
        self.assertEqual(lines, {self.bank.pk: (0, Decimal("40")), self.food.pk: (Decimal("40"), 0)})

    def test_create_with_splits(self):
        tx = self._create(
            splits=[{"category": self.food.pk, "amount": "25"}, {"category": self.fuel.pk, "amount": "15"}]
        )
        self.assertEqual(tx.journal_entry.lines.count(), 3)

    def test_create_refuses_an_unknown_account_as_not_found(self):
        with self.assertRaises(FeedError) as ctx:
            self._create(account_id=0)
        self.assertEqual((ctx.exception.status, ctx.exception.message), (404, "Bank account not found"))

    def test_create_refuses_splits_that_do_not_add_up_before_writing(self):
        with self.assertRaises(FeedError):
            self._create(splits=[{"category": self.food.pk, "amount": "1"}, {"category": self.fuel.pk, "amount": "1"}])
        self.assertFalse(BankTransaction.objects.filter(book=self.book).exists())

    def test_editable_transaction_refuses_a_void_row(self):
        tx = self._create()
        BankTransaction.objects.filter(pk=tx.pk).update(is_void=True)
        with self.assertRaisesMessage(FeedError, manual.VOID_EDIT_ERROR):
            manual.editable_transaction(self.book, tx.pk)

    def test_update_clearing_the_category_decategorizes(self):
        tx = self._create(category_id=self.food.pk)
        entry_id = tx.journal_entry_id
        tx = manual.update_transaction(
            self.book,
            manual.editable_transaction(self.book, tx.pk),
            account_id=self.bank.pk,
            date=tx.posted_date,
            outflow=Decimal("40"),
        )
        self.assertIsNone(tx.journal_entry_id)
        self.assertFalse(JournalLine.objects.filter(journal_entry_id=entry_id).exists())

    def test_update_refuses_collapsing_a_split_unless_asked(self):
        tx = self._create(
            splits=[{"category": self.food.pk, "amount": "25"}, {"category": self.fuel.pk, "amount": "15"}]
        )
        fields = {
            "account_id": self.bank.pk,
            "date": tx.posted_date,
            "outflow": Decimal("40"),
            "category_id": self.food.pk,
        }
        with self.assertRaisesMessage(FeedError, "split across categories"):
            manual.update_transaction(self.book, manual.editable_transaction(self.book, tx.pk), **fields)
        tx = manual.update_transaction(
            self.book, manual.editable_transaction(self.book, tx.pk), **fields, remove_split=True
        )
        self.assertEqual(tx.journal_entry.lines.count(), 2)

    def test_update_refuses_changing_a_reconciled_amount(self):
        tx = self._create(category_id=self.food.pk)
        tx.journal_entry.lines.filter(account=self.bank).update(is_reconciled=True)
        with self.assertRaisesMessage(FeedError, "before changing its amount"):
            manual.update_transaction(
                self.book,
                manual.editable_transaction(self.book, tx.pk),
                account_id=self.bank.pk,
                date=tx.posted_date,
                outflow=Decimal("41"),
                category_id=self.food.pk,
            )
