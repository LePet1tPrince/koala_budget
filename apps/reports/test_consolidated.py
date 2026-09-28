"""Tests for the three consolidated reports (docs/reports-consolidation.md)."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .consolidated import bucket_for, budget_goals_report, net_worth_report, shift_month, spending_report


class ConsolidatedReportsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Consolidated", slug="consolidated")
        cls.book = cls.team.default_book
        cls.book.budget_future_income = True
        cls.book.save()
        cls.user = CustomUser.objects.create_user(username="cons", email="cons@example.com", password="pw123456!")
        cls.team.membership_set.create(user=cls.user, role=ROLE_ADMIN)

        def group(name, account_type):
            return AccountGroup.objects.create(book=cls.book, name=name, account_type=account_type)

        cls.bank_group = group("Zq Bank", ACCOUNT_TYPE_ASSET)
        cls.card_group = group("Zq Cards", ACCOUNT_TYPE_LIABILITY)
        cls.pay_group = group("Zq Pay", ACCOUNT_TYPE_INCOME)
        cls.home_group = group("Zq Home", ACCOUNT_TYPE_EXPENSE)
        cls.bank = Account.objects.create(book=cls.book, name="Zq Checking", account_group=cls.bank_group)
        cls.card = Account.objects.create(book=cls.book, name="Zq Visa", account_group=cls.card_group)
        cls.salary = Account.objects.create(book=cls.book, name="Zq Salary", account_group=cls.pay_group)
        cls.rent = Account.objects.create(book=cls.book, name="Zq Rent", account_group=cls.home_group)
        cls.food = Account.objects.create(book=cls.book, name="Zq Food", account_group=cls.home_group)

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="t")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=Decimal(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=Decimal(amount))
        return entry

    def setUp(self):
        self.client.login(username="cons", password="pw123456!")

    def url(self, name):
        return reverse(f"reports:{name}", args=self.book.url_args)


class HelpersTest(TestCase):
    def test_bucket_for_range_length(self):
        self.assertEqual(bucket_for(date(2026, 1, 1), date(2027, 12, 31)), "month")
        self.assertEqual(bucket_for(date(2026, 1, 1), date(2028, 1, 1)), "quarter")
        self.assertEqual(bucket_for(date(2016, 1, 1), date(2026, 1, 1)), "year")

    def test_shift_month_crosses_years(self):
        self.assertEqual(shift_month(date(2026, 1, 1), -1), date(2025, 12, 1))
        self.assertEqual(shift_month(date(2026, 12, 1), 1), date(2027, 1, 1))


class SpendingReportTest(ConsolidatedReportsBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.post(date(2026, 1, 5), cls.bank, cls.salary, "3000.00")
        cls.post(date(2026, 1, 6), cls.rent, cls.bank, "1200.00")
        cls.post(date(2026, 2, 3), cls.food, cls.card, "300.00")

    def test_totals_match_the_income_statement(self):
        report = spending_report(self.book, date(2026, 1, 1), date(2026, 2, 28))
        stats = report["stats"]
        self.assertEqual(stats["income"], Decimal("3000.00"))
        self.assertEqual(stats["expenses"], Decimal("1500.00"))
        self.assertEqual(stats["net"], Decimal("1500.00"))
        self.assertEqual(stats["savings_rate"], Decimal("50"))
        self.assertEqual(stats["avg_net"], Decimal("750.00"))
        self.assertEqual(report["period"], "month")
        self.assertEqual(report["chart_data"]["income"], [3000.0, 0.0])
        self.assertEqual(report["chart_data"]["expenses"], [1200.0, 300.0])
        self.assertEqual(report["chart_data"]["net"], [1800.0, -300.0])
        self.assertEqual(len(report["sankey_data"]["expenses"]), 2)

    def test_empty_range_has_no_charts(self):
        report = spending_report(self.book, date(2020, 1, 1), date(2020, 1, 31))
        self.assertIsNone(report["chart_data"])
        self.assertIsNone(report["sankey_data"])
        self.assertIsNone(report["stats"]["savings_rate"])

    def test_view_renders_and_links_accounts_with_range_and_return_to(self):
        response = self.client.get(
            self.url("spending"), {"start_date": "2026-01-01", "end_date": "2026-02-28", "columns": "period"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["by_period"])
        detail = reverse("accounts:account_detail", args=[*self.book.url_args, self.rent.pk])
        self.assertContains(response, f"{detail}?start_date=2026-01-01&amp;end_date=2026-02-28&amp;return_to=")
        self.assertContains(response, "Jan 2026")

    def test_view_defaults_to_year_to_date(self):
        response = self.client.get(self.url("spending"))
        self.assertEqual(response.context["start_date"], date(date.today().year, 1, 1))
        self.assertEqual(response.context["end_date"], date.today())

    def test_bad_dates_fall_back_to_default(self):
        response = self.client.get(self.url("spending"), {"start_date": "nope", "end_date": "2026-01-01"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], date(date.today().year, 1, 1))

    def test_requires_membership(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(self.url("spending")).status_code, 200)


class NetWorthReportTest(ConsolidatedReportsBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.post(date(2025, 12, 20), cls.bank, cls.salary, "1000.00")  # before the range
        cls.post(date(2026, 1, 5), cls.bank, cls.salary, "3000.00")
        cls.post(date(2026, 2, 3), cls.food, cls.card, "300.00")

    def test_start_end_and_change_per_account_and_section(self):
        report = net_worth_report(self.book, date(2026, 1, 1), date(2026, 2, 28))
        assets, liabilities = report["sections"]
        self.assertEqual(
            (assets["start"], assets["end"], assets["change"]), (Decimal("1000"), Decimal("4000"), Decimal("3000"))
        )
        self.assertEqual(liabilities["end"], Decimal("300.00"))
        card_row = liabilities["groups"][0]["rows"][0]
        self.assertEqual((card_row["start"], card_row["change"]), (Decimal("0"), Decimal("300.00")))

        stats = report["stats"]
        self.assertEqual(stats["start_net_worth"], Decimal("1000.00"))
        self.assertEqual(stats["net_worth"], Decimal("3700.00"))
        self.assertEqual(stats["change"], Decimal("2700.00"))
        self.assertEqual(stats["pct_change"], Decimal("270"))
        self.assertEqual(report["chart_data"]["net_worth"], [4000.0, 3700.0])

    def test_composition_bands_sum_to_net_worth(self):
        report = net_worth_report(self.book, date(2026, 1, 1), date(2026, 2, 28))
        composition = report["composition_data"]
        by_name = {g["name"]: g for g in composition["groups"]}
        self.assertEqual(by_name["Zq Bank"]["type"], "asset")
        self.assertEqual(by_name["Zq Cards"]["values"], [0.0, -300.0])  # a debt pulls net worth down
        for month, worth in enumerate(composition["net_worth"]):
            self.assertAlmostEqual(sum(g["values"][month] for g in composition["groups"]), worth)

    def test_composition_keeps_the_sign_of_a_group_that_crosses_zero(self):
        # The card is paid 500 on a 300 balance: 200 in credit, which adds to net worth.
        self.post(date(2026, 3, 2), self.card, self.bank, "500.00")
        composition = net_worth_report(self.book, date(2026, 1, 1), date(2026, 3, 31))["composition_data"]
        card = next(g for g in composition["groups"] if g["name"] == "Zq Cards")
        self.assertEqual(card["values"], [0.0, -300.0, 200.0])

    def test_composition_folds_a_long_tail(self):
        from .consolidated import _fold_side

        series = [{"name": f"G{i}", "values": [float(i)]} for i in range(1, 8)]
        folded = _fold_side(series, 5, "Other")
        self.assertEqual([g["name"] for g in folded], ["G7", "G6", "G5", "G4", "Other"])
        self.assertEqual(folded[-1]["values"], [6.0])  # 1 + 2 + 3

    def test_end_matches_the_balance_sheet(self):
        from .services import ReportService

        report = net_worth_report(self.book, date(2026, 1, 1), date(2026, 2, 28))
        sheet = ReportService(self.book).get_balance_sheet_data(date(2026, 2, 28))
        self.assertEqual(report["stats"]["net_worth"], sheet["net_worth"])
        self.assertEqual(report["stats"]["assets"], sheet["total_assets"])

    def test_view_caps_range_at_today(self):
        response = self.client.get(self.url("net_worth"), {"start_month": "2026-01", "end_month": "2099-12"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["end_date"], date.today())
        self.assertContains(response, "Zq Visa")

    def test_requires_membership(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(self.url("net_worth")).status_code, 200)


class PlanFixture(ConsolidatedReportsBase):
    """June 2026: Food over this month's budget but covered by May's rollover, Rent overspent, one goal."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        may, june = date(2026, 5, 1), date(2026, 6, 1)
        Budget.objects.create(book=cls.book, month=may, category=cls.food, budget_amount=Decimal("400"))
        Budget.objects.create(book=cls.book, month=june, category=cls.food, budget_amount=Decimal("400"))
        Budget.objects.create(book=cls.book, month=june, category=cls.rent, budget_amount=Decimal("1000"))
        Budget.objects.create(book=cls.book, month=june, category=cls.salary, budget_amount=Decimal("3000"))
        cls.post(date(2026, 5, 10), cls.food, cls.bank, "100.00")  # 300 rolls into June
        cls.post(date(2026, 6, 10), cls.food, cls.bank, "600.00")  # over June's 400, covered by rollover
        cls.post(date(2026, 6, 11), cls.rent, cls.bank, "1100.00")  # overspent
        cls.post(date(2026, 6, 1), cls.bank, cls.salary, "2500.00")
        cls.goal = Goal.objects.create(
            book=cls.book, name="Zq Car", target_amount=Decimal("1200"), target_date=date(2026, 11, 30)
        )
        GoalAllocation.objects.create(book=cls.book, goal=cls.goal, month=may, amount=Decimal("200"))
        GoalAllocation.objects.create(book=cls.book, goal=cls.goal, month=june, amount=Decimal("100"))


