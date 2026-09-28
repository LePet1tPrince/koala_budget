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
OCT = date(2026, 10, 1)


class UnassignedFixture(TestCase):
    """The worked example from docs/unassigned-plan.md §1:

    net worth 20,000 + income due 5,000 − envelopes 7,500 (3,500 rolled over + 4,000)
    − goals 16,000 = 1,500.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Unassigned Team", slug="unassigned-team")
        cls.book = cls.team.default_book
        # The worked example budgets September's salary before it lands.
        cls.book.budget_future_income = True
        cls.book.save()
        asset = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        equity = AccountGroup.objects.create(book=cls.book, name="Opening", account_type="equity")
        income = AccountGroup.objects.create(book=cls.book, name="Work", account_type="income")
        expense = AccountGroup.objects.create(book=cls.book, name="Living", account_type="expense")
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=asset)
        cls.opening = Account.objects.create(book=cls.book, name="Opening Balance", account_group=equity)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=income)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=expense)
        cls.fun = Account.objects.create(book=cls.book, name="Fun", account_group=expense)

        cls.post(date(2026, 8, 2), cls.checking, cls.opening, "20000")
        Budget.objects.create(book=cls.book, month=SEPT, category=cls.salary, budget_amount=Decimal("5000"))
        Budget.objects.create(book=cls.book, month=AUG, category=cls.groceries, budget_amount=Decimal("3500"))
        Budget.objects.create(book=cls.book, month=SEPT, category=cls.groceries, budget_amount=Decimal("4000"))
        cls.goal = Goal.objects.create(book=cls.book, name="House", target_amount=Decimal("50000"))
        GoalAllocation.objects.create(book=cls.book, goal=cls.goal, month=AUG, amount=Decimal("15000"))
        GoalAllocation.objects.create(book=cls.book, goal=cls.goal, month=SEPT, amount=Decimal("1000"))

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="entry", status="posted")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=Decimal(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=Decimal(amount))
        return entry

    def budget(self, category, month, amount):
        Budget.objects.update_or_create(
            book=self.book, category=category, month=month, defaults={"budget_amount": Decimal(amount)}
        )

    def unassigned(self, month=SEPT):
        return compute_unassigned(self.book, month).amount


class ComputeUnassignedTest(UnassignedFixture):
    def test_worked_example(self):
        u = compute_unassigned(self.book, SEPT)
        self.assertEqual(u.net_worth, Decimal("20000"))
        self.assertEqual(u.income_due, Decimal("5000"))
        self.assertEqual(u.envelopes, Decimal("7500"))
        self.assertEqual(u.goals, Decimal("16000"))
        self.assertEqual(u.overspent, Decimal("0"))
        self.assertEqual(u.amount, Decimal("1500"))
        self.assertEqual(u.state, STATE_POSITIVE)
        self.assertEqual(str(u.label), "Unassigned")

    def test_card_agrees_with_the_metric(self):
        # The budget/goals card is built from the same calculation.
        card = NetWorthService.card_data(compute_unassigned(self.book, SEPT))
        self.assertEqual(card["available"], Decimal("1500"))
        self.assertEqual(card["net_worth"] + card["income_due"] - card["spend"] - card["save"], card["available"])

    def test_voided_entries_do_not_count(self):
        entry = self.post(date(2026, 9, 6), self.groceries, self.checking, "100")
        entry.status = JournalEntry.STATUS_VOID
        entry.save()
        self.assertEqual(self.unassigned(), Decimal("1500"))

    def test_equity_entries_move_it(self):
        # An opening balance or reconciliation adjustment changes net worth and nothing else.
        self.post(date(2026, 9, 3), self.checking, self.opening, "250")
        self.assertEqual(self.unassigned(), Decimal("1750"))

    def test_available_with_previous_matches_two_single_passes(self):
        service = BudgetService(self.book)
        categories = [self.groceries]
        current, previous = service.get_available_with_previous(SEPT, categories)
        self.assertEqual(current, service.get_available_by_category(SEPT, categories))
        self.assertEqual(previous, service.get_available_by_category(AUG, categories))


class IncomeTest(UnassignedFixture):
    """Budgeted income counts as coming; the difference rolls month to month."""

    def test_raising_last_months_income_budget_raises_it(self):
        self.budget(self.salary, AUG, "1000")
        self.assertEqual(self.unassigned(), Decimal("2500"))

    def test_raising_this_months_income_budget_raises_it(self):
        self.budget(self.salary, SEPT, "5600")
        self.assertEqual(self.unassigned(), Decimal("2100"))

    def test_next_months_income_budget_does_not_count_yet(self):
        self.budget(self.salary, OCT, "5000")
        self.assertEqual(self.unassigned(), Decimal("1500"))

    def test_income_arriving_within_budget_changes_nothing(self):
        self.post(date(2026, 9, 5), self.checking, self.salary, "2000")
        u = compute_unassigned(self.book, SEPT)
        self.assertEqual(u.income_due, Decimal("3000"))
        self.assertEqual(u.amount, Decimal("1500"))

    def test_last_months_income_arriving_within_budget_changes_nothing(self):
        self.budget(self.salary, AUG, "1000")
        before = self.unassigned()
        self.post(date(2026, 8, 20), self.checking, self.salary, "400")
        self.assertEqual(self.unassigned(), before)

    def test_a_shortfall_rolls_forward_as_still_due(self):
        # Budgeted 5,000 in August and 4,800 arrived: the 200 is still expected.
        self.budget(self.salary, AUG, "5000")
        self.post(date(2026, 8, 20), self.checking, self.salary, "4800")
        u = compute_unassigned(self.book, SEPT)
        self.assertEqual(u.income_due, Decimal("5200"))
        self.assertEqual(u.amount, Decimal("6500"))
        # Lowering the budget is how you say it isn't coming.
        self.budget(self.salary, SEPT, "4800")
        self.assertEqual(compute_unassigned(self.book, SEPT).income_due, Decimal("5000"))

    def test_income_over_budget_arrives_unassigned(self):
        self.post(date(2026, 9, 5), self.checking, self.salary, "5300")
        u = compute_unassigned(self.book, SEPT)
        self.assertEqual(u.income_due, Decimal("0"))
        self.assertEqual(u.amount, Decimal("1800"))

    def test_last_months_income_over_budget_arrives_unassigned(self):
        # September's salary is in, so August's extra has nothing left to fill.
        self.post(date(2026, 9, 5), self.checking, self.salary, "5000")
        self.post(date(2026, 8, 25), self.checking, self.salary, "300")
        self.assertEqual(self.unassigned(), Decimal("1800"))

    def test_a_surplus_rolls_forward_against_income_still_expected(self):
        # 300 arrived in August with nothing budgeted; September's 5,000 hasn't come.
        # The surplus counts once: it fills part of September's expected income.
        self.post(date(2026, 8, 25), self.checking, self.salary, "300")
        u = compute_unassigned(self.book, SEPT)
        self.assertEqual(u.income_due, Decimal("4700"))
        self.assertEqual(u.amount, Decimal("1500"))

    def test_a_late_paycheque_counts_once(self):
        # 5,000 budgeted in September and October; nothing in September, 10,000 in October.
        self.budget(self.salary, OCT, "5000")
        on_time = self.post(date(2026, 9, 25), self.checking, self.salary, "5000")
        self.post(date(2026, 10, 25), self.checking, self.salary, "5000")
        expected = self.unassigned(OCT)
        on_time.delete()
        self.post(date(2026, 10, 2), self.checking, self.salary, "5000")
        self.assertEqual(self.unassigned(OCT), expected)
        self.assertEqual(compute_unassigned(self.book, OCT).income_due, Decimal("0"))

    def test_with_future_income_off_only_received_income_counts(self):
        self.book.budget_future_income = False
        self.book.save()
        u = compute_unassigned(self.book, SEPT)
        self.assertEqual(u.income_due, Decimal("0"))
        self.assertEqual(u.amount, Decimal("-3500"))
        self.assertEqual(u.state, STATE_NEGATIVE)
        self.assertEqual(str(u.label), "Over-assigned")


class ExpenseTest(UnassignedFixture):
    """An envelope claims its unspent budget; overspending comes out of Unassigned."""

    def test_raising_last_months_budget_lowers_it(self):
        self.budget(self.groceries, AUG, "4000")
        self.assertEqual(self.unassigned(), Decimal("1000"))

    def test_raising_this_months_budget_lowers_it(self):
        self.budget(self.groceries, SEPT, "4600")
        self.assertEqual(self.unassigned(), Decimal("900"))

    def test_next_months_budget_does_not_count_yet(self):
        self.budget(self.groceries, OCT, "4000")
        self.assertEqual(self.unassigned(), Decimal("1500"))

    def test_spending_within_budget_changes_nothing(self):
        self.post(date(2026, 8, 12), self.groceries, self.checking, "3000")
        self.post(date(2026, 9, 12), self.groceries, self.checking, "4000")
        self.assertEqual(self.unassigned(), Decimal("1500"))

    def test_overspending_this_month_comes_out(self):
        # 8,000 of groceries against 7,500 in the envelope (3,500 rolled over + 4,000).
        self.post(date(2026, 9, 6), self.groceries, self.checking, "8000")
        u = compute_unassigned(self.book, SEPT)
        self.assertEqual(u.envelopes, Decimal("0"))
        self.assertEqual(u.overspent, Decimal("500"))
        self.assertEqual(u.amount, Decimal("1000"))

    def test_unbudgeted_spending_comes_out(self):
        self.post(date(2026, 9, 6), self.fun, self.checking, "120")
        self.assertEqual(self.unassigned(), Decimal("1380"))

    def test_overspending_last_month_comes_out(self):
        self.budget(self.fun, AUG, "100")
        self.assertEqual(self.unassigned(), Decimal("1400"))
        self.post(date(2026, 8, 6), self.fun, self.checking, "150")
        self.assertEqual(self.unassigned(), Decimal("1350"))

    def test_filling_the_hole_does_not_move_it_again(self):
        self.post(date(2026, 9, 6), self.fun, self.checking, "120")
        self.assertEqual(self.unassigned(), Decimal("1380"))
        # The hole is carried, never reset: the first 120 of a budget fills it...
        self.budget(self.fun, SEPT, "120")
        self.assertEqual(self.unassigned(), Decimal("1380"))
        # ...and only what goes past it is a new claim.
        self.budget(self.fun, SEPT, "200")
        self.assertEqual(self.unassigned(), Decimal("1300"))

    def test_last_months_hole_is_filled_by_this_months_budget(self):
        self.post(date(2026, 8, 6), self.fun, self.checking, "120")
        self.assertEqual(self.unassigned(), Decimal("1380"))
        self.budget(self.fun, SEPT, "300")
        # 120 of it fills August's hole; 180 is left in the envelope.
        self.assertEqual(self.unassigned(), Decimal("1200"))
        self.assertEqual(compute_unassigned(self.book, SEPT).envelopes, Decimal("7680"))

    def test_covering_from_unassigned_is_free(self):
        self.post(date(2026, 9, 6), self.fun, self.checking, "120")
        BudgetService(self.book).raise_budget(self.fun, SEPT, Decimal("120"))
        self.assertEqual(self.unassigned(), Decimal("1380"))

    def test_covering_from_a_goal_gives_the_goals_money_back(self):
        from .services import GoalService

        self.post(date(2026, 9, 6), self.fun, self.checking, "120")
        GoalService(self.book).cover_from_goal(self.goal, self.fun, SEPT, Decimal("120"))
        self.assertEqual(self.unassigned(), Decimal("1500"))


class GoalTest(UnassignedFixture):
    """A goal claims what's left in it; overspending it comes out of Unassigned."""

    def spend_from_goal(self, day, amount):
        self.post(day, self.goal.account, self.checking, amount)

    def test_allocating_last_month_lowers_it(self):
        GoalAllocation.objects.filter(goal=self.goal, month=AUG).update(amount=Decimal("15500"))
        self.assertEqual(self.unassigned(), Decimal("1000"))

    def test_allocating_this_month_lowers_it(self):
        GoalAllocation.objects.filter(goal=self.goal, month=SEPT).update(amount=Decimal("1200"))
        self.assertEqual(self.unassigned(), Decimal("1300"))

    def test_next_months_allocation_does_not_count_yet(self):
        GoalAllocation.objects.create(book=self.book, goal=self.goal, month=OCT, amount=Decimal("1000"))
        self.assertEqual(self.unassigned(), Decimal("1500"))
        # Seen from October it is a claim like any other.
        self.assertEqual(self.unassigned(OCT), Decimal("500"))

    def test_spending_within_the_goal_changes_nothing(self):
        self.spend_from_goal(date(2026, 8, 20), "6000")
        self.spend_from_goal(date(2026, 9, 20), "10000")
        self.assertEqual(self.unassigned(), Decimal("1500"))

    def test_overspending_a_goal_comes_out(self):
        self.spend_from_goal(date(2026, 9, 20), "17000")
        u = compute_unassigned(self.book, SEPT)
        self.assertEqual(u.goals, Decimal("0"))
        self.assertEqual(u.goals_overspent, Decimal("1000"))
        self.assertEqual(u.amount, Decimal("500"))
        # Paying it back fills the hole first, which moves nothing.
        GoalAllocation.objects.filter(goal=self.goal, month=SEPT).update(amount=Decimal("2000"))
        self.assertEqual(self.unassigned(), Decimal("500"))

    def test_spending_after_the_month_does_not_count_yet(self):
        self.spend_from_goal(date(2026, 10, 3), "17000")
        self.assertEqual(self.unassigned(), Decimal("1500"))

    def test_archived_goal_releases_its_money(self):
        self.goal.is_archived = True
        self.goal.save()
        u = compute_unassigned(self.book, SEPT)
        self.assertEqual(u.goals, Decimal("0"))
        self.assertEqual(u.amount, Decimal("17500"))


