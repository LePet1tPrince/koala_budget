"""Tests for the Unassigned metric (apps/budget/unassigned.py) and where it is shown."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Account, AccountGroup
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .models import Budget, Goal, GoalAllocation
from .services import BudgetService, NetWorthService
from .unassigned import (
    STATE_NEGATIVE,
    STATE_POSITIVE,
    allocation_bar,
    compute_unassigned,
    waterfall,
)

AUG = date(2026, 8, 1)
SEPT = date(2026, 9, 1)
MID_SEPT = date(2026, 9, 10)


class UnassignedFixture(TestCase):
    """The worked example from docs/unassigned-plan.md §1:

    net worth 20,000 + income due 5,000 − rollover 3,500 − this month 4,000
    − goals before 15,000 − goals this month 1,000 = 1,500.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Unassigned Team", slug="unassigned-team")
        asset = AccountGroup.objects.create(team=cls.team, name="Cash", account_type="asset")
        equity = AccountGroup.objects.create(team=cls.team, name="Opening", account_type="equity")
        income = AccountGroup.objects.create(team=cls.team, name="Work", account_type="income")
        expense = AccountGroup.objects.create(team=cls.team, name="Living", account_type="expense")
        cls.checking = Account.objects.create(team=cls.team, name="Checking", account_group=asset)
        cls.opening = Account.objects.create(team=cls.team, name="Opening Balance", account_group=equity)
        cls.salary = Account.objects.create(team=cls.team, name="Salary", account_group=income)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=expense)

        cls.post(date(2026, 8, 2), cls.checking, cls.opening, "20000")
        Budget.objects.create(team=cls.team, month=SEPT, category=cls.salary, budget_amount=Decimal("5000"))
        Budget.objects.create(team=cls.team, month=AUG, category=cls.groceries, budget_amount=Decimal("3500"))
        Budget.objects.create(team=cls.team, month=SEPT, category=cls.groceries, budget_amount=Decimal("4000"))
        cls.goal = Goal.objects.create(team=cls.team, name="House", target_amount=Decimal("50000"))
        GoalAllocation.objects.create(team=cls.team, goal=cls.goal, month=AUG, amount=Decimal("15000"))
        GoalAllocation.objects.create(team=cls.team, goal=cls.goal, month=SEPT, amount=Decimal("1000"))

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(team=cls.team, entry_date=day, description="entry", status="posted")
        JournalLine.objects.create(team=cls.team, journal_entry=entry, account=debit, dr_amount=Decimal(amount))
        JournalLine.objects.create(team=cls.team, journal_entry=entry, account=credit, cr_amount=Decimal(amount))
        return entry


