"""Tests for goal plans (apps/budget/plans.py, docs/goal-plans-plan.md)."""

import ast
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Account, AccountGroup
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team

from . import goal_links, plans
from .models import Goal, GoalAccountLink, GoalAllocation, GoalPlan
from .services import GoalService, goal_monthly
from .unassigned import compute_unassigned

AUG = date(2026, 8, 1)
SEPT = date(2026, 9, 1)
OCT = date(2026, 10, 1)
NOV = date(2026, 11, 1)
DEC = date(2026, 12, 1)
JAN = date(2027, 1, 1)


def today_is(day):
    """Pin "today" for everything that reads it (plans, link writers, `Goal.save`)."""
    return mock.patch("django.utils.timezone.localdate", return_value=day)


class PlanFixture(TestCase):
    """Checking 5,000 and a pension account 20,000, both opened in August."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Plans Team", slug="plans-team")
        cls.book = cls.team.default_book
        asset = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        equity = AccountGroup.objects.create(book=cls.book, name="Opening", account_type="equity")
        expense = AccountGroup.objects.create(book=cls.book, name="Living", account_type="expense")
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=asset)
        cls.pension = Account.objects.create(book=cls.book, name="Pension Account", account_group=asset)
        cls.opening = Account.objects.create(book=cls.book, name="Opening Balance", account_group=equity)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=expense)
        cls.post(date(2026, 8, 2), cls.checking, cls.opening, "5000")
        cls.post(date(2026, 8, 2), cls.pension, cls.opening, "20000")

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="entry", status="posted")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=D(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=D(amount))
        return entry

    def goal(self, name="Pension", contribution="1000", target="0", plan_from=OCT, **extra):
        goal = Goal.objects.create(
            book=self.book,
            name=name,
            target_amount=D(target),
            monthly_contribution=D(contribution) if contribution else None,
            plan_from=plan_from,
            **extra,
        )
        return goal

    def link(self, goal, account=None, start=OCT, include=False, end=None):
        return GoalAccountLink.objects.create(
            book=self.book,
            goal=goal,
            account=account or self.pension,
            start_date=start,
            end_date=end,
            include_starting_balance=include,
        )

    def transfer(self, day, amount, into=None, out_of=None):
        return self.post(day, into or self.pension, out_of or self.checking, amount)

    def unassigned(self, month):
        return compute_unassigned(self.book, month)

    def numbers(self, goal, month):
        """`with_progress(month)` figures, plus `through`: everything given up to the end of `month`
        (`allocated` itself also counts manual allocations dated later)."""
        numbers = (
            Goal.objects.filter(pk=goal.pk)
            .with_progress(month)
            .values("allocated", "left", "saved_previous", "saved_this_month")
            .get()
        )
        numbers["through"] = numbers["saved_previous"] + numbers["saved_this_month"]
        return numbers

    def held(self, goal, month):
        goal = Goal.objects.get(pk=goal.pk)
        return plans.held_by_goal([goal], goal_monthly(self.book, [goal], end=plans.next_month(month)), month)[goal.pk]


class LinkedReleaseTest(PlanFixture):
    """docs/goal-plans-plan.md §2.5: a linked goal, unmet plans released at month end."""

    def setUp(self):
        self.baseline = self.unassigned(OCT).amount
        self.pension_goal = self.goal()
        self.link(self.pension_goal)

    def test_the_plan_holds_the_money_back(self):
        u = self.unassigned(OCT)
        self.assertEqual(u.goals_held, D("1000"))
        self.assertEqual(u.goals, D("0"))
        self.assertEqual(u.amount, self.baseline - D("1000"))

    def test_the_transfer_moves_nothing(self):
        self.transfer(date(2026, 10, 15), "1000")
        u = self.unassigned(OCT)
        self.assertEqual(u.goals_held, D("0"))
        self.assertEqual(u.goals, D("1000"))
        self.assertEqual(u.amount, self.baseline - D("1000"))

    def test_a_short_transfer_holds_the_rest(self):
        self.transfer(date(2026, 10, 15), "600")
        u = self.unassigned(OCT)
        self.assertEqual(u.goals_held, D("400"))
        self.assertEqual(u.goals, D("600"))
        self.assertEqual(u.amount, self.baseline - D("1000"))

    def test_the_shortfall_is_released_at_month_end(self):
        self.transfer(date(2026, 10, 15), "600")
        u = self.unassigned(NOV)
        # October's 400 lapsed; November plans its own 1,000.
        self.assertEqual(u.goals_held, D("1000"))
        self.assertEqual(u.goals, D("600"))
        self.assertEqual(u.amount, self.baseline - D("1600"))

    def test_an_over_transfer_takes_the_extra(self):
        self.transfer(date(2026, 10, 15), "1200")
        u = self.unassigned(OCT)
        self.assertEqual(u.goals_held, D("0"))
        self.assertEqual(u.goals, D("1200"))
        self.assertEqual(u.amount, self.baseline - D("1200"))

    def test_the_plan_never_changes_allocated(self):
        self.assertEqual(self.numbers(self.pension_goal, OCT)["allocated"], D("0"))

    def test_a_transfer_dated_next_month_counts_next_month(self):
        self.transfer(date(2026, 11, 2), "1000")
        self.assertEqual(self.held(self.pension_goal, OCT), D("1000"))
        self.assertEqual(self.held(self.pension_goal, NOV), D("0"))

    def test_a_starting_balance_is_not_put_in(self):
        GoalAccountLink.objects.filter(goal=self.pension_goal).update(include_starting_balance=True)
        self.assertEqual(self.numbers(self.pension_goal, OCT)["allocated"], D("20000"))
        self.assertEqual(self.held(self.pension_goal, OCT), D("1000"))

    def test_money_moved_out_raises_held_again(self):
        self.transfer(date(2026, 10, 10), "1000")
        self.post(date(2026, 10, 20), self.checking, self.pension, "300")
        self.assertEqual(self.held(self.pension_goal, OCT), D("300"))

    def test_a_manual_assign_counts_towards_the_plan(self):
        GoalAllocation.objects.create(book=self.book, goal=self.pension_goal, month=OCT, amount=D("250"))
        self.assertEqual(self.held(self.pension_goal, OCT), D("750"))

    def test_held_is_capped_at_what_the_target_still_needs(self):
        Goal.objects.filter(pk=self.pension_goal.pk).update(target_amount=D("1500"))
        self.transfer(date(2026, 9, 10), "1200")
        GoalAccountLink.objects.filter(goal=self.pension_goal).update(start_date=SEPT)
        # 1,200 arrived in September; October can only still need 300.
        self.assertEqual(self.held(self.pension_goal, OCT), D("300"))

    def test_a_closed_goal_holds_nothing(self):
        with today_is(date(2026, 10, 15)):
            GoalService(self.book).close(self.pension_goal, OCT)
        Goal.objects.filter(pk=self.pension_goal.pk).update(closed_at=timezone.make_aware(datetime(2026, 10, 15, 12)))
        self.assertEqual(self.held(self.pension_goal, OCT), D("0"))
        self.assertEqual(self.held(self.pension_goal, SEPT), D("0"))


class LinkedCarryTest(PlanFixture):
    def setUp(self):
        self.pension_goal = self.goal(unmet_plan=Goal.UNMET_CARRY)
        self.link(self.pension_goal)

    def test_the_shortfall_carries(self):
        self.transfer(date(2026, 10, 15), "600")
        self.assertEqual(self.held(self.pension_goal, OCT), D("400"))
        self.assertEqual(self.held(self.pension_goal, NOV), D("1400"))
        self.transfer(date(2026, 11, 3), "1400")
        self.assertEqual(self.held(self.pension_goal, NOV), D("0"))

    def test_a_late_transfer_fills_last_months_gap_first(self):
        self.transfer(date(2026, 11, 2), "1000")
        # October's 1,000 arrived on Nov 2: November still holds its own.
        self.assertEqual(self.held(self.pension_goal, NOV), D("1000"))

    def test_an_over_transfer_lowers_later_months(self):
        self.transfer(date(2026, 10, 15), "1500")
        self.assertEqual(self.held(self.pension_goal, NOV), D("500"))


class DirectGoalTest(PlanFixture):
    """A goal with no linked account is given its plan outright, capped at its target."""

    def setUp(self):
        self.baseline = self.unassigned(OCT).amount
        self.car = self.goal(name="Car", contribution="500", target="1200")

    def test_the_plan_is_the_allocation(self):
        self.assertEqual(self.numbers(self.car, OCT)["allocated"], D("500"))
        self.assertEqual(self.numbers(self.car, OCT)["saved_this_month"], D("500"))
        u = self.unassigned(OCT)
        self.assertEqual(u.goals_held, D("0"))
        self.assertEqual(u.amount, self.baseline - D("500"))

    def test_capped_at_the_target(self):
        expected = {OCT: D("500"), NOV: D("1000"), DEC: D("1200"), JAN: D("1200")}
        for month, allocated in expected.items():
            self.assertEqual(self.numbers(self.car, month)["allocated"], allocated, month)
        monthly = goal_monthly(self.book, [self.car], end=plans.next_month(JAN))[self.car.pk]
        self.assertEqual([monthly[m]["plan_in"] for m in (OCT, NOV, DEC, JAN)], [D("500"), D("500"), D("200"), D("0")])

    def test_months_before_plan_from_plan_nothing(self):
        self.assertEqual(self.numbers(self.car, SEPT)["allocated"], D("0"))

    def test_future_months_count_only_when_viewed(self):
        self.assertEqual(self.unassigned(OCT).goals, D("500"))
        self.assertEqual(self.unassigned(NOV).goals, D("1000"))

    def test_an_open_ended_goal_is_not_capped(self):
        rrsp = self.goal(name="RRSP", contribution="300")
        self.assertEqual(self.numbers(rrsp, DEC)["allocated"], D("900"))

    def test_assigns_add_on_top(self):
        GoalAllocation.objects.create(book=self.book, goal=self.car, month=OCT, amount=D("100"))
        self.assertEqual(self.numbers(self.car, OCT)["allocated"], D("600"))

    def test_a_typed_plan_replaces_the_default(self):
        plans.set_plan(self.car, OCT, D("300"))
        self.assertEqual(self.numbers(self.car, OCT)["allocated"], D("300"))
        self.assertEqual(self.numbers(self.car, NOV)["allocated"], D("800"))

    def test_reset_goes_back_to_the_default(self):
        plans.set_plan(self.car, OCT, D("300"))
        plans.reset_plan(self.car, OCT)
        self.assertEqual(self.numbers(self.car, OCT)["allocated"], D("500"))

    def test_reset_is_refused_before_plan_from(self):
        GoalPlan.objects.create(book=self.book, goal=self.car, month=SEPT, amount=D("100"))
        with self.assertRaises(plans.PlanError):
            plans.reset_plan(self.car, SEPT)

    def test_a_negative_plan_is_refused(self):
        with self.assertRaises(plans.PlanError):
            plans.set_plan(self.car, OCT, D("-1"))


class FreezeTest(PlanFixture):
    """`freeze` records the past so a later change can't rewrite it, and never moves a figure."""

    def figures(self, goals, months):
        return {
            (goal.pk, month): (
                self.numbers(goal, month)["allocated"],
                self.numbers(goal, month)["saved_this_month"],
                self.held(goal, month),
            )
            for goal in goals
            for month in months
        } | {("unassigned", month): self.unassigned(month).amount for month in months}

    def test_freeze_changes_no_figure(self):
        car = self.goal(name="Car", contribution="500", target="1200", plan_from=AUG)
        pension = self.goal(plan_from=AUG)
        self.link(pension, start=SEPT)
        self.transfer(date(2026, 9, 10), "700")
        GoalAllocation.objects.create(book=self.book, goal=car, month=SEPT, amount=D("100"))
        GoalPlan.objects.create(book=self.book, goal=car, month=NOV, amount=D("50"))
        months = [AUG, SEPT, OCT, NOV, DEC]
        before = self.figures([car, pension], months)
        with today_is(date(2026, 11, 20)):
            plans.freeze(car)
            plans.freeze(pension)
        self.assertEqual(Goal.objects.get(pk=car.pk).plan_from, NOV)
        self.assertEqual(self.figures([car, pension], months), before)

    def test_freeze_through_the_current_month(self):
        car = self.goal(name="Car", contribution="500")
        with today_is(date(2026, 10, 15)):
            plans.freeze(car, through_current=True)
        self.assertEqual(Goal.objects.get(pk=car.pk).plan_from, NOV)
        self.assertEqual(GoalPlan.objects.get(goal=car, month=OCT).source, GoalPlan.SOURCE_DEFAULT)

    def test_a_contribution_change_keeps_the_past(self):
        car = self.goal(name="Car", contribution="500", plan_from=AUG)
        with today_is(date(2026, 10, 15)):
            plans.freeze(car)
            Goal.objects.filter(pk=car.pk).update(monthly_contribution=D("200"))
        self.assertEqual(self.numbers(car, SEPT)["allocated"], D("1000"))
        self.assertEqual(self.numbers(car, OCT)["saved_this_month"], D("200"))

    def test_raising_the_target_doesnt_release_capped_months(self):
        car = self.goal(name="Car", contribution="500", target="1000", plan_from=AUG)
        self.assertEqual(self.numbers(car, OCT)["allocated"], D("1000"))
        with today_is(date(2026, 11, 15)):
            plans.freeze(car)
            Goal.objects.filter(pk=car.pk).update(target_amount=D("3000"))
        # August and September funded it; October counted nothing and still doesn't.
        self.assertEqual(self.numbers(car, OCT)["allocated"], D("1000"))
        self.assertEqual(self.numbers(car, NOV)["allocated"], D("1500"))

    def test_mark_funded_keeps_this_month_and_stops_after(self):
        car = self.goal(name="Car", contribution="500", target="5000")
        with today_is(date(2026, 10, 15)):
            GoalService(self.book).mark_funded(car)
        self.assertEqual(self.numbers(car, OCT)["allocated"], D("500"))
        self.assertEqual(self.numbers(car, DEC)["allocated"], D("500"))

    def test_linking_mid_month_turns_the_month_into_a_hold(self):
        car = self.goal(name="Car", contribution="500")
        before = self.unassigned(OCT).amount
        self.assertEqual(self.numbers(car, OCT)["allocated"], D("500"))
        with today_is(date(2026, 10, 15)):
            row = goal_links.LinkRow(
                account=self.pension, start_date=date(2026, 10, 15), include_starting_balance=False
            )
            goal_links.set_links(car, [row])
        self.assertEqual(self.numbers(car, OCT)["allocated"], D("0"))
        self.assertEqual(self.held(car, OCT), D("500"))
        self.assertEqual(self.unassigned(OCT).amount, before)

    def test_unlinking_mid_month_keeps_the_month_linked(self):
        pension = self.goal(plan_from=SEPT)
        link = self.link(pension, start=SEPT)
        GoalAccountLink.objects.filter(pk=link.pk).update(created_at=timezone.make_aware(datetime(2026, 9, 1, 12)))
        link.refresh_from_db()
        with today_is(date(2026, 10, 15)):
            goal_links.unlink(link)
        self.assertEqual(self.held(pension, OCT), D("1000"))
        self.assertEqual(self.numbers(pension, OCT)["allocated"], D("0"))
        # From November the goal is direct: its plan is given.
        self.assertEqual(self.numbers(pension, NOV)["saved_this_month"], D("1000"))


