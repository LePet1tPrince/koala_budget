"""
Goals on the budget page (docs/budget-tabs-goals-plan.md §3): a goal row's
Budgeted is the month's `GoalAllocation`, Available its balance at the month's end.
"""

import json
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .models import Budget, Goal, GoalAccountLink, GoalAllocation
from .services import GoalAllocationError, GoalService
from .unassigned import compute_unassigned
from .views import GOAL_TAB, _budget_figures

AUG = date(2026, 8, 1)
SEPT = date(2026, 9, 1)
OCT = date(2026, 10, 1)
NOV = date(2026, 11, 1)
D = Decimal


class Fixture(TestCase):
    """
    Checking holds 10,000. "Car" (target 5,000) has 1,000 assigned in August, 500 in
    September and 200 already in November; 300 was spent from it in September.
    "House" has nothing assigned, but Savings is linked to it from September and
    received 250 then.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Budget Goals Team", slug="budget-goals-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="budgetgoals@example.com", password="pass12345")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        OnboardingState.objects.create(book=cls.book, completed_at="2026-01-01T00:00:00Z", phase="done")

        assets = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        equity = AccountGroup.objects.create(book=cls.book, name="Opening Balances", account_type="goal")
        expenses = AccountGroup.objects.create(book=cls.book, name="Living", account_type="expense")
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=assets)
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=assets)
        cls.opening = Account.objects.create(book=cls.book, name="Opening Balance", account_group=equity)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=expenses)
        cls.post(AUG, cls.checking, cls.opening, "10000")

        cls.car = Goal.objects.create(book=cls.book, name="Car", target_amount=D("5000"))
        Goal.objects.filter(pk=cls.car.pk).update(created_at="2026-07-15T12:00:00Z")
        cls.aug = GoalAllocation.objects.create(book=cls.book, goal=cls.car, month=AUG, amount=D("1000"))
        cls.sept = GoalAllocation.objects.create(book=cls.book, goal=cls.car, month=SEPT, amount=D("500"))
        GoalAllocation.objects.create(book=cls.book, goal=cls.car, month=NOV, amount=D("200"))
        cls.post(date(2026, 9, 10), cls.car.account, cls.checking, "300")

        cls.house = Goal.objects.create(book=cls.book, name="House", target_amount=D("50000"))
        Goal.objects.filter(pk=cls.house.pk).update(created_at="2026-07-15T12:00:00Z")
        GoalAccountLink.objects.create(book=cls.book, goal=cls.house, account=cls.savings, start_date=SEPT)
        cls.post(date(2026, 9, 5), cls.savings, cls.checking, "250")

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="entry", status="posted")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=D(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=D(amount))
        return entry

    def setUp(self):
        self.client.login(username="budgetgoals@example.com", password="pass12345")

    def goal_section(self, month):
        sections = _budget_figures(self.book, month)["sections"]
        return next(s for s in sections if s["key"] == GOAL_TAB)

    def row(self, goal, month):
        return next((r for r in self.goal_section(month)["rows"] if r["goal"].pk == goal.pk), None)

    def save(self, **body):
        return self.client.post(
            reverse("budget:budget_save_amount", args=self.book.url_args),
            data=json.dumps(body),
            content_type="application/json",
        )


class GoalSectionFiguresTest(Fixture):
    def test_a_goal_row_reads_like_a_category(self):
        row = self.row(self.car, SEPT)
        self.assertEqual(row["budgeted"], D("500"))
        self.assertEqual(row["linked"], D("0"))
        self.assertEqual(row["actual"], D("300"))
        # 1,000 + 500 − 300, as of the end of September.
        self.assertEqual(row["available"], D("1200"))
        self.assertEqual(row["input_value"], "500.00")

    def test_available_ignores_contributions_dated_after_the_month(self):
        """`goal.left` counts November's 200; the row as of September must not."""
        row = self.row(self.car, SEPT)
        self.assertEqual(row["goal"].left, D("1400"))
        self.assertEqual(row["available"], D("1200"))

    def test_linked_money_counts_in_available_but_not_in_budgeted(self):
        row = self.row(self.house, SEPT)
        self.assertEqual(row["budgeted"], D("0"))
        self.assertEqual(row["input_value"], "")
        self.assertEqual(row["linked"], D("250"))
        self.assertEqual(row["available"], D("250"))

    def test_goals_tab_agrees_with_unassigned(self):
        """
        With only active goals, Σ max(0, available) over the goal rows is exactly
        Unassigned's goals term.
        """
        # An overspent goal, to cover that edge.
        trip = Goal.objects.create(book=self.book, name="Trip", target_amount=D("1000"))
        GoalAllocation.objects.create(book=self.book, goal=trip, month=SEPT, amount=D("100"))
        self.post(date(2026, 9, 20), trip.account, self.checking, "400")
        Goal.objects.filter(pk=trip.pk).update(created_at="2026-07-15T12:00:00Z")
        for month in (AUG, SEPT, OCT, NOV):
            rows = self.goal_section(month)["rows"]
            claims = sum((max(r["available"], D("0")) for r in rows), D("0"))
            self.assertEqual(claims, compute_unassigned(self.book, month).goals, month)

    def test_closed_and_archived_goals_have_no_row(self):
        """Only active goals are listed, in every month -- including ones before they closed."""
        GoalService(self.book).close(self.car, SEPT)
        Goal.objects.filter(pk=self.house.pk).update(is_archived=True)
        for month in (AUG, SEPT, OCT, date(2027, 1, 1)):
            self.assertEqual(self.goal_section(month)["rows"], [], month)

    def test_closed_goals_are_not_offered_to_cover_from(self):
        GoalService(self.book).close(self.car, SEPT)
        response = self.client.get(reverse("budget:budget_home", args=self.book.url_args) + "?month=2026-09-01")
        self.assertEqual([g["name"] for g in response.context["cover_goals"]], ["House"])

    def test_a_goal_created_after_the_month_has_no_row_until_it_has_figures(self):
        late = Goal.objects.create(book=self.book, name="Later", target_amount=D("100"))
        self.assertIsNone(self.row(late, AUG))

    def test_meter_is_saved_against_the_target(self):
        row = self.row(self.car, SEPT)
        self.assertEqual(row["meter"]["label"], "30%")  # 1,500 of 5,000
        self.assertFalse(row["meter"]["over"])

    def test_tabs_put_goals_between_income_and_expenses(self):
        self.book.budget_future_income = True
        self.book.save()
        keys = [s["key"] for s in _budget_figures(self.book, SEPT)["sections"]]
        self.assertEqual(keys, ["income", "goal", "expense"])

    def test_the_goals_tab_is_there_without_future_income(self):
        self.book.budget_future_income = False
        self.book.save()
        keys = [s["key"] for s in _budget_figures(self.book, SEPT)["sections"]]
        self.assertEqual(keys, ["goal", "expense"])

    def test_sidebar_summary(self):
        summary = self.goal_section(SEPT)["summary"]
        self.assertEqual(summary["leftover_last_month"], D("1000"))
        self.assertEqual(summary["assigned_this_month"], D("500"))
        self.assertEqual(summary["linked_this_month"], D("250"))
        self.assertEqual(summary["activity_this_month"], D("300"))
        self.assertEqual(summary["available"], D("1450"))

    def test_page_renders_goal_rows_on_the_goals_tab(self):
        url = reverse("budget:budget_home", args=self.book.url_args)
        response = self.client.get(f"{url}?month=2026-09-01&tab=goal")
        self.assertEqual(response.context["budget_tab"], "goal")
        self.assertContains(response, 'data-testid="budget-goal-row"', count=2)
        self.assertContains(response, 'data-testid="budget-goal-linked"', count=1)
        self.assertContains(response, 'data-testid="budget-total-goals"')
        # A goal row is not a category row: the category count is unchanged.
        self.assertContains(response, 'data-testid="budget-row"', count=1)

    def test_cover_dialog_offers_the_month_end_balance(self):
        response = self.client.get(reverse("budget:budget_home", args=self.book.url_args) + "?month=2026-09-01")
        lefts = {g["name"]: g["left"] for g in response.context["cover_goals"]}
        self.assertEqual(lefts, {"Car": "1200.00", "House": "250.00"})


