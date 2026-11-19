"""
The budget API (`apps/budget/api/`): response shapes, permissions, validation and the
write rules its endpoints keep (ledger writes, closed periods, hidden categories).

The endpoint-by-endpoint behaviour the budget page relies on is in `tests.py`
(save, figures, grid, visibility) and `test_goals_envelopes.py` (cover); this file
covers what is new with the API.
"""

import json
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.budget.ledger import budget_amount, budgeted_in_month, set_budget, set_goal_allocation
from apps.budget.models import Goal
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

JUNE = date(2025, 6, 1)
MAY = date(2025, 5, 1)


class BudgetApiFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Budget API", slug="budget-api")
        cls.book = cls.team.default_book
        cls.book.budget_future_income = True
        cls.book.save()
        cls.admin = CustomUser.objects.create_user(username="api-admin@example.com", password="pw")
        cls.member = CustomUser.objects.create_user(username="api-member@example.com", password="pw")
        cls.outsider = CustomUser.objects.create_user(username="api-outsider@example.com", password="pw")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        elsewhere = Team.objects.create(name="Elsewhere API", slug="elsewhere-api")
        elsewhere.members.add(cls.outsider, through_defaults={"role": ROLE_ADMIN})

        income = AccountGroup.objects.create(book=cls.book, name="API Income", account_type=ACCOUNT_TYPE_INCOME)
        expenses = AccountGroup.objects.create(book=cls.book, name="API Expenses", account_type=ACCOUNT_TYPE_EXPENSE)
        assets = AccountGroup.objects.create(book=cls.book, name="API Assets", account_type="asset")
        cls.salary = Account.objects.create(book=cls.book, name="API Salary", account_group=income)
        cls.groceries = Account.objects.create(book=cls.book, name="API Groceries", account_group=expenses)
        cls.rent = Account.objects.create(book=cls.book, name="API Rent", account_group=expenses)
        cls.old = Account.objects.create(book=cls.book, name="API Old", account_group=expenses, hidden_from_budget=True)
        cls.checking = Account.objects.create(book=cls.book, name="API Checking", account_group=assets)

        set_budget(cls.book, cls.groceries, MAY, Decimal("300"))
        set_budget(cls.book, cls.rent, MAY, Decimal("1000"))
        set_budget(cls.book, cls.old, MAY, Decimal("20"))
        set_budget(cls.book, cls.groceries, JUNE, Decimal("100"))
        cls.spend(cls.rent, "1200", date(2025, 6, 3))
        cls.spend(cls.checking, "3000", date(2025, 6, 1), credit=cls.salary)

        cls.goal = Goal.objects.create(book=cls.book, name="API Buffer", target_amount=Decimal("1000"))
        set_goal_allocation(cls.book, cls.goal, JUNE, Decimal("500"))

    @classmethod
    def spend(cls, debit, amount, day, credit=None):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="API")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=Decimal(amount))
        JournalLine.objects.create(
            book=cls.book, journal_entry=entry, account=credit or cls.checking, cr_amount=Decimal(amount)
        )

    def setUp(self):
        self.client.force_login(self.member)

    def url(self, name, **kwargs):
        return reverse(name, kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, **kwargs})

    def post(self, name, body, **kwargs):
        return self.client.post(self.url(name, **kwargs), json.dumps(body), content_type="application/json")


