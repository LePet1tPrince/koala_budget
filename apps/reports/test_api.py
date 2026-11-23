"""The reports API (`apps/reports/api.py`): the same figures as the pages, with ids and structured drills."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.books.tests.factories import build_book_data, second_book
from apps.monthly_review.models import MonthlyReviewState
from apps.teams.models import Team
from apps.teams.roles import ROLE_MEMBER
from apps.users.models import CustomUser
from apps.utils.months import add_months, format_month

MARK_A = "QQREPORTAQQ"
MARK_B = "QQREPORTBQQ"


class ReportsApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Reports API", slug="reports-api")
        cls.user = CustomUser.objects.create_user(username="reports-api@example.com", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_MEMBER})
        cls.a = build_book_data(cls.team.default_book, MARK_A, cls.user)
        cls.b = build_book_data(second_book(cls.team), MARK_B, cls.user)

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, name):
        return reverse(name, args=self.a.book.url_args)

    def assert_refuses_outsiders(self, name, params=None):
        outsider = CustomUser.objects.create_user(username=f"out-{name}@example.com", password="pass")
        self.client.force_login(outsider)
        self.assertIn(self.client.get(self.url(name), params or {}).status_code, (403, 404))
        self.client.logout()
        self.assertIn(self.client.get(self.url(name), params or {}).status_code, (401, 403))


class SpendingApiTest(ReportsApiTestCase):
    def get(self, **params):
        return self.client.get(self.url("reports:api_spending"), params)

    def test_statement_with_ids_and_period_bounds(self):
        response = self.get(start_date="2026-03-05", end_date="2026-04-20", columns="month")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["start_date"], data["end_date"]), ("2026-03-05", "2026-04-20"))
        self.assertEqual(data["columns"]["selected"], "month")
        self.assertEqual([o["key"] for o in data["columns"]["options"]], ["total", "quarter", "month"])  # Q1 and Q2
        # Each column's drill dates, clamped to the range: no query strings.
        self.assertEqual(
            [(p["start_date"], p["end_date"]) for p in data["periods"]],
            [("2026-03-05", "2026-03-31"), ("2026-04-01", "2026-04-20")],
        )
        group = data["expenses"]["groups"][0]
        self.assertEqual(group["id"], self.a.expense_group.id)
        account = group["accounts"][0]
        self.assertEqual((account["id"], account["name"]), (self.a.groceries.id, self.a.groceries.name))
        self.assertEqual(account["amount"], "42.00")
        self.assertEqual(account["per_period"], ["42.00", "0.00"])
        self.assertEqual(data["stats"]["expenses"], "42.00")
        self.assertTrue(data["has_activity"])
        self.assertNotIn(MARK_B, response.content.decode())
        self.assertNotIn("?start_date", response.content.decode())

    def test_a_column_period_the_range_does_not_span_falls_back_to_total(self):
        data = self.get(start_date="2026-03-01", end_date="2026-03-31", columns="year").json()
        self.assertEqual(data["columns"]["selected"], "total")

    def test_default_range_is_this_year(self):
        data = self.get().json()
        self.assertEqual(data["start_date"], date(date.today().year, 1, 1).isoformat())
        self.assertEqual(data["end_date"], date.today().isoformat())

    def test_validation_errors(self):
        self.assertEqual(self.get(start_date="2026-03-01").status_code, 400)
        self.assertIn("end_date", self.get(start_date="2026-03-31", end_date="2026-03-01").json())
        self.assertIn("start_date", self.get(start_date="March", end_date="2026-03-31").json())
        self.assertIn("columns", self.get(columns="week").json())

    def test_refuses_outsiders(self):
        self.assert_refuses_outsiders("reports:api_spending")


class NetWorthApiTest(ReportsApiTestCase):
    def get(self, **params):
        return self.client.get(self.url("reports:api_net_worth"), params)

    def test_sections_trend_and_composition(self):
        response = self.get(start_month="2026-01", end_month="2026-06")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["start_date"], data["end_date"]), ("2026-01-01", "2026-06-30"))
        assets = next(s for s in data["sections"] if s["key"] == "assets")
        group = assets["groups"][0]
        self.assertEqual(group["id"], self.a.chequing.account_group_id)
        chequing = next(a for a in group["accounts"] if a["id"] == self.a.chequing.id)
        self.assertEqual((chequing["start"], chequing["end"]), ("0.00", "-42.00"))
        self.assertEqual([p["date"] for p in data["trend"]][:2], ["2026-01-31", "2026-02-28"])
        self.assertEqual(data["trend"][2]["net_worth"], "-42.00")
        self.assertEqual(len(data["composition"]["dates"]), 6)
        self.assertEqual(data["stats"]["num_months"], 6)
        self.assertNotIn(MARK_B, response.content.decode())

    def test_never_runs_past_today(self):
        this_month = date.today().replace(day=1)
        data = self.get(start_month=format_month(this_month), end_month=format_month(add_months(this_month, 3))).json()
        self.assertEqual(data["end_date"], date.today().isoformat())

    def test_validation_errors(self):
        self.assertEqual(self.get(start_month="2026-01").status_code, 400)
        self.assertIn("end_month", self.get(start_month="2026-06", end_month="2026-01").json())
        self.assertIn("start_month", self.get(start_month="2026-1", end_month="2026-06").json())

    def test_refuses_outsiders(self):
        self.assert_refuses_outsiders("reports:api_net_worth")


class BudgetGoalsApiTest(ReportsApiTestCase):
    def get(self, **params):
        return self.client.get(self.url("reports:api_budget_goals"), params)

    def test_month_figures_with_goal_ids(self):
        response = self.get(month="2026-03")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["month"], "2026-03")
        self.assertEqual(data["unassigned"]["net_worth"], "-42.00")
        self.assertEqual([step["key"] for step in data["waterfall"]], ["net_worth", "envelopes", "goals", "unassigned"])
        row = data["goal_rows"][0]
        self.assertEqual(row["goal"]["id"], self.a.goal.id)
        self.assertEqual(Decimal(row["assigned"]), Decimal(data["goal_totals"]["assigned"]))
        self.assertNotIn(MARK_B, response.content.decode())

    def test_defaults_to_this_month(self):
        self.assertEqual(self.get().json()["month"], format_month(date.today()))

    def test_malformed_month_is_a_400(self):
        response = self.get(month="2026-03-01")
        self.assertEqual(response.status_code, 400)
        self.assertIn("month", response.json())

    def test_refuses_outsiders(self):
        self.assert_refuses_outsiders("reports:api_budget_goals")


class ReportsHomeApiTest(ReportsApiTestCase):
    def test_last_month_review_status(self):
        last_month = add_months(date.today(), -1)
        url = self.url("reports:api_home")
        self.assertEqual(
            self.client.get(url).json(), {"monthly_review": {"month": format_month(last_month), "reviewed": False}}
        )
        state = MonthlyReviewState.objects.create(book=self.a.book, month=last_month)
        state.complete()
        state.save()
        # Book B's review of the same month says nothing about book A.
        MonthlyReviewState.objects.create(book=self.b.book, month=add_months(last_month, -1))
        self.assertTrue(self.client.get(url).json()["monthly_review"]["reviewed"])

    def test_refuses_outsiders(self):
        self.assert_refuses_outsiders("reports:api_home")