class BudgetGoalsReportTest(PlanFixture):
    def test_envelopes_are_one_total(self):
        from apps.budget.unassigned import compute_unassigned

        report = budget_goals_report(self.book, date(2026, 6, 1))
        unassigned = compute_unassigned(self.book, date(2026, 6, 1))
        envelopes = report["envelopes"]
        self.assertEqual(envelopes["total"], unassigned.envelopes)
        self.assertEqual(envelopes["total"], envelopes["rollover"] + envelopes["this_month"])
        self.assertEqual(envelopes["overspent"], Decimal("100.00"))  # Rent, carried negative
        self.assertNotIn("spending", report)

    def test_goals_and_unassigned(self):
        from apps.budget.unassigned import compute_unassigned

        report = budget_goals_report(self.book, date(2026, 6, 1))
        row = report["goal_rows"][0]
        self.assertEqual(row["assigned"], Decimal("100"))
        self.assertEqual(row["needed"], Decimal("166.67"))  # (1200 − 200) over the 6 months Jun..Nov
        self.assertEqual(report["goal_totals"]["allocated"], Decimal("300"))
        self.assertEqual(report["unassigned"].amount, compute_unassigned(self.book, date(2026, 6, 1)).amount)
        self.assertEqual(report["waterfall"][-1]["value"], float(report["unassigned"].amount))

    def test_view_renders_month_without_listing_categories(self):
        response = self.client.get(self.url("budget_goals"), {"month": "2026-06"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["prev_month"], date(2026, 5, 1))
        self.assertContains(response, "Zq Car")
        self.assertContains(response, 'data-testid="plan-envelopes-card"')
        self.assertNotContains(response, "Zq Food")
        self.assertNotContains(response, "Zq Rent")

    def test_bad_month_falls_back_to_this_month(self):
        response = self.client.get(self.url("budget_goals"), {"month": "garbage"})
        self.assertEqual(response.context["month"], date.today().replace(day=1))

    def test_requires_membership(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(self.url("budget_goals")).status_code, 200)


class BudgetPageProgressBarTest(PlanFixture):
    """The per-category bars moved from the report onto the budget page itself."""

    def rows(self):
        response = self.client.get(reverse("budget:budget_home", args=self.book.url_args), {"month": "2026-06-01"})
        self.assertEqual(response.status_code, 200)
        return {
            row["category"].name: row
            for section in response.context["sections"]
            for group in section["groups"]
            for row in group["rows"]
        }, response

    def test_expense_bar_counts_the_rollover(self):
        rows, response = self.rows()
        food = rows["Zq Food"]["meter"]
        self.assertEqual(food["width"], 86)  # 600 of 400 budgeted + 300 rolled in
        self.assertFalse(food["over"])  # over this month's budget, but nothing is wrong
        self.assertContains(response, 'data-testid="budget-meter"')

    def test_overspent_bar_is_full_and_red(self):
        rent = self.rows()[0]["Zq Rent"]["meter"]
        self.assertEqual((rent["width"], rent["over"], rent["label"]), (100, True, "110%"))

    def test_income_bar_is_received_of_expected(self):
        salary = self.rows()[0]["Zq Salary"]["meter"]
        self.assertEqual((salary["width"], salary["income"], salary["over"]), (83, True, False))

    def test_unbudgeted_category_shows_no_percentage(self):
        from apps.budget.views import _meter

        meter = _meter("expense", Decimal("0"), Decimal("40"), Decimal("-40"))
        self.assertEqual((meter["label"], meter["width"], meter["over"]), ("—", 100, True))
        self.assertEqual(_meter("expense", Decimal("0"), Decimal("0"), Decimal("0"))["width"], 0)

    def test_autosave_returns_the_new_bar(self):
        import json

        response = self.client.post(
            reverse("budget:budget_save_amount", args=self.book.url_args),
            data=json.dumps({"category_id": self.rent.pk, "month": "2026-06-01", "amount": "2200"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        cell = response.json()["cells"][f"row:{self.rent.pk}:meter"]
        self.assertEqual((cell["width"], cell["value"], cell["tone"]), (50, "50%", ""))


class ReturnToLabelTest(ConsolidatedReportsBase):
    def test_account_page_links_back_to_the_report(self):
        report_path = self.url("spending") + "?start_date=2026-01-01&end_date=2026-01-31"
        detail = reverse("accounts:account_detail", args=[*self.book.url_args, self.rent.pk])
        response = self.client.get(detail, {"return_to": report_path})
        self.assertContains(response, "Back to Income &amp; Spending")