class AdoptTest(PlanFixture):
    def test_existing_goals_plan_from_the_given_month(self):
        car = self.goal(name="Car", contribution="500", plan_from=None)
        Goal.objects.filter(pk=car.pk).update(plan_from=None)
        GoalAllocation.objects.create(book=self.book, goal=car, month=OCT, amount=D("500"))
        plans.adopt_goals(
            Goal.objects.filter(pk=car.pk),
            OCT,
            Goal=Goal,
            GoalPlan=GoalPlan,
            GoalAllocation=GoalAllocation,
            GoalAccountLink=GoalAccountLink,
        )
        car.refresh_from_db()
        self.assertEqual(car.plan_from, OCT)
        # Assigned by hand already: the default doesn't add it again this month.
        self.assertEqual(GoalPlan.objects.get(goal=car, month=OCT).amount, D("0"))
        self.assertEqual(self.numbers(car, OCT)["allocated"], D("500"))
        self.assertEqual(self.numbers(car, NOV)["allocated"], D("1000"))
        self.assertEqual(self.numbers(car, SEPT)["through"], D("0"))


class PlanTwinTest(PlanFixture):
    """The SQL (`with_progress`) and Python (`goal_monthly`) readings of plans agree."""

    def test_sql_and_python_agree(self):
        car = self.goal(name="Car", contribution="500", target="2200", plan_from=AUG)
        rrsp = self.goal(name="RRSP", contribution="300", plan_from=SEPT)
        pension = self.goal(plan_from=AUG)
        GoalPlan.objects.create(book=self.book, goal=pension, month=AUG, amount=D("250"))
        # Linked the way the app links: freezing first (`goal_links.set_links`).
        with today_is(SEPT):
            plans.freeze(pension)
        self.link(pension, start=SEPT)
        with today_is(NOV):
            plans.freeze(rrsp)
        self.link(rrsp, account=self.checking, start=NOV)
        GoalAllocation.objects.create(book=self.book, goal=car, month=SEPT, amount=D("400"))
        GoalAllocation.objects.create(book=self.book, goal=car, month=NOV, amount=D("-150"))
        GoalPlan.objects.create(book=self.book, goal=car, month=OCT, amount=D("900"))
        self.transfer(date(2026, 9, 12), "800")
        goals = [car, rrsp, pension]
        months = [AUG, SEPT, OCT, NOV, DEC, JAN]
        monthly = goal_monthly(self.book, goals, end=plans.next_month(JAN))
        for goal in goals:
            running = D("0")
            for month in months:
                cell = monthly[goal.pk].get(month)
                saved = cell["saved"] if cell else D("0")
                running += saved
                sql = self.numbers(goal, month)
                self.assertEqual(sql["saved_this_month"], saved, (goal.name, month))
                self.assertEqual(sql["through"], running, (goal.name, month))