class GoalBudgetSaveTest(Fixture):
    def test_typing_sets_the_months_contribution(self):
        response = self.save(goal_id=self.car.pk, month="2026-09-01", amount="700")
        self.assertEqual(response.status_code, 200)
        self.sept.refresh_from_db()
        # Set, not added: the goals page's buttons add, the budget's field sets.
        self.assertEqual(self.sept.amount, D("700"))
        self.assertEqual(response.json()["amount"], "700.00")

        event = AuditEvent.objects.get(event_type=AuditEvent.GOAL_CONTRIBUTION_EDITED)
        self.assertEqual(event.metadata["from"], "500.00")
        self.assertEqual(D(event.metadata["to"]), D("700"))
        self.assertEqual(event.metadata["via"], "budget")

    def test_a_new_month_creates_the_row(self):
        self.save(goal_id=self.house.pk, month="2026-10-01", amount="120+30")
        self.assertEqual(GoalAllocation.objects.get(goal=self.house, month=OCT).amount, D("150.00"))

    def test_zero_removes_the_row(self):
        self.save(goal_id=self.car.pk, month="2026-09-01", amount="")
        self.assertFalse(GoalAllocation.objects.filter(pk=self.sept.pk).exists())

    def test_response_repaints_the_goal_row_and_unassigned(self):
        before = compute_unassigned(self.book, SEPT).amount
        cells = self.save(goal_id=self.car.pk, month="2026-09-01", amount="700").json()["cells"]
        self.assertEqual(cells[f"goal:{self.car.pk}:available"]["value"], "$1,400.00")
        self.assertEqual(cells[f"goal:{self.car.pk}:budgeted"]["value"], "700.00")
        self.assertEqual(cells["section:goal:budgeted"]["value"], "$700.00")
        self.assertEqual(cells["tab:goal:budgeted"]["value"], "$700.00")
        self.assertEqual(cells["sidebar:goal:assigned"]["value"], "$700.00")
        self.assertEqual(compute_unassigned(self.book, SEPT).amount, before - D("200"))
        self.assertEqual(cells["networth:save"]["value"], "$1,650.00")

    def test_cannot_take_back_money_already_spent(self):
        self.post(date(2026, 9, 25), self.car.account, self.checking, "1300")  # 1,600 spent of 1,700
        response = self.save(goal_id=self.car.pk, month="2026-09-01", amount="0")
        self.assertEqual(response.status_code, 400)
        self.assertIn("only $100.00 is left", response.json()["error"])
        self.sept.refresh_from_db()
        self.assertEqual(self.sept.amount, D("500"))

    def test_closed_and_archived_goals_are_refused(self):
        Goal.objects.filter(pk=self.car.pk).update(closed_at="2026-09-30T00:00:00Z")
        Goal.objects.filter(pk=self.house.pk).update(is_archived=True)
        for goal in (self.car, self.house):
            response = self.save(goal_id=goal.pk, month="2026-10-01", amount="10")
            self.assertEqual(response.status_code, 400)
        self.assertFalse(GoalAllocation.objects.filter(month=OCT).exists())

    def test_another_books_goal_is_refused(self):
        other = Team.objects.create(name="Other Goals Team", slug="other-goals-team")
        foreign = Goal.objects.create(book=other.default_book, name="Foreign", target_amount=D("100"))
        response = self.save(goal_id=foreign.pk, month="2026-09-01", amount="50")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(GoalAllocation.objects.filter(goal=foreign).exists())

    def test_exactly_one_of_goal_and_category(self):
        both = self.save(goal_id=self.car.pk, category_id=self.groceries.pk, month="2026-09-01", amount="5")
        neither = self.save(month="2026-09-01", amount="5")
        self.assertEqual((both.status_code, neither.status_code), (400, 400))
        self.assertFalse(Budget.objects.exists())
        self.sept.refresh_from_db()
        self.assertEqual(self.sept.amount, D("500"))

    def test_junk_amount_is_refused(self):
        response = self.save(goal_id=self.car.pk, month="2026-09-01", amount="lots")
        self.assertEqual(response.status_code, 400)

    def test_goals_page_reads_the_same_contribution(self):
        self.save(goal_id=self.car.pk, month="2026-09-01", amount="650")
        page = self.client.get(reverse("budget:goals_list", args=self.book.url_args) + "?month=2026-09-01")
        item = next(i for i in page.context["goal_items"] if i["goal"].pk == self.car.pk)
        self.assertEqual(item["this_month"], D("650"))

    def test_no_js_post_sets_the_contribution_and_returns_to_the_goals_tab(self):
        url = reverse("budget:budget_home", args=self.book.url_args)
        response = self.client.post(
            f"{url}?month=2026-09-01", {"goal_id": self.car.pk, "budget_month": "2026-09-01", "budget_amount": "640"}
        )
        self.assertRedirects(response, f"{url}?month=2026-09-01&tab=goal", fetch_redirect_response=False)
        self.sept.refresh_from_db()
        self.assertEqual(self.sept.amount, D("640"))

    def test_goals_page_no_js_set_month_refuses_a_closed_goal(self):
        Goal.objects.filter(pk=self.car.pk).update(closed_at="2026-09-30T00:00:00Z")
        self.client.post(
            reverse("budget:goal_allocate", args=[*self.book.url_args, self.car.pk]),
            {"month": "2026-10-01", "amount": "50"},
        )
        self.assertFalse(GoalAllocation.objects.filter(goal=self.car, month=OCT).exists())


