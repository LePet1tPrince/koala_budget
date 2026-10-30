"""Unit tests for `services/batch.py`: the batch bar's writes, called without a request."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services import batch
from apps.bank_feed.services.errors import FeedError, RowsRefused
from apps.bank_feed.services.manual import VOID_EDIT_ERROR
from apps.books.context import current_book
from apps.teams.models import Team


class BatchServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.book = Team.objects.create(name="Batch Svc", slug="batch-svc").default_book
        assets = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        expenses = AccountGroup.objects.create(book=cls.book, name="Spend", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.bank = Account.objects.create(book=cls.book, name="Checking", account_group=assets, has_feed=True)
        cls.card = Account.objects.create(book=cls.book, name="Card", account_group=assets, has_feed=True)
        cls.food = Account.objects.create(book=cls.book, name="Food", account_group=expenses)

    def setUp(self):
        context = current_book(self.book)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def _row(self, amount="12.50", account=None):
        return BankTransaction.objects.create(
            book=self.book, account=account or self.bank, amount=Decimal(amount), posted_date=date(2026, 4, 3)
        )

    def test_categorize_creates_entries_and_counts_them(self):
        rows = [self._row(), self._row("-30")]
        self.assertEqual(batch.categorize(self.book, {r.pk for r in rows}, self.food.pk), 2)
        for row in rows:
            row.refresh_from_db()
            self.assertEqual({line.account_id for line in row.journal_entry.lines.all()}, {self.bank.pk, self.food.pk})

    def test_categorize_refuses_a_missing_row_before_writing(self):
        row = self._row()
        with self.assertRaises(FeedError) as ctx:
            batch.categorize(self.book, {row.pk, 0}, self.food.pk)
        self.assertEqual(ctx.exception.status, 404)
        row.refresh_from_db()
        self.assertIsNone(row.journal_entry_id)

    def test_edit_names_every_refused_row(self):
        rows = [self._row(), self._row()]
        BankTransaction.objects.filter(pk__in=[r.pk for r in rows]).update(is_void=True)
        with self.assertRaises(RowsRefused) as ctx:
            batch.edit(self.book, [r.pk for r in rows], description="x")
        self.assertEqual({r["id"] for r in ctx.exception.refused}, {r.pk for r in rows})
        self.assertEqual(ctx.exception.refused[0]["error"], VOID_EDIT_ERROR)

    def test_edit_refuses_a_move_to_an_account_off_the_feed(self):
        with self.assertRaisesMessage(FeedError, "bank feed enabled"):
            batch.edit(self.book, [self._row().pk], account_id=self.food.pk)

    def test_edit_refusal_of_a_category_equal_to_the_row_account(self):
        row = self._row()
        self.assertIsNotNone(batch.edit_refusal(row, self.bank, None, None))
        self.assertIsNone(batch.edit_refusal(row, self.food, None, None))

    def test_edit_applies_only_given_fields(self):
        row = self._row()
        batch.edit(self.book, [row.pk], description="Lunch", payee="Cafe")
        row.refresh_from_db()
        self.assertEqual((row.description, row.merchant_name, row.posted_date), ("Lunch", "Cafe", date(2026, 4, 3)))

    def test_duplicate_skips_reconciled_rows(self):
        plain, reconciled = self._row(), self._row()
        batch.categorize(self.book, {reconciled.pk}, self.food.pk)
        reconciled.refresh_from_db()
        reconciled.journal_entry.lines.filter(account=self.bank).update(is_reconciled=True)
        copies = batch.duplicate(self.book, [plain.pk, reconciled.pk])
        self.assertEqual([c.raw["duplicated_from"] for c in copies], [plain.pk])
        self.assertIsNone(copies[0].journal_entry_id)

    def test_delete_void_leaves_rows_that_count(self):
        live, void = self._row(), self._row()
        BankTransaction.objects.filter(pk=void.pk).update(is_void=True)
        batch.delete_void(self.book, [live.pk, void.pk])
        self.assertEqual(list(BankTransaction.objects.filter(book=self.book)), [live])

    def test_unreconcile_clears_the_rows_own_line(self):
        row = self._row()
        batch.categorize(self.book, {row.pk}, self.food.pk)
        row.refresh_from_db()
        row.journal_entry.lines.update(is_reconciled=True)
        batch.unreconcile(self.book, [row.pk])
        flags = dict(row.journal_entry.lines.values_list("account_id", "is_reconciled"))
        self.assertEqual(flags, {self.bank.pk: False, self.food.pk: True})

    def test_set_void_and_restore(self):
        row = self._row()
        self.assertEqual(len(batch.set_void(self.book, [row.pk])), 1)
        row.refresh_from_db()
        self.assertTrue(row.is_void)
        batch.set_void(self.book, [row.pk], restore=True)
        row.refresh_from_db()
        self.assertFalse(row.is_void)