class MonthFiguresShapeTest(BudgetApiFixture):
    def test_tabs_sections_groups_rows(self):
        response = self.client.get(self.url("budget:api_month"), {"month": "2025-06"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"month", "has_categories", "sections", "totals", "unassigned", "cover_goals"})
        self.assertEqual(data["month"], "2025-06")
        self.assertEqual([s["key"] for s in data["sections"]], ["income", "expense"])

        expense = data["sections"][1]
        self.assertEqual(
            set(expense),
            {"key", "label", "income", "totals", "overspent", "hidden_count", "summary", "autofill", "groups"},
        )
        self.assertEqual(expense["overspent"], 1)  # rent: 1000 rolled in, 1200 spent
        self.assertEqual(expense["hidden_count"], 1)
        self.assertEqual(
            [a["action"] for a in expense["autofill"]],
            ["assigned_last_month", "spent_last_month", "assign_zero", "reset_available_zero"],
        )
        visible, hidden = expense["groups"]
        self.assertEqual((visible["name"], visible["hidden"]), ("API Expenses", False))
        self.assertTrue(hidden["hidden"])
        self.assertEqual([r["category_id"] for r in hidden["rows"]], [self.old.pk])

        groceries = next(r for r in visible["rows"] if r["category_id"] == self.groceries.pk)
        self.assertEqual(
            groceries,
            {
                "category_id": self.groceries.pk,
                "name": "API Groceries",
                "account_group_id": self.groceries.account_group_id,
                "account_group_name": "API Expenses",
                "hidden": False,
                "budgeted": "100.00",
                "actual": "0.00",
                "available": "400.00",
                "meter": {"pct": 0.0, "width": 0, "over": False, "label": "0%"},
            },
        )
        rent = next(r for r in visible["rows"] if r["category_id"] == self.rent.pk)
        self.assertEqual((rent["available"], rent["meter"]["over"]), ("-200.00", True))
        self.assertEqual(expense["summary"]["leftover_last_month"], "1320.00")

        self.assertEqual(data["unassigned"]["month"], "2025-06")
        self.assertEqual(data["unassigned"]["expected_income"]["label"], "Expected income")
        self.assertEqual(data["cover_goals"], [{"id": self.goal.pk, "name": "API Buffer", "left": "500.00"}])

    def test_month_is_required(self):
        response = self.client.get(self.url("budget:api_month"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("month", response.json())

    def test_a_book_without_categories(self):
        other = Team.objects.create(name="Empty API", slug="empty-api")
        other.members.add(self.member, through_defaults={"role": ROLE_MEMBER})
        response = self.client.get(reverse("budget:api_month", args=other.default_book.url_args), {"month": "2025-06"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["has_categories"])


class PermissionsTest(BudgetApiFixture):
    READS = {"budget:api_month": {"month": "2025-06"}, "budget:api_grid": {}, "budget:api_unassigned": {}}

    def writes(self):
        return {
            "budget:api_amount": ({}, {"category_id": self.groceries.pk, "month": "2025-06", "amount": "1"}),
            "budget:api_cover": ({}, {"category_id": self.rent.pk, "month": "2025-06", "amount": "1"}),
            "budget:api_autofill": ({}, {"action": "assign_zero", "month": "2025-06"}),
            "budget:api_grid_save": ({}, {"changes": []}),
            "budget:api_category_visibility": ({"pk": self.groceries.pk}, {"hidden": True, "month": "2025-06"}),
        }

    def test_members_read_and_write(self):
        for name, query in self.READS.items():
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name), query).status_code, 200)
        for name, (kwargs, body) in self.writes().items():
            with self.subTest(name=name):
                self.assertEqual(self.post(name, body, **kwargs).status_code, 200, name)

    def test_non_members_get_a_404_and_change_nothing(self):
        self.client.force_login(self.outsider)
        for name, query in self.READS.items():
            with self.subTest(name=name):
                self.assertIn(self.client.get(self.url(name), query).status_code, (403, 404))
        for name, (kwargs, body) in self.writes().items():
            with self.subTest(name=name):
                self.assertIn(self.post(name, body, **kwargs).status_code, (403, 404), name)
        self.assertEqual(budget_amount(self.book, self.groceries, JUNE), Decimal("100"))

    def test_anonymous_is_refused(self):
        self.client.logout()
        for name, query in self.READS.items():
            with self.subTest(name=name):
                self.assertIn(self.client.get(self.url(name), query).status_code, (401, 403))
        for name, (kwargs, body) in self.writes().items():
            with self.subTest(name=name):
                self.assertIn(self.post(name, body, **kwargs).status_code, (401, 403), name)

    def test_an_unknown_book_is_a_404(self):
        url = reverse("budget:api_month", args=[self.team.slug, "no-such-book"])
        self.assertEqual(self.client.get(url, {"month": "2025-06"}).status_code, 404)