class GoalAutofillTest(Fixture):
    def autofill(self, action, follow=False, **extra):
        return self.client.post(
            reverse("budget:budget_autofill", args=self.book.url_args),
            {"month": "2026-10-01", "section": "goal", "action": action, **extra},
            follow=follow,
        )

    def test_assigned_last_month(self):
        response = self.autofill("assigned_last_month")
        url = reverse("budget:budget_home", args=self.book.url_args)
        self.assertRedirects(response, f"{url}?month=2026-10-01&tab=goal", fetch_redirect_response=False)
        self.assertEqual(GoalAllocation.objects.get(goal=self.car, month=OCT).amount, D("500"))
        # House had nothing in September, so October stays empty.
        self.assertFalse(GoalAllocation.objects.filter(goal=self.house, month=OCT).exists())

    def test_monthly_plan(self):
        self.car.monthly_contribution = D("250")
        self.car.save()
        self.autofill("monthly_plan")
        self.assertEqual(GoalAllocation.objects.get(goal=self.car, month=OCT).amount, D("250"))
        # No target date and no contribution: no plan, left alone.
        self.assertFalse(GoalAllocation.objects.filter(goal=self.house, month=OCT).exists())

    def test_only_the_checked_goals(self):
        self.autofill("assigned_last_month", filtered="1", goal_ids=[str(self.house.pk)])
        self.assertFalse(GoalAllocation.objects.filter(goal=self.car, month=OCT).exists())

    def test_a_goal_it_would_overdraw_is_left_alone_and_named(self):
        GoalAllocation.objects.create(book=self.book, goal=self.car, month=OCT, amount=D("100"))
        self.post(date(2026, 10, 2), self.car.account, self.checking, "1450")  # 1,750 spent of 1,800
        response = self.autofill("assign_zero", follow=True)
        self.assertEqual(GoalAllocation.objects.get(goal=self.car, month=OCT).amount, D("100"))
        self.assertContains(response, "Left alone, since it would take back money already spent: Car.")

    def test_never_touches_category_budgets(self):
        Budget.objects.create(book=self.book, category=self.groceries, month=OCT, budget_amount=D("80"))
        self.autofill("assign_zero")
        self.assertEqual(Budget.objects.get(category=self.groceries, month=OCT).budget_amount, D("80"))


class SetMonthAllocationTest(Fixture):
    def test_unchanged_amount_writes_nothing(self):
        old = GoalService(self.book).set_month_allocation(self.car, SEPT, D("500"))
        self.assertEqual(old, D("500"))

    def test_raises_for_a_closed_goal(self):
        Goal.objects.filter(pk=self.car.pk).update(closed_at="2026-09-30T00:00:00Z")
        with self.assertRaises(GoalAllocationError):
            GoalService(self.book).set_month_allocation(self.car, OCT, D("10"))