class ComputeUnassignedTest(UnassignedFixture):
    def test_worked_example(self):
        u = compute_unassigned(self.team, SEPT, today=MID_SEPT)
        self.assertEqual(u.net_worth, Decimal("20000"))
        self.assertEqual(u.income_due, Decimal("5000"))
        self.assertEqual(u.rollover, Decimal("3500"))
        self.assertEqual(u.this_month, Decimal("4000"))
        self.assertEqual(u.goals_before, Decimal("15000"))
        self.assertEqual(u.goals_this_month, Decimal("1000"))
        self.assertEqual(u.amount, Decimal("1500"))
        self.assertEqual(u.state, STATE_POSITIVE)
        self.assertEqual(str(u.label), "Unassigned")

    def test_card_agrees_with_the_metric(self):
        # The budget/goals card is built from the same calculation.
        card = NetWorthService.card_data(compute_unassigned(self.team, SEPT, today=MID_SEPT))
        self.assertEqual(card["available"], Decimal("1500"))
        self.assertEqual(card["net_worth"] + card["income_due"] - card["spend"] - card["save"], card["available"])

    def test_income_due_stops_counting_once_the_month_is_over(self):
        # Reviewing September from October: the unreceived income isn't coming.
        u = compute_unassigned(self.team, SEPT, today=date(2026, 10, 5))
        self.assertEqual(u.income_due, Decimal("0"))
        self.assertEqual(u.amount, Decimal("-3500"))
        self.assertEqual(u.state, STATE_NEGATIVE)
        self.assertEqual(str(u.label), "Over-assigned")

    def test_last_months_income_shortfall_does_not_carry(self):
        # Budgeted 5,000 in August and only 4,800 arrived. The missing 200 must not
        # linger as income "still due" in September (the budget page's income
        # rollover would carry it forever).
        Budget.objects.create(team=self.team, month=AUG, category=self.salary, budget_amount=Decimal("5000"))
        self.post(date(2026, 8, 20), self.checking, self.salary, "4800")
        u = compute_unassigned(self.team, SEPT, today=MID_SEPT)
        self.assertEqual(u.income_due, Decimal("5000"))
        self.assertEqual(u.amount, Decimal("1500") + Decimal("4800"))

    def test_income_over_budget_arrives_unassigned(self):
        self.post(date(2026, 9, 5), self.checking, self.salary, "5300")
        u = compute_unassigned(self.team, SEPT, today=MID_SEPT)
        self.assertEqual(u.income_due, Decimal("0"))
        # All 5,300 is in net worth; 300 more than planned has no job yet.
        self.assertEqual(u.amount, Decimal("1800"))

    def test_partly_received_income_counts_only_the_rest(self):
        self.post(date(2026, 9, 5), self.checking, self.salary, "2000")
        u = compute_unassigned(self.team, SEPT, today=MID_SEPT)
        self.assertEqual(u.income_due, Decimal("3000"))
        self.assertEqual(u.amount, Decimal("1500"))

    def test_overspending_is_carried_not_taken_from_unassigned(self):
        before = compute_unassigned(self.team, SEPT, today=MID_SEPT).amount
        # 8,000 of groceries against 7,500 in the envelope (3,500 rolled over + 4,000).
        self.post(date(2026, 9, 6), self.groceries, self.checking, "8000")
        u = compute_unassigned(self.team, SEPT, today=MID_SEPT)
        self.assertEqual(u.envelopes, Decimal("-500"))
        self.assertEqual(u.amount, before)

    def test_archived_goal_releases_its_money(self):
        self.goal.is_archived = True
        self.goal.save()
        u = compute_unassigned(self.team, SEPT, today=MID_SEPT)
        self.assertEqual(u.goals, Decimal("0"))
        self.assertEqual(u.amount, Decimal("17500"))

    def test_voided_entries_do_not_count(self):
        entry = self.post(date(2026, 9, 6), self.groceries, self.checking, "100")
        entry.status = JournalEntry.STATUS_VOID
        entry.save()
        self.assertEqual(compute_unassigned(self.team, SEPT, today=MID_SEPT).amount, Decimal("1500"))

    def test_available_with_previous_matches_two_single_passes(self):
        service = BudgetService(self.team)
        categories = [self.groceries]
        current, previous = service.get_available_with_previous(SEPT, categories)
        self.assertEqual(current, service.get_available_by_category(SEPT, categories))
        self.assertEqual(previous, service.get_available_by_category(AUG, categories))


class DollarMapGeometryTest(UnassignedFixture):
    def test_waterfall_steps_chain_down_to_unassigned(self):
        bars = waterfall(compute_unassigned(self.team, SEPT, today=MID_SEPT))
        self.assertEqual([b["key"] for b in bars][0], "net_worth")
        self.assertEqual(bars[-1]["key"], "unassigned")
        self.assertEqual(bars[-1]["end"], 1500.0)
        steps = [b for b in bars if not b["total"]]
        for previous, step in zip([bars[0]] + steps, steps, strict=False):
            self.assertEqual(step["start"], previous["end"])
        self.assertEqual(steps[-1]["end"], bars[-1]["end"])

    def test_bar_segments_cover_the_claims(self):
        bar = allocation_bar(compute_unassigned(self.team, SEPT, today=MID_SEPT, detail=True))
        self.assertEqual(
            {s["key"]: s["amount"] for s in bar["segments"]},
            {
                "goals": Decimal("16000"),
                "envelopes": Decimal("7500"),
                "unassigned": Decimal("1500"),
            },
        )
        self.assertAlmostEqual(sum(s["pct"] for s in bar["segments"]), 100.0, places=2)
        self.assertEqual(bar["net_worth_pct"], 80.0)
        self.assertEqual(bar["with_due_pct"], 100.0)
        self.assertIsNone(bar["overshoot"])

    def test_overshoot_is_over_assignment_plus_carried_overspending(self):
        # A second envelope overspent by 500 while Groceries still holds 7,500, and
        # September seen from October so nothing is "due": over-assigned by 3,500.
        other = Account.objects.create(team=self.team, name="Fun", account_group=self.groceries.account_group)
        self.post(date(2026, 9, 7), other, self.checking, "500")
        u = compute_unassigned(self.team, SEPT, today=date(2026, 10, 5), detail=True)
        bar = allocation_bar(u)
        self.assertEqual(u.amount, Decimal("-3500"))
        self.assertEqual(bar["overshoot"]["over_assigned"], Decimal("3500"))
        self.assertEqual(bar["overshoot"]["carried"], Decimal("500"))
        claims = sum(s["amount"] for s in bar["segments"])
        self.assertEqual(claims - u.net_worth, Decimal("3500") + Decimal("500"))


