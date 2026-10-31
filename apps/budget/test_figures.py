"""Unit tests for `apps/budget/figures.py`: the budget page's numbers, without a request."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.books.context import current_book
from apps.teams.models import Team

from .figures import budget_categories, budget_cells, budget_figures, budget_tab_keys, meter
from .ledger import set_budget

MONTH = date(2026, 5, 1)


class FiguresTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.book = Team.objects.create(name="Figures", slug="figures").default_book
        cls.book.budget_future_income = True
        cls.book.save()
        expenses = AccountGroup.objects.create(book=cls.book, name="Home", account_type=ACCOUNT_TYPE_EXPENSE)
        income = AccountGroup.objects.create(book=cls.book, name="Pay", account_type=ACCOUNT_TYPE_INCOME)
        cls.rent = Account.objects.create(book=cls.book, name="Rent", account_group=expenses)
        cls.power = Account.objects.create(book=cls.book, name="Power", account_group=expenses, hidden_from_budget=True)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=income)

    def setUp(self):
        context = current_book(self.book)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def test_categories_list_income_before_expenses(self):
        self.assertEqual(list(budget_categories(self.book)), [self.salary, self.power, self.rent])

    def test_tab_keys_follow_future_income(self):
        self.assertEqual(budget_tab_keys(self.book), ["income", "expense"])
        self.book.budget_future_income = False
        self.assertEqual(budget_tab_keys(self.book), ["expense"])

    def test_figures_total_sections_and_collect_hidden_categories(self):
        set_budget(self.book, self.rent, MONTH, Decimal("1200"))
        set_budget(self.book, self.power, MONTH, Decimal("80"))
        figures = budget_figures(self.book, MONTH)
        expense = next(section for section in figures["sections"] if section["key"] == "expense")
        self.assertEqual(expense["totals"]["budgeted"], Decimal("1280"))
        self.assertEqual(expense["hidden_count"], 1)
        hidden = expense["groups"][-1]
        self.assertTrue(hidden["hidden"])
        self.assertEqual([row["category"] for row in hidden["rows"]], [self.power])
        self.assertEqual(figures["sidebar_summary"]["expense"]["assigned_this_month"], Decimal("1280"))

    def test_cells_carry_every_repainted_figure(self):
        set_budget(self.book, self.rent, MONTH, Decimal("1200"))
        cells = budget_cells(budget_figures(self.book, MONTH))
        self.assertEqual(cells[f"row:{self.rent.pk}:available"], {"value": "$1,200.00", "tone": "pos"})
        self.assertEqual(cells[f"row:{self.rent.pk}:budgeted"]["value"], "1200.00")
        self.assertEqual(cells["section:expense:budgeted"]["value"], "$1,200.00")
        self.assertTrue(cells["tab:expense:overspent"]["hidden"])
        for key in ("networth:net_worth", "networth:label", "sidebar:expense:available", "group:expense:0:budgeted"):
            self.assertIn(key, cells)

    def test_meter(self):
        # Spent 50 of a 100 budget with nothing rolled in.
        self.assertEqual(meter("expense", Decimal("100"), Decimal("50"), Decimal("50"))["width"], 50)
        # Rolled-in money widens the whole: 50 spent of 100 budget + 100 carried in.
        self.assertEqual(meter("expense", Decimal("100"), Decimal("50"), Decimal("150"))["width"], 25)
        over = meter("expense", Decimal("100"), Decimal("150"), Decimal("-50"))
        self.assertEqual((over["width"], over["over"], over["label"]), (100, True, "150%"))
        income = meter("income", Decimal("1000"), Decimal("250"), Decimal("-750"))
        self.assertEqual((income["width"], income["over"], income["income"]), (25, False, True))
        self.assertEqual(meter("expense", Decimal("0"), Decimal("0"), Decimal("0"))["label"], "—")
