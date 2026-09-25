from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.budget.models import Budget
from apps.journal.models import JournalEntry, JournalLine
from apps.monthly_review.services.budget import budget_breakdown
from apps.teams.models import Team


class BudgetBreakdownTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Budget Team", slug="budget-team")
        cls.book = cls.team.default_book
        # These tests budget income before it arrives.
        cls.book.budget_future_income = True
        cls.book.save()
        cls.expense_group = AccountGroup.objects.create(
            book=cls.book, name="Everyday", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.income_group = AccountGroup.objects.create(book=cls.book, name="Pay", account_type=ACCOUNT_TYPE_INCOME)
        cls.bank = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        cls.chequing = Account.objects.create(book=cls.book, name="Chequing", account_group=cls.bank)

        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=cls.expense_group)
        cls.dining = Account.objects.create(book=cls.book, name="Dining", account_group=cls.expense_group)
        cls.other = Account.objects.create(book=cls.book, name="Miscellaneous", account_group=cls.expense_group)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=cls.income_group)

    def _spend(self, category, amount, day):
        entry = JournalEntry.objects.create(book=self.book, entry_date=day, description="spend", status="posted")
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=category, dr_amount=amount)
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=self.chequing, cr_amount=amount)

    def _budget(self, category, month, amount):
        Budget.objects.create(book=self.book, category=category, month=month, budget_amount=Decimal(amount))

    def test_overspent_category_with_real_carried_over_balance(self):
        # July: budgeted 200, spent 100 -> available carries +100 into August.
        self._budget(self.groceries, date(2026, 7, 1), "200")
        self._spend(self.groceries, Decimal("100"), date(2026, 7, 10))
        # August: budgeted 200, spent 400 -> available = 200 - 400 + 100 = -100 (a real hole).
        self._budget(self.groceries, date(2026, 8, 1), "200")
        self._spend(self.groceries, Decimal("400"), date(2026, 8, 5))

        breakdown = budget_breakdown(self.book, date(2026, 8, 1))
        self.assertEqual(len(breakdown["overspent"]), 1)
        self.assertEqual(breakdown["overspent"][0]["category"], self.groceries)
        self.assertEqual(breakdown["overspent"][0]["over"], Decimal("200"))
        self.assertEqual(breakdown["overspent"][0]["available"], Decimal("-100"))
        self.assertEqual(breakdown["over_assigned"], [])

    def test_over_assigned_category_covered_by_carry_over(self):
        # July: budgeted 100, spent 50 -> available carries +50 into August.
        self._budget(self.dining, date(2026, 7, 1), "100")
        self._spend(self.dining, Decimal("50"), date(2026, 7, 10))
        # August: budgeted 100, spent 120 -> available = 100 - 120 + 50 = 30 (still positive).
        self._budget(self.dining, date(2026, 8, 1), "100")
        self._spend(self.dining, Decimal("120"), date(2026, 8, 5))

        breakdown = budget_breakdown(self.book, date(2026, 8, 1))
        self.assertEqual(breakdown["overspent"], [])
        self.assertEqual(len(breakdown["over_assigned"]), 1)
        row = breakdown["over_assigned"][0]
        self.assertEqual(row["category"], self.dining)
        self.assertEqual(row["over"], Decimal("20"))
        self.assertEqual(row["available"], Decimal("30"))

    def test_unbudgeted_category_with_spend_is_listed_but_not_overspent(self):
        self._spend(self.other, Decimal("30"), date(2026, 8, 5))

        breakdown = budget_breakdown(self.book, date(2026, 8, 1))
        self.assertEqual(breakdown["overspent"], [])
        self.assertEqual(breakdown["over_assigned"], [])
        rows = [c for g in breakdown["groups"] for c in g["categories"]]
        misc_row = next(r for r in rows if r["name"] == "Miscellaneous")
        self.assertTrue(misc_row["unbudgeted"])
        self.assertEqual(misc_row["spent"], Decimal("30"))
        self.assertEqual(misc_row["assigned"], Decimal("0"))

    def test_groups_ordered_income_first(self):
        self._budget(self.salary, date(2026, 8, 1), "3000")
        self._spend(self.groceries, Decimal("10"), date(2026, 8, 5))
        entry = JournalEntry.objects.create(
            book=self.book, entry_date=date(2026, 8, 1), description="pay", status="posted"
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=self.chequing, dr_amount=Decimal("3000")
        )
        JournalLine.objects.create(book=self.book, journal_entry=entry, account=self.salary, cr_amount=Decimal("3000"))

        breakdown = budget_breakdown(self.book, date(2026, 8, 1))
        group_names = [g["name"] for g in breakdown["groups"]]
        self.assertEqual(group_names, ["Pay", "Everyday"])

    def test_totals_sum_across_groups(self):
        self._budget(self.groceries, date(2026, 8, 1), "200")
        self._spend(self.groceries, Decimal("150"), date(2026, 8, 5))
        self._budget(self.dining, date(2026, 8, 1), "50")
        self._spend(self.dining, Decimal("50"), date(2026, 8, 6))

        breakdown = budget_breakdown(self.book, date(2026, 8, 1))
        self.assertEqual(breakdown["totals"]["assigned"], Decimal("250"))
        self.assertEqual(breakdown["totals"]["spent"], Decimal("200"))

    def test_category_count_reflects_transactions_in_month(self):
        self._spend(self.groceries, Decimal("10"), date(2026, 8, 1))
        self._spend(self.groceries, Decimal("20"), date(2026, 8, 15))
        self._spend(self.groceries, Decimal("5"), date(2026, 7, 1))  # different month, excluded

        breakdown = budget_breakdown(self.book, date(2026, 8, 1))
        rows = [c for g in breakdown["groups"] for c in g["categories"]]
        groceries_row = next(r for r in rows if r["name"] == "Groceries")
        self.assertEqual(groceries_row["count"], 2)
