"""Unit tests for `apps/budget/grid.py`: the multi-month grid's rows and its save validation."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.books.context import current_book
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team

from . import grid
from .ledger import set_budget


class GridTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.book = Team.objects.create(name="Grid", slug="grid-svc").default_book
        expenses = AccountGroup.objects.create(book=cls.book, name="Home", account_type=ACCOUNT_TYPE_EXPENSE)
        banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cls.bank = Account.objects.create(book=cls.book, name="Checking", account_group=banks)
        cls.rent = Account.objects.create(book=cls.book, name="Rent", account_group=expenses)
        cls.hidden = Account.objects.create(book=cls.book, name="Old", account_group=expenses, hidden_from_budget=True)

    def setUp(self):
        context = current_book(self.book)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def test_months_are_clamped(self):
        self.assertEqual(len(grid.grid_months(date(2026, 1, 1), 100)), grid.MAX_MONTHS)
        self.assertEqual(grid.grid_months(date(2026, 11, 1), 0), [date(2026, 11, 1)])
        self.assertEqual(grid.grid_months(date(2026, 11, 1), 3)[-1], date(2027, 1, 1))

    def test_groups_carry_amounts_and_actuals_and_skip_hidden(self):
        set_budget(self.book, self.rent, date(2026, 2, 1), Decimal("900"))
        entry = JournalEntry.objects.create(book=self.book, entry_date=date(2026, 3, 5))
        JournalLine.objects.create(journal_entry=entry, book=self.book, account=self.rent, dr_amount=Decimal("1200"))
        JournalLine.objects.create(journal_entry=entry, book=self.book, account=self.bank, cr_amount=Decimal("1200"))

        groups, modes = grid.grid_groups(self.book, grid.grid_months(date(2026, 1, 1), 12), today=date(2026, 5, 20))
        self.assertEqual([m["key"] for m in modes], list(grid.ACTUAL_MODES))
        (row,) = groups[0]["rows"]
        self.assertEqual(row["id"], self.rent.pk)
        self.assertEqual(row["amounts"], {"2026-02-01": "900.00"})
        # Jan–Apr complete: 1200 / 4.
        self.assertEqual(row["actuals"], {"avg_this_year": "300.00", "avg_last_year": "0.00", "last_month": "0.00"})

    def test_january_has_no_average_this_year(self):
        windows = grid.actual_windows(date(2026, 1, 10))
        self.assertEqual(windows["avg_this_year"][:2], (None, None))
        self.assertEqual(windows["last_month"][:2], (date(2025, 12, 1), date(2025, 12, 1)))

    def test_parse_changes_normalises_and_last_write_wins(self):
        merged = grid.parse_changes(
            self.book,
            [
                {"category_id": self.rent.pk, "month": "2026-03-15", "amount": "10"},
                {"category_id": self.rent.pk, "month": "2026-03-01", "amount": 12.345},
            ],
        )
        self.assertEqual(merged, {(self.rent.pk, date(2026, 3, 1)): Decimal("12.35")})

    def test_parse_changes_refuses_the_whole_batch(self):
        good = {"category_id": self.rent.pk, "month": "2026-03-01", "amount": "1"}
        for changes, message in (
            ("nope", "Invalid request body."),
            ([good, "x"], "Invalid request body."),
            ([good, {**good, "category_id": self.bank.pk}], "Unknown budget category."),
            ([{**good, "month": "soon"}], "Invalid month."),
            ([{**good, "amount": "lots"}], "Invalid amount."),
            ([good] * (grid.MAX_CHANGES + 1), "Too many changes in one request."),
        ):
            with self.subTest(message=message), self.assertRaisesMessage(grid.GridError, message):
                grid.parse_changes(self.book, changes)