class AmountWriteRulesTest(BudgetApiFixture):
    def test_a_closed_period_does_not_lock_the_budget(self):
        """Budget entries are never in a closed period (period_lock exempts them)."""
        self.book.locked_through = date(2025, 12, 31)
        self.book.save(update_fields=["locked_through"])
        response = self.post(
            "budget:api_amount", {"category_id": self.groceries.pk, "month": "2025-06", "amount": "75"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(budget_amount(self.book, self.groceries, JUNE), Decimal("75"))

    def test_validation_errors_name_their_field(self):
        cases = {
            "category_id": {"category_id": self.checking.pk, "month": "2025-06", "amount": "1"},
            "month": {"category_id": self.groceries.pk, "month": "June", "amount": "1"},
            "amount": {"category_id": self.groceries.pk, "month": "2025-06", "amount": "lots"},
        }
        for field, body in cases.items():
            with self.subTest(field=field):
                response = self.post("budget:api_amount", body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertEqual(budget_amount(self.book, self.groceries, JUNE), Decimal("100"))

    def test_income_is_refused_while_the_book_does_not_budget_it(self):
        self.book.budget_future_income = False
        self.book.save(update_fields=["budget_future_income"])
        response = self.post("budget:api_amount", {"category_id": self.salary.pk, "month": "2025-06", "amount": "1"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"category_id": ["Unknown budget category."]})


class CoverApiTest(BudgetApiFixture):
    def test_from_unassigned(self):
        response = self.post("budget:api_cover", {"category_id": self.rent.pk, "month": "2025-06", "amount": "200"})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(
            {k: data[k] for k in ("source", "category_id", "month", "amount", "goal_id", "goal_left")},
            {
                "source": "unassigned",
                "category_id": self.rent.pk,
                "month": "2025-06",
                "amount": "200.00",
                "goal_id": None,
                "goal_left": None,
            },
        )
        self.assertEqual(data["figures"]["sections"][1]["overspent"], 0)

    def test_from_a_goal_by_default_when_one_is_named(self):
        response = self.post(
            "budget:api_cover",
            {"category_id": self.rent.pk, "month": "2025-06", "amount": "200", "goal_id": self.goal.pk},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["source"], response.json()["goal_left"]), ("goal", "300.00"))

    def test_refusals_name_their_field(self):
        cases = {
            "goal_id": {"source": "goal"},
            "amount": {"amount": "-5"},
            "source": {"source": "savings"},
        }
        for field, overrides in cases.items():
            with self.subTest(field=field):
                body = {"category_id": self.rent.pk, "month": "2025-06", "amount": "10", **overrides}
                response = self.post("budget:api_cover", body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        response = self.post("budget:api_cover", {"category_id": self.salary.pk, "month": "2025-06", "amount": "10"})
        self.assertEqual(response.json(), {"category_id": ["Unknown budget category."]})


class AutofillApiTest(BudgetApiFixture):
    def test_assigned_last_month_for_one_tab(self):
        response = self.post(
            "budget:api_autofill", {"action": "assigned_last_month", "month": "2025-06", "section": "expense"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data["action"], data["changed"]), ("assigned_last_month", 2))
        amounts = budgeted_in_month(self.book, JUNE)
        self.assertEqual(amounts[self.groceries.pk], Decimal("300"))
        self.assertEqual(amounts[self.rent.pk], Decimal("1000"))
        # The hidden category is never reached.
        self.assertNotIn(self.old.pk, amounts)
        groceries = next(
            row
            for row in data["figures"]["sections"][1]["groups"][0]["rows"]
            if row["category_id"] == self.groceries.pk
        )
        self.assertEqual(groceries["budgeted"], "300.00")

    def test_only_the_selected_categories(self):
        response = self.post(
            "budget:api_autofill",
            {"action": "assign_zero", "month": "2025-06", "section": "expense", "category_ids": [self.rent.pk]},
        )
        self.assertEqual(response.json()["changed"], 1)
        self.assertEqual(budget_amount(self.book, self.groceries, JUNE), Decimal("100"))

    def test_an_empty_selection_reaches_nothing(self):
        response = self.post("budget:api_autofill", {"action": "assign_zero", "month": "2025-06", "category_ids": []})
        self.assertEqual(response.json()["changed"], 0)
        self.assertEqual(budget_amount(self.book, self.groceries, JUNE), Decimal("100"))

    def test_validation(self):
        self.book.budget_future_income = False
        self.book.save(update_fields=["budget_future_income"])
        cases = {
            "action": {"action": "double_it", "month": "2025-06"},
            "month": {"action": "assign_zero", "month": "2025-06-01"},
            "section": {"action": "assign_zero", "month": "2025-06", "section": "income"},
        }
        for field, body in cases.items():
            with self.subTest(field=field):
                response = self.post("budget:api_autofill", body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertEqual(budget_amount(self.book, self.groceries, JUNE), Decimal("100"))


class RememberedMonthTest(BudgetApiFixture):
    """The budget page changes month in place (through the API) and leaves a cookie; the
    next Budget or Goals page without ?month= opens on the newer of that and the session."""

    def page(self, query=""):
        return self.client.get(self.url("budget:budget_home") + query).context["month"]

    def test_the_cookie_of_an_in_place_change_wins_once(self):
        self.assertEqual(self.page("?month=2025-03-01"), date(2025, 3, 1))
        self.client.cookies["budget_month"] = "2025-07-01.abc1"
        self.assertEqual(self.page(), date(2025, 7, 1))
        self.assertEqual(self.client.get(self.url("budget:goals_list")).context["month"], date(2025, 7, 1))

    def test_a_later_explicit_month_overtakes_the_cookie(self):
        self.client.cookies["budget_month"] = "2025-07-01.abc1"
        self.assertEqual(self.page(), date(2025, 7, 1))
        self.client.get(self.url("budget:goals_list") + "?month=2025-09-01")
        self.assertEqual(self.page(), date(2025, 9, 1))
        # A new in-place change is a new cookie value, and wins again.
        self.client.cookies["budget_month"] = "2025-08-01.def2"
        self.assertEqual(self.page(), date(2025, 8, 1))