class DollarMapGeometryTest(UnassignedFixture):
    def test_waterfall_steps_chain_down_to_unassigned(self):
        bars = waterfall(compute_unassigned(self.book, SEPT))
        self.assertEqual([b["key"] for b in bars], ["net_worth", "income_due", "envelopes", "goals", "unassigned"])
        self.assertEqual(bars[-1]["end"], 1500.0)
        steps = [b for b in bars if not b["total"]]
        for previous, step in zip([bars[0]] + steps, steps, strict=False):
            self.assertEqual(step["start"], previous["end"])
        self.assertEqual(steps[-1]["end"], bars[-1]["end"])

    def test_bar_segments_cover_the_claims(self):
        bar = allocation_bar(compute_unassigned(self.book, SEPT, detail=True))
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

    def test_overshoot_is_over_assignment_only(self):
        # Overspending isn't a claim, so it can't push the bar past what you have.
        self.post(date(2026, 9, 7), self.fun, self.checking, "500")
        self.assertIsNone(allocation_bar(compute_unassigned(self.book, SEPT, detail=True))["overshoot"])
        self.budget(self.groceries, SEPT, "9000")
        u = compute_unassigned(self.book, SEPT, detail=True)
        bar = allocation_bar(u)
        self.assertEqual(u.amount, Decimal("-4000"))
        self.assertEqual(bar["overshoot"]["over_assigned"], Decimal("4000"))
        claims = sum(s["amount"] for s in bar["segments"])
        self.assertEqual(claims - (u.net_worth + u.income_due), Decimal("4000"))

    def test_detail_lists_overspent_envelopes_and_goals(self):
        self.post(date(2026, 9, 7), self.fun, self.checking, "500")
        u = compute_unassigned(self.book, SEPT, detail=True)
        fun = next(e for e in u.detail["envelopes"] if e["name"] == "Fun")
        self.assertEqual(fun["amount"], Decimal("-500"))
        self.assertEqual(u.detail["goals"][0]["amount"], Decimal("16000"))
        self.assertEqual(u.detail["income_due"], [{"name": "Salary", "amount": Decimal("5000")}])