class PlanInputsWriteTest(TestCase):
    """
    Anything that changes what a goal's default plans goes through a writer that
    freezes first (`plans.freeze`), or a month with no row would silently plan the
    new settings in the past.
    """

    FIELDS = {"monthly_contribution", "is_complete", "closed_at", "target_amount", "plan_from"}
    ALLOWED = {
        "apps/budget/models.py",  # Goal.save: plan_from for a new goal
        "apps/budget/plans.py",  # the writers
        "apps/budget/services.py",  # close / mark_funded / archive, which freeze first
    }

    def test_no_writes_outside_the_writers(self):
        root = Path(__file__).resolve().parents[2]
        offenders = []
        for path in (root / "apps").rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if "test" in path.name or "/tests/" in rel or "/migrations/" in rel or rel in self.ALLOWED:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Attribute) and target.attr in self.FIELDS:
                            offenders.append(f"{rel}:{node.lineno}")
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "update"
                    and any(kw.arg in self.FIELDS for kw in node.keywords)
                ):
                    offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [])


class ViewFixture(PlanFixture):
    """Signed in, with a direct goal (Car, $500/month) and a linked one (Pension, $1,000/month)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.onboarding.models import OnboardingState
        from apps.teams.roles import ROLE_ADMIN
        from apps.users.models import CustomUser

        cls.user = CustomUser.objects.create_user(username="plans@example.com", password="pass12345")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        OnboardingState.objects.create(book=cls.book, completed_at="2026-01-01T00:00:00Z", phase="done")

    def setUp(self):
        self.client.login(username="plans@example.com", password="pass12345")
        self.car = self.goal(name="Car", contribution="500")
        self.pension_goal = self.goal(name="Pension")
        self.link(self.pension_goal)

    def url(self, name, *args):
        from django.urls import reverse

        return reverse(name, args=[*self.book.url_args, *args])

    def save(self, **body):
        import json

        return self.client.post(
            self.url("budget:budget_save_goal_plan"),
            json.dumps({"month": "2026-10-01", **body}),
            content_type="application/json",
        )


class BudgetPageGoalsTest(ViewFixture):
    """The budget page's Goals section and `budget_save_goal_plan` (docs/goal-plans-plan.md §6)."""

    def test_the_section_lists_open_goals_with_their_plans(self):
        response = self.client.get(self.url("budget:budget_home") + "?month=2026-10-01")
        self.assertEqual(response.status_code, 200)
        section = response.context["goal_section"]
        rows = {row["goal"].name: row for row in section["rows"]}
        self.assertEqual(rows["Car"]["planned"], D("500"))
        self.assertEqual(rows["Car"]["actual"], D("500"))
        self.assertFalse(rows["Car"]["linked"])
        self.assertEqual(rows["Pension"]["held"], D("1000"))
        self.assertEqual(rows["Pension"]["link_names"], ["Pension Account"])
        self.assertContains(response, 'data-testid="budget-goal-section"')
        self.assertContains(response, 'data-testid="goal-held"')

    def test_saving_a_plan_returns_the_page_figures(self):
        response = self.save(goal_id=self.car.pk, amount="300")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["amount"], "300.00")
        self.assertTrue(data["typed"])
        self.assertTrue(data["can_reset"])
        self.assertEqual(data["cells"][f"goal:{self.car.pk}:actual"]["value"], "$300.00")
        self.assertIn("networth:held", data["cells"])
        self.assertEqual(GoalPlan.objects.get(goal=self.car, month=OCT).amount, D("300"))

    def test_a_formula_is_saved_as_its_result(self):
        self.save(goal_id=self.car.pk, amount="100+50")
        self.assertEqual(GoalPlan.objects.get(goal=self.car, month=OCT).amount, D("150"))

    def test_reset(self):
        self.save(goal_id=self.car.pk, amount="300")
        response = self.save(goal_id=self.car.pk, reset=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["amount"], "500.00")
        self.assertFalse(GoalPlan.objects.filter(goal=self.car).exists())

    def test_refusals(self):
        self.assertEqual(self.save(goal_id=self.car.pk, amount="-5").status_code, 400)
        self.assertEqual(self.save(goal_id=self.car.pk, amount="abc").status_code, 400)
        GoalPlan.objects.create(book=self.book, goal=self.car, month=SEPT, amount=D("100"))
        self.assertEqual(self.save(goal_id=self.car.pk, month="2026-09-01", reset=True).status_code, 400)
        self.assertEqual(self.save(goal_id=999999, amount="5").status_code, 404)

    def test_another_books_goal_is_not_found(self):
        from apps.books.models import Book

        other = Book.objects.create(team=self.team, name="Other", slug="other")
        theirs = Goal.objects.create(book=other, name="Theirs", monthly_contribution=D("10"))
        self.assertEqual(self.save(goal_id=theirs.pk, amount="5").status_code, 404)
        self.assertFalse(GoalPlan.objects.filter(goal=theirs).exists())

    def test_a_closed_goal_is_refused(self):
        Goal.objects.filter(pk=self.car.pk).update(closed_at="2026-10-02T00:00:00Z")
        self.assertEqual(self.save(goal_id=self.car.pk, amount="5").status_code, 404)

    def test_a_form_post_redirects_back(self):
        response = self.client.post(
            self.url("budget:budget_save_goal_plan"),
            {"goal_id": self.car.pk, "month": "2026-10-01", "amount": "250"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("month=2026-10-01", response["Location"])
        self.assertEqual(GoalPlan.objects.get(goal=self.car, month=OCT).amount, D("250"))

    def test_the_net_worth_card_shows_held(self):
        response = self.client.get(self.url("budget:budget_home") + "?month=2026-10-01")
        self.assertEqual(response.context["net_worth_card"]["held"], D("1000"))
        self.assertContains(response, 'data-testid="net-worth-card-held"')


class GoalPagesTest(ViewFixture):
    """The goal form, the goals page's quick-assign and the goal's activity (docs/goal-plans-plan.md §7)."""

    def edit(self, goal, **data):
        return self.client.post(
            self.url("budget:goal_update", goal.pk),
            {
                "name": goal.name,
                "target_amount": str(goal.target_amount),
                "monthly_contribution": str(goal.monthly_contribution or ""),
                "outflow": goal.outflow,
                **data,
            },
        )

    def test_changing_the_contribution_keeps_past_months(self):
        Goal.objects.filter(pk=self.car.pk).update(plan_from=AUG)
        with today_is(date(2026, 10, 15)):
            response = self.edit(self.car, monthly_contribution="200")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.numbers(self.car, SEPT)["through"], D("1000"))
        self.assertEqual(self.numbers(self.car, OCT)["saved_this_month"], D("200"))
        self.assertEqual(Goal.objects.get(pk=self.car.pk).plan_from, OCT)

    def test_the_unmet_plan_setting_saves(self):
        with today_is(date(2026, 10, 15)):
            self.edit(
                self.pension_goal,
                unmet_plan="carry",
                link_account=[str(self.pension.pk)],
                **{f"link_start_{self.pension.pk}": "2026-10-01"},
            )
        self.assertEqual(Goal.objects.get(pk=self.pension_goal.pk).unmet_plan, Goal.UNMET_CARRY)

    def test_quick_assign_on_a_linked_goal_raises_the_plan(self):
        import json

        response = self.client.post(
            self.url("budget:goal_assign_available", self.pension_goal.pk),
            json.dumps({"month": "2026-10-01", "amount": "250"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data["planned"])
        self.assertEqual(data["plan"], 1250.0)
        self.assertEqual(data["held"], 1250.0)
        self.assertFalse(GoalAllocation.objects.filter(goal=self.pension_goal).exists())
        self.assertEqual(GoalPlan.objects.get(goal=self.pension_goal, month=OCT).amount, D("1250"))
        # The transfer completes it: nothing is given twice.
        self.transfer(date(2026, 10, 20), "1250")
        self.assertEqual(self.numbers(self.pension_goal, OCT)["through"], D("1250"))
        self.assertEqual(self.held(self.pension_goal, OCT), D("0"))

    def test_quick_assign_on_a_direct_goal_still_assigns(self):
        import json

        response = self.client.post(
            self.url("budget:goal_assign_available", self.car.pk),
            json.dumps({"month": "2026-10-01", "amount": "100"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("planned", response.json())
        self.assertEqual(GoalAllocation.objects.get(goal=self.car, month=OCT).amount, D("100"))

    def test_the_activity_lists_planned_contributions(self):
        response = self.client.get(self.url("budget:goal_detail", self.car.pk) + "?month=2026-10-01")
        kinds = [event["kind"] for event in response.context["activity"]]
        self.assertIn("planned", kinds)
        self.assertContains(response, 'data-testid="goal-month-plan"')

    def test_the_goals_page_shows_what_a_linked_goal_waits_for(self):
        response = self.client.get(self.url("budget:goals_list") + "?month=2026-10-01")
        items = {item["goal"].name: item for item in response.context["goal_items"]}
        self.assertEqual(items["Pension"]["held"], D("1000"))
        self.assertTrue(items["Pension"]["plan_linked"])
        self.assertContains(response, 'data-testid="goal-card-held"')


class ReportsTest(PlanFixture):
    """Held money in the Dollar Map, Budget vs Actual and the monthly review (docs/goal-plans-plan.md §7)."""

    def setUp(self):
        self.pension_goal = self.goal()
        self.link(self.pension_goal)

    def test_the_dollar_map_shows_held(self):
        from .unassigned import allocation_bar, waterfall

        u = compute_unassigned(self.book, OCT, detail=True)
        keys = [step["key"] for step in waterfall(u)]
        self.assertIn("goals_held", keys)
        self.assertEqual(waterfall(u)[-1]["value"], float(u.amount))
        segments = {seg["key"]: seg["amount"] for seg in allocation_bar(u)["segments"]}
        self.assertEqual(segments["goals_held"], D("1000"))
        self.assertEqual(u.detail["goals"][0]["held"], D("1000"))

    def test_budget_vs_actual_rows(self):
        rows, totals = GoalService(self.book).month_rows(OCT)
        self.assertEqual(rows[0]["needed"], D("1000"))
        self.assertEqual(rows[0]["held"], D("1000"))
        self.assertEqual(totals["held"], D("1000"))

    def test_the_monthly_review_names_an_unmet_plan(self):
        from apps.monthly_review.services.insights import _step7_saving
        from apps.monthly_review.services.review import _goal_plans_unmet

        self.transfer(date(2026, 10, 10), "600")
        with mock.patch("apps.monthly_review.services.review.date") as fake_date:
            fake_date.today.return_value = date(2026, 11, 5)
            fake_date.side_effect = date
            unmet = _goal_plans_unmet(self.book, OCT)
        self.assertEqual(unmet, [{"name": "Pension", "planned": D("1000"), "missing": D("400"), "carried": False}])
        review = {"current": {"saved": D("600"), "savings_rate": 0}, "baselines": {}, "goal_plans_unmet": unmet}
        insights = [i for i in _step7_saving(review) if i.kind == "goal_plan_unmet"]
        self.assertEqual(len(insights), 1)
        self.assertIn("went back to Unassigned", str(insights[0].title))