class UnassignedViewsTest(UnassignedFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = CustomUser.objects.create_user(username="unassigned@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.outsider = CustomUser.objects.create_user(username="outsider-u@example.com", password="testpass123")
        other = Team.objects.create(name="Elsewhere", slug="elsewhere-u")
        other.members.add(cls.outsider, through_defaults={"role": ROLE_ADMIN})
        state = OnboardingState.objects.create(team=cls.team)
        state.complete()
        state.save()

    def setUp(self):
        self.client.login(username="unassigned@example.com", password="testpass123")

    def test_api_returns_the_figure(self):
        response = self.client.get(reverse("budget:api_unassigned", args=[self.team.slug]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"amount", "raw", "display", "state", "label", "month"})
        self.assertEqual(data["raw"], f"{compute_unassigned(self.team, date.today()).amount:.2f}")

    def test_api_refuses_non_members_and_anonymous(self):
        url = reverse("budget:api_unassigned", args=[self.team.slug])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.login(username="outsider-u@example.com", password="testpass123")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_api_is_read_only(self):
        response = self.client.post(reverse("budget:api_unassigned", args=[self.team.slug]))
        self.assertEqual(response.status_code, 405)

    def test_pill_is_on_app_pages(self):
        response = self.client.get(reverse("budget:budget_home", args=[self.team.slug]))
        self.assertContains(response, 'data-testid="unassigned-pill"')
        self.assertContains(response, 'data-testid="unassigned-pill-compact"')
        self.assertContains(response, reverse("budget:api_unassigned", args=[self.team.slug]))

    def test_dashboard_leads_with_unassigned(self):
        response = self.client.get(reverse("web_team:home", args=[self.team.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="metric-unassigned"')
        self.assertNotContains(response, 'data-testid="metric-budget-available"')
        self.assertEqual(response.context["unassigned"].amount, compute_unassigned(self.team, date.today()).amount)

    def test_dollar_map_report(self):
        url = reverse("reports:dollar_map", args=[self.team.slug])
        response = self.client.get(url, {"month": "2026-09"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["month"], SEPT)
        self.assertContains(response, 'data-testid="dollar-map-waterfall"')
        self.assertContains(response, "House")
        self.assertContains(response, "Groceries")
        self.assertEqual(response.context["waterfall"][-1]["key"], "unassigned")

    def test_dollar_map_ignores_a_malformed_month(self):
        response = self.client.get(reverse("reports:dollar_map", args=[self.team.slug]), {"month": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["month"], date.today().replace(day=1))

    def test_dollar_map_refuses_non_members(self):
        self.client.logout()
        self.client.login(username="outsider-u@example.com", password="testpass123")
        self.assertEqual(self.client.get(reverse("reports:dollar_map", args=[self.team.slug])).status_code, 404)

    def test_reports_home_links_the_dollar_map(self):
        response = self.client.get(reverse("reports:reports_home", args=[self.team.slug]))
        self.assertContains(response, 'data-testid="report-link-dollar-map"')