class UnassignedViewsTest(UnassignedFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = CustomUser.objects.create_user(username="unassigned@example.com", password="testpass123")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.outsider = CustomUser.objects.create_user(username="outsider-u@example.com", password="testpass123")
        other = Team.objects.create(name="Elsewhere", slug="elsewhere-u")
        other.members.add(cls.outsider, through_defaults={"role": ROLE_ADMIN})
        state = OnboardingState.objects.create(book=cls.book)
        state.complete()
        state.save()

    def setUp(self):
        self.client.login(username="unassigned@example.com", password="testpass123")

    def test_api_returns_the_figure(self):
        response = self.client.get(reverse("budget:api_unassigned", args=[self.team.slug, self.book.slug]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"amount", "raw", "display", "state", "label", "month"})
        self.assertEqual(data["raw"], f"{compute_unassigned(self.book, date.today()).amount:.2f}")

    def test_api_refuses_non_members_and_anonymous(self):
        url = reverse("budget:api_unassigned", args=[self.team.slug, self.book.slug])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.login(username="outsider-u@example.com", password="testpass123")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_api_is_read_only(self):
        response = self.client.post(reverse("budget:api_unassigned", args=[self.team.slug, self.book.slug]))
        self.assertEqual(response.status_code, 405)

    def test_pill_is_on_app_pages(self):
        response = self.client.get(reverse("budget:budget_home", args=[self.team.slug, self.book.slug]))
        self.assertContains(response, 'data-testid="unassigned-pill"')
        self.assertContains(response, 'data-testid="unassigned-pill-compact"')
        self.assertContains(response, reverse("budget:api_unassigned", args=[self.team.slug, self.book.slug]))

    def test_dashboard_leads_with_unassigned(self):
        response = self.client.get(reverse("web_book:home", args=[self.team.slug, self.book.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="metric-unassigned"')
        self.assertNotContains(response, 'data-testid="metric-budget-available"')
        self.assertEqual(response.context["unassigned"].amount, compute_unassigned(self.book, date.today()).amount)

    def test_dollar_map_report(self):
        url = reverse("reports:dollar_map", args=[self.team.slug, self.book.slug])
        response = self.client.get(url, {"month": "2026-09"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["month"], SEPT)
        self.assertContains(response, 'data-testid="dollar-map-waterfall"')
        self.assertContains(response, "House")
        self.assertContains(response, "Groceries")
        self.assertEqual(response.context["waterfall"][-1]["key"], "unassigned")

    def test_dollar_map_uses_the_shared_month_picker(self):
        # The picker navigates with ?month=YYYY-MM-DD; the view must read that form too.
        response = self.client.get(
            reverse("reports:dollar_map", args=[self.team.slug, self.book.slug]), {"month": "2026-08-01"}
        )
        self.assertEqual(response.context["month"], AUG)
        self.assertContains(response, 'id="budget-month-picker" data-month="2026-08-01"')
        self.assertContains(response, "budget-month-picker-app")

    def test_dollar_map_ignores_a_malformed_month(self):
        response = self.client.get(
            reverse("reports:dollar_map", args=[self.team.slug, self.book.slug]), {"month": "nope"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["month"], date.today().replace(day=1))

    def test_dollar_map_refuses_non_members(self):
        self.client.logout()
        self.client.login(username="outsider-u@example.com", password="testpass123")
        self.assertEqual(
            self.client.get(reverse("reports:dollar_map", args=[self.team.slug, self.book.slug])).status_code, 404
        )

    def test_reports_home_links_the_dollar_map(self):
        response = self.client.get(reverse("reports:reports_home", args=[self.team.slug, self.book.slug]))
        self.assertContains(response, 'data-testid="report-link-dollar-map"')
