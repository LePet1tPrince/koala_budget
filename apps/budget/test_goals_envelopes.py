"""Goals as envelopes (docs/goals-envelopes-plan.md): maths, integrity, lifecycle, reports."""

import io
import random
from datetime import date
from decimal import Decimal

from django.apps import apps as django_apps
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import ACCOUNT_TYPE_EQUITY, Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.models import OnboardingState
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .models import (
    GOALS_GROUP_NAME,
    STATE_CLOSED,
    STATE_FUNDED,
    STATE_SAVING,
    STATE_SPENDING,
    Budget,
    Goal,
    GoalAllocation,
)
from .services import GoalCloseError, GoalService, goal_left_by_account, picker_accounts_data
from .unassigned import compute_unassigned, waterfall

AUG = date(2026, 8, 1)
SEPT = date(2026, 9, 1)
OCT = date(2026, 10, 1)
TODAY = date(2026, 9, 24)


class GoalsFixture(TestCase):
    """
    Checking holds 20,000 (from opening-balance equity). A "Car" goal has 5,000
    allocated (3,000 in August, 2,000 in September). Groceries is budgeted 400 in
    September. A system "Reconciliation Adjustments" equity account exists, as it
    does on every real chart.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Envelope Team", slug="envelope-team")
        cls.user = CustomUser.objects.create_user(username="envelope@example.com", password="pass12345")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        OnboardingState.objects.create(team=cls.team, completed_at="2026-01-01T00:00:00Z", phase="done")

        asset = AccountGroup.objects.create(team=cls.team, name="Cash", account_type="asset")
        cls.system_equity_group = AccountGroup.objects.create(
            team=cls.team, name="Equity Adjustments", account_type=ACCOUNT_TYPE_EQUITY, is_system=True
        )
        cls.opening_group = AccountGroup.objects.create(
            team=cls.team, name="Opening Balances", account_type=ACCOUNT_TYPE_EQUITY
        )
        expense = AccountGroup.objects.create(team=cls.team, name="Living", account_type="expense")
        income = AccountGroup.objects.create(team=cls.team, name="Work", account_type="income")
        cls.checking = Account.objects.create(team=cls.team, name="Checking", account_group=asset, has_feed=True)
        cls.system = Account.objects.create(
            team=cls.team, name="Reconciliation Adjustments", account_group=cls.system_equity_group, is_system=True
        )
        cls.opening = Account.objects.create(team=cls.team, name="Opening Balance", account_group=cls.opening_group)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=expense)
        cls.salary = Account.objects.create(team=cls.team, name="Salary", account_group=income)

        cls.post(date(2026, 8, 1), cls.checking, cls.opening, "20000")
        Budget.objects.create(team=cls.team, month=SEPT, category=cls.groceries, budget_amount=Decimal("400"))
        cls.car = Goal.objects.create(
            team=cls.team, name="Car", target_amount=Decimal("20000"), target_date=date(2027, 2, 15)
        )
        GoalAllocation.objects.create(team=cls.team, goal=cls.car, month=AUG, amount=Decimal("3000"))
        GoalAllocation.objects.create(team=cls.team, goal=cls.car, month=SEPT, amount=Decimal("2000"))

    def setUp(self):
        self.client.login(username="envelope@example.com", password="pass12345")

    @classmethod
    def post(cls, day, debit, credit, amount, status=JournalEntry.STATUS_POSTED):
        entry = JournalEntry.objects.create(team=cls.team, entry_date=day, description="entry", status=status)
        JournalLine.objects.create(team=cls.team, journal_entry=entry, account=debit, dr_amount=Decimal(amount))
        JournalLine.objects.create(team=cls.team, journal_entry=entry, account=credit, cr_amount=Decimal(amount))
        return entry

    def spend_from_car(self, day, amount):
        """A purchase paid from Checking, categorized to the Car goal."""
        return self.post(day, self.car.account, self.checking, amount)

    def numbers(self, month=SEPT, goal=None):
        return (
            Goal.objects.filter(pk=(goal or self.car).pk)
            .with_progress(month)
            .values("allocated", "spent", "left")
            .get()
        )

    def unassigned(self, month=SEPT):
        return compute_unassigned(self.team, month, today=TODAY).amount


# ---------------------------------------------------------------------------
# §3 / §4.2 maths
# ---------------------------------------------------------------------------


class GoalMathsTest(GoalsFixture):
    def test_allocated_spent_left(self):
        self.spend_from_car(date(2026, 9, 5), "1200")
        self.assertEqual(
            self.numbers(), {"allocated": Decimal("5000"), "spent": Decimal("1200"), "left": Decimal("3800")}
        )

    def test_a_refund_reduces_spent(self):
        self.spend_from_car(date(2026, 9, 5), "1200")
        self.post(date(2026, 9, 6), self.checking, self.car.account, "200")
        self.assertEqual(self.numbers()["spent"], Decimal("1000"))

    def test_a_withdrawal_is_a_negative_allocation(self):
        GoalAllocation.objects.create(team=self.team, goal=self.car, month=OCT, amount=Decimal("-500"))
        self.assertEqual(self.numbers(OCT)["allocated"], Decimal("4500"))

    def test_void_and_archived_feed_entries_do_not_count(self):
        self.spend_from_car(date(2026, 9, 5), "100")
        self.post(date(2026, 9, 5), self.car.account, self.checking, "300", status=JournalEntry.STATUS_VOID)
        archived = self.spend_from_car(date(2026, 9, 5), "700")
        BankTransaction.objects.create(
            team=self.team,
            account=self.checking,
            posted_date=date(2026, 9, 5),
            amount=Decimal("700"),
            description="archived",
            source=BankTransaction.SOURCE_CSV,
            journal_entry=archived,
            is_archived=True,
        )
        self.assertEqual(self.numbers()["spent"], Decimal("100"))

    def test_spending_after_month_end_is_excluded_from_that_month(self):
        self.spend_from_car(date(2026, 10, 2), "900")
        self.assertEqual(self.numbers(SEPT)["spent"], Decimal("0"))
        self.assertEqual(self.numbers(OCT)["spent"], Decimal("900"))

    def test_progress_uses_allocated_not_left(self):
        self.spend_from_car(date(2026, 9, 5), "4000")
        goal = Goal.objects.with_progress(SEPT).get(pk=self.car.pk)
        self.assertEqual(goal.progress_percentage, 25.0)
        self.assertEqual(goal.to_fund, Decimal("15000"))

    def test_overspent_goal_goes_negative(self):
        self.spend_from_car(date(2026, 9, 5), "6500")
        self.assertEqual(self.numbers()["left"], Decimal("-1500"))


class UnassignedInvariantTest(GoalsFixture):
    def test_spending_from_a_goal_leaves_unassigned_unchanged(self):
        before = self.unassigned()
        self.spend_from_car(date(2026, 9, 5), "1200")
        self.assertEqual(self.unassigned(), before)

    def test_invariant_over_random_amounts_and_months(self):
        rng = random.Random(20260924)
        for _ in range(15):
            month = rng.choice([AUG, SEPT, OCT])
            day = month.replace(day=rng.randint(1, 28))
            amount = Decimal(rng.randint(1, 900_000)) / 100
            before = {m: self.unassigned(m) for m in (AUG, SEPT, OCT)}
            if rng.random() < 0.3:
                self.post(day, self.checking, self.car.account, str(amount))  # a refund
            else:
                self.spend_from_car(day, str(amount))
            for m in (AUG, SEPT, OCT):
                self.assertEqual(self.unassigned(m), before[m], f"{amount} on {day}, viewed in {m}")

    def test_overspending_a_goal_leaves_unassigned_unchanged(self):
        before = self.unassigned()
        self.spend_from_car(date(2026, 9, 5), "7500")
        self.assertEqual(self.unassigned(), before)

    def test_goals_term_is_sum_of_left_and_the_waterfall_adds_spending_back(self):
        self.spend_from_car(date(2026, 9, 5), "1200")
        result = compute_unassigned(self.team, SEPT, today=TODAY, detail=True)
        self.assertEqual(result.goals_spent, Decimal("1200"))
        self.assertEqual(result.goals, Decimal("3800"))
        self.assertEqual(result.detail["goals"][0]["amount"], Decimal("3800"))
        self.assertEqual(result.detail["goals"][0]["spent"], Decimal("1200"))
        bars = {bar["key"]: bar for bar in waterfall(result)}
        self.assertEqual(bars["goals_spent"]["value"], 1200.0)
        self.assertEqual(bars["unassigned"]["end"], float(result.amount))

    def test_a_funded_goal_keeps_its_claim(self):
        before = self.unassigned()
        self.car.is_complete = True
        self.car.save()
        self.assertEqual(self.unassigned(), before)


class AssignWithdrawTest(GoalsFixture):
    def url(self, name):
        return reverse(f"budget:{name}", args=[self.team.slug, self.car.pk])

    def test_withdraw_caps_at_left(self):
        self.spend_from_car(date(2026, 9, 5), "4500")
        response = self.client.post(
            self.url("goal_withdraw"), {"month": "2026-09-01", "amount": "600"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("$500.00 left", response.json()["error"])

    def test_withdraw_all_takes_left_and_reports_it(self):
        self.spend_from_car(date(2026, 9, 5), "4500")
        response = self.client.post(self.url("goal_withdraw"), {"month": "2026-09-01"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["withdrawn"], 500.0)
        self.assertEqual(data["spent"], 4500.0)
        self.assertEqual(data["left"], 0.0)

    def test_assign_reports_spent_and_left(self):
        self.spend_from_car(date(2026, 9, 5), "1000")
        response = self.client.post(
            self.url("goal_assign_available"), {"month": "2026-09-01", "amount": "100"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["left"], 4100.0)

    def test_a_funded_goal_takes_an_explicit_amount_but_not_quick_assign(self):
        self.car.is_complete = True
        self.car.save()
        quick = self.client.post(
            self.url("goal_assign_available"), {"month": "2026-09-01"}, content_type="application/json"
        )
        self.assertEqual(quick.status_code, 400)
        explicit = self.client.post(
            self.url("goal_assign_available"), {"month": "2026-09-01", "amount": "50"}, content_type="application/json"
        )
        self.assertEqual(explicit.status_code, 200)

    def test_dashboard_to_reach_all_goals_is_target_minus_allocated(self):
        self.spend_from_car(date(2026, 9, 5), "1000")
        response = self.client.get(reverse("web_team:home", args=[self.team.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["amount_to_reach_goals"], Decimal("15000"))


# ---------------------------------------------------------------------------
# §4.1 integrity
# ---------------------------------------------------------------------------


class GoalsGroupTest(GoalsFixture):
    def test_new_goal_account_avoids_the_system_group(self):
        goal = Goal.objects.create(team=self.team, name="Trip", target_amount=Decimal("100"))
        self.assertFalse(goal.account.account_group.is_system)
        self.assertEqual(goal.account.account_group.name, GOALS_GROUP_NAME)
        self.assertEqual(goal.account.account_group.account_type, ACCOUNT_TYPE_EQUITY)

    def test_a_goals_group_of_another_type_does_not_capture_goal_accounts(self):
        team = Team.objects.create(name="Clash", slug="clash")
        AccountGroup.objects.create(team=team, name=GOALS_GROUP_NAME, account_type="expense")
        goal = Goal.objects.create(team=team, name="Trip", target_amount=Decimal("100"))
        self.assertEqual(goal.account.account_group.account_type, ACCOUNT_TYPE_EQUITY)
        self.assertFalse(goal.account.account_group.is_system)

    def test_migration_moves_goal_accounts_out_of_system_groups(self):
        stray = Goal.objects.create(team=self.team, name="Stray", target_amount=Decimal("1"))
        Account.objects.filter(pk=stray.account_id).update(account_group=self.system_equity_group)

        from importlib import import_module

        migration = import_module("apps.budget.migrations.0004_goal_closed_at_goals_group")
        migration.move_goal_accounts_out_of_system_groups(django_apps, None)

        stray.account.refresh_from_db()
        self.assertFalse(stray.account.account_group.is_system)
        self.assertEqual(stray.account.account_group.account_type, ACCOUNT_TYPE_EQUITY)

    def test_every_goal_has_an_account(self):
        self.assertFalse(Goal.objects.filter(account__isnull=True).exists())


class PickerAccountsTest(GoalsFixture):
    def test_system_accounts_are_left_out_and_goals_carry_left(self):
        self.spend_from_car(date(2026, 9, 5), "1000")
        data = {row["id"]: row for row in picker_accounts_data(self.team, SEPT)}
        self.assertNotIn(self.system.pk, data)
        self.assertTrue(data[self.car.account_id]["is_goal"])
        self.assertEqual(data[self.car.account_id]["goal_left"], "4000.00")
        # Plain equity is not a goal.
        self.assertFalse(data[self.opening.pk]["is_goal"])
        self.assertIsNone(data[self.opening.pk]["goal_left"])
        self.assertFalse(data[self.opening.pk]["is_system"])

    def test_goal_left_by_account_only_covers_goal_accounts(self):
        self.assertEqual(set(goal_left_by_account(self.team)), {self.car.account_id})


class SystemCategoryRefusedTest(GoalsFixture):
    """Every endpoint that takes a category refuses the system account."""

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)
        self.feed = f"/a/{self.team.slug}/bankfeed/api/feed/"
        self.tx = BankTransaction.objects.create(
            team=self.team,
            account=self.checking,
            posted_date=date(2026, 9, 5),
            amount=Decimal("25"),
            description="Coffee",
            source=BankTransaction.SOURCE_CSV,
        )

    def call(self, method, url, data):
        with current_team(self.team):
            return getattr(self.api, method)(url, data, format="json")

    def manual(self, **extra):
        return {"date": "2026-09-05", "account": self.checking.pk, "outflow": "25.00", "description": "x", **extra}

    def test_each_endpoint(self):
        cases = {
            "categorize": (
                "post",
                f"{self.feed}categorize/",
                {"rows": [{"id": self.tx.pk}], "category_id": self.system.pk},
            ),
            "create": ("post", self.feed, self.manual(category=self.system.pk)),
            "create splits": (
                "post",
                self.feed,
                self.manual(
                    splits=[
                        {"category": self.system.pk, "amount": "10"},
                        {"category": self.groceries.pk, "amount": "15"},
                    ]
                ),
            ),
            "update": ("put", f"{self.feed}{self.tx.pk}/", self.manual(category=self.system.pk)),
            "batch_edit": ("patch", f"{self.feed}batch_edit/", {"ids": [self.tx.pk], "category_id": self.system.pk}),
            "journal line": (
                "post",
                f"/a/{self.team.slug}/journal/api/lines/",
                {
                    "date": "2026-09-05",
                    "account": self.checking.pk,
                    "category": self.system.pk,
                    "outflow": "10.00",
                    "description": "x",
                },
            ),
        }
        for name, (method, url, data) in cases.items():
            with self.subTest(name):
                response = self.call(method, url, data)
                self.assertEqual(response.status_code, 400, (name, response.content))
                self.assertIn("bookkeeping account", response.content.decode())

    def test_recategorize_refuses_the_system_account(self):
        entry = self.post(date(2026, 9, 5), self.groceries, self.checking, "10")
        line = entry.lines.get(account=self.groceries)
        response = self.call(
            "post",
            f"/a/{self.team.slug}/journal/api/lines/{line.pk}/recategorize/",
            {"new_category_id": self.system.pk},
        )
        self.assertEqual(response.status_code, 400)

    def test_a_transaction_already_on_the_system_account_can_be_resaved(self):
        with current_team(self.team):
            self.api.post(
                f"{self.feed}categorize/",
                {"rows": [{"id": self.tx.pk}], "category_id": self.groceries.pk},
                format="json",
            )
        self.tx.refresh_from_db()
        line = self.tx.journal_entry.lines.get(account=self.groceries)
        line.account = self.system
        line.save()
        response = self.call("put", f"{self.feed}{self.tx.pk}/", self.manual(category=self.system.pk))
        self.assertEqual(response.status_code, 200, response.content)


# ---------------------------------------------------------------------------
# §4.3 states and §4.4 cover from goal
# ---------------------------------------------------------------------------


class GoalStatesTest(GoalsFixture):
    def state(self, goal=None):
        return Goal.objects.with_progress(SEPT).get(pk=(goal or self.car).pk).state

    def test_states(self):
        self.assertEqual(self.state(), STATE_SAVING)
        self.car.is_complete = True
        self.car.save()
        self.assertEqual(self.state(), STATE_FUNDED)
        self.spend_from_car(date(2026, 9, 5), "100")
        self.assertEqual(self.state(), STATE_SPENDING)
        GoalService(self.team).close(self.car, SEPT)
        self.assertEqual(self.state(), STATE_CLOSED)

    def test_close_releases_what_is_left(self):
        self.spend_from_car(date(2026, 9, 5), "1000")
        before = self.unassigned()
        result = GoalService(self.team).close(self.car, SEPT)
        self.assertEqual(result["released"], Decimal("4000"))
        self.assertEqual(self.numbers()["left"], Decimal("0"))
        self.assertEqual(self.unassigned(), before + Decimal("4000"))
        self.car.refresh_from_db()
        self.assertIsNotNone(self.car.closed_at)

    def test_close_refuses_a_negative_goal_unless_covered(self):
        self.spend_from_car(date(2026, 9, 5), "6000")
        with self.assertRaises(GoalCloseError):
            GoalService(self.team).close(self.car, SEPT)
        self.car.refresh_from_db()
        self.assertIsNone(self.car.closed_at)

        before = self.unassigned()
        result = GoalService(self.team).close(self.car, SEPT, cover=True)
        self.assertEqual(result["covered"], Decimal("1000"))
        self.assertEqual(self.numbers()["left"], Decimal("0"))
        self.assertEqual(self.unassigned(), before - Decimal("1000"))

    def test_close_view_is_audited_and_closed_goals_move_to_their_filter(self):
        response = self.client.post(
            reverse("budget:goal_close", args=[self.team.slug, self.car.pk]), {"month": "2026-09-01"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AuditEvent.objects.filter(team=self.team, event_type=AuditEvent.GOAL_CLOSED).exists())

        page = self.client.get(reverse("budget:goals_list", args=[self.team.slug]) + "?month=2026-09-01")
        self.assertNotContains(page, 'data-testid="goal-card"')
        closed = self.client.get(reverse("budget:goals_list", args=[self.team.slug]) + "?show=closed&month=2026-09-01")
        self.assertContains(closed, 'data-testid="closed-goal-row"')

    def test_close_opens_a_dialog_that_says_what_happens(self):
        url = reverse("budget:goals_list", args=[self.team.slug]) + "?month=2026-09-01&style=summit"
        page = self.client.get(url).content.decode()
        self.assertIn(f'id="goal-close-dialog-{self.car.pk}"', page)
        self.assertIn("goes back to your unassigned money", page)
        self.assertIn("$5,000.00", page)

        self.spend_from_car(date(2026, 9, 5), "6000")
        page = self.client.get(url).content.decode()
        # The negative case is the one shown, with the amount it takes to cover.
        self.assertRegex(page, r'data-close-case="neg"\s*>\s*Spending went past')
        self.assertIn('name="cover" value="1" data-close-cover >', page)
        self.assertIn("$1,000.00", page)

    def test_goal_detail_page_has_the_close_dialog(self):
        page = self.client.get(reverse("budget:goal_detail", args=[self.team.slug, self.car.pk]))
        self.assertContains(page, 'data-testid="goal-close-dialog"')

    def test_close_view_refuses_negative_without_cover(self):
        self.spend_from_car(date(2026, 9, 5), "6000")
        self.client.post(reverse("budget:goal_close", args=[self.team.slug, self.car.pk]), {"month": "2026-09-01"})
        self.car.refresh_from_db()
        self.assertIsNone(self.car.closed_at)

    def test_archiving_an_open_goal_closes_it_first(self):
        before = self.unassigned()
        self.client.post(reverse("budget:goal_delete", args=[self.team.slug, self.car.pk]) + "?month=2026-09-01")
        self.car.refresh_from_db()
        self.assertTrue(self.car.is_archived)
        self.assertIsNotNone(self.car.closed_at)
        # Released, then hidden: the money is back in Unassigned either way.
        self.assertEqual(self.unassigned(), before + Decimal("5000"))

    def test_archiving_a_negative_goal_is_refused(self):
        self.spend_from_car(date(2026, 9, 5), "6000")
        self.client.post(reverse("budget:goal_delete", args=[self.team.slug, self.car.pk]))
        self.car.refresh_from_db()
        self.assertFalse(self.car.is_archived)

    def test_goals_page_shows_allocated_spent_left_and_negative_carried(self):
        self.spend_from_car(date(2026, 9, 5), "6500")
        page = self.client.get(reverse("budget:goals_list", args=[self.team.slug]) + "?month=2026-09-01&style=summit")
        self.assertContains(page, 'data-testid="goal-negative"')
        self.assertContains(page, "-$1,500.00")
        self.assertContains(page, 'data-testid="goal-spending-link"')

    def test_goal_detail_lists_its_spending(self):
        self.spend_from_car(date(2026, 9, 5), "321")
        page = self.client.get(reverse("budget:goal_detail", args=[self.team.slug, self.car.pk]))
        self.assertContains(page, 'data-testid="goal-spending-row"', count=1)
        self.assertContains(page, "$321.00")


class CoverOverspendingTest(GoalsFixture):
    def cover(self, **overrides):
        body = {
            "category_id": self.groceries.pk,
            "source": "goal",
            "goal_id": self.car.pk,
            "month": "2026-09-01",
            "amount": "150",
            **overrides,
        }
        return self.client.post(
            reverse("budget:budget_cover", args=[self.team.slug]), body, content_type="application/json"
        )

    def groceries_budget(self):
        return Budget.objects.get(team=self.team, category=self.groceries, month=SEPT).budget_amount

    def test_from_a_goal_the_goal_gives_the_budget_gets_and_unassigned_is_unchanged(self):
        self.post(date(2026, 9, 5), self.groceries, self.checking, "550")  # 150 over budget
        before = self.unassigned()
        response = self.cover()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.groceries_budget(), Decimal("550"))
        self.assertEqual(self.numbers()["allocated"], Decimal("4850"))
        self.assertEqual(self.unassigned(), before)
        self.assertEqual(response.json()["cells"][f"row:{self.groceries.pk}:available"]["value"], "$0.00")
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.GOAL_COVERED_BUDGET).exists())

    def test_from_unassigned_the_budget_rises_and_unassigned_falls(self):
        self.post(date(2026, 9, 5), self.groceries, self.checking, "550")
        before = self.unassigned()
        response = self.cover(source="unassigned", goal_id=None)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["source"], "unassigned")
        self.assertIsNone(data["goal_left"])
        self.assertEqual(self.groceries_budget(), Decimal("550"))
        self.assertEqual(self.numbers()["allocated"], Decimal("5000"))  # the goal is untouched
        self.assertEqual(self.unassigned(), before - Decimal("150"))
        self.assertEqual(data["cells"][f"row:{self.groceries.pk}:available"]["value"], "$0.00")

    def test_from_unassigned_creates_the_budget_row_when_there_is_none(self):
        Budget.objects.filter(team=self.team, category=self.groceries).delete()
        response = self.cover(source="unassigned", amount="75")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.groceries_budget(), Decimal("75"))

    def test_a_goal_can_go_negative_covering(self):
        response = self.cover(amount="6000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["goal_left"], "-1000.00")

    def test_refusals(self):
        closed = Goal.objects.create(team=self.team, name="Done", target_amount=Decimal("1"))
        GoalService(self.team).close(closed, SEPT)
        for name, overrides in {
            "income category": {"category_id": self.salary.pk},
            "closed goal": {"goal_id": closed.pk},
            "goal source without a goal": {"goal_id": None},
            "unknown source": {"source": "savings"},
            "zero amount": {"amount": "0"},
            "bad amount": {"amount": "abc"},
        }.items():
            with self.subTest(name):
                self.assertEqual(self.cover(**overrides).status_code, 400)

    def test_budget_page_offers_cover_on_overspent_rows(self):
        self.post(date(2026, 9, 5), self.groceries, self.checking, "550")
        page = self.client.get(reverse("budget:budget_home", args=[self.team.slug]) + "?month=2026-09-01")
        self.assertContains(page, 'data-testid="cover-btn"')
        self.assertContains(page, 'data-testid="cover-source-unassigned"')
        self.assertContains(page, 'data-testid="cover-source-goal"')

    def test_cover_is_offered_without_any_goals(self):
        Goal.objects.filter(team=self.team).delete()
        self.post(date(2026, 9, 5), self.groceries, self.checking, "550")
        page = self.client.get(reverse("budget:budget_home", args=[self.team.slug]) + "?month=2026-09-01")
        self.assertContains(page, 'data-testid="cover-btn"')
        self.assertContains(page, 'data-testid="cover-source-unassigned"')
        self.assertNotContains(page, 'data-testid="cover-source-goal"')


# ---------------------------------------------------------------------------
# §4.5 reports
# ---------------------------------------------------------------------------


class GoalReportsTest(GoalsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.post(date(2026, 9, 3), cls.checking, cls.salary, "6000")
        cls.post(date(2026, 9, 4), cls.groceries, cls.checking, "4200")
        cls.post(date(2026, 9, 5), cls.car.account, cls.checking, "19400")

    def test_income_statement_reports_goal_spending_below_the_operating_net(self):
        from apps.reports.services import ReportService

        data = ReportService(self.team).get_income_statement_data(SEPT, date(2026, 9, 30), period="month")
        self.assertEqual(data["net_profit"], Decimal("1800"))
        self.assertEqual(data["goal_spending"]["total"], Decimal("19400"))
        self.assertEqual([i["account"] for i in data["goal_spending"]["items"]], [self.car.account])
        self.assertEqual(data["net_after_goal_spending"], Decimal("-17600"))
        self.assertEqual(data["net_after_goal_spending_per_period"], [Decimal("-17600")])
        # Goal spending is not an expense.
        self.assertNotIn(self.car.account, [i["account"] for i in data["expenses"]])

    def test_plain_equity_is_not_goal_spending_and_stays_on_the_balance_sheet(self):
        from apps.reports.services import ReportService

        service = ReportService(self.team)
        data = service.get_income_statement_data(date(2026, 8, 1), date(2026, 9, 30))
        self.assertNotIn(self.opening, [i["account"] for i in data["goal_spending"]["items"]])
        sheet = service.get_balance_sheet_data(date(2026, 9, 30))
        equity_accounts = [item["account"] for item in sheet["equity"]]
        self.assertIn(self.opening, equity_accounts)
        self.assertNotIn(self.car.account, equity_accounts)

    def test_income_statement_page_and_csv(self):
        qs = "?start_date=2026-09-01&end_date=2026-09-30"
        page = self.client.get(reverse("reports:income_statement", args=[self.team.slug]) + qs)
        self.assertContains(page, 'data-testid="goal-spending-table"')
        self.assertContains(page, 'data-testid="net-after-goal-spending"')
        self.assertEqual(page.context["sankey_data"]["goal_spending"], 19400.0)
        # Savings rate reads the operating net.
        self.assertEqual(round(page.context["savings_rate"]), 30)
        csv = self.client.get(reverse("reports:export_income_statement", args=[self.team.slug]) + qs)
        body = csv.content.decode()
        self.assertIn("GOAL SPENDING", body)
        self.assertIn("Net After Goal Spending,-17600.00", body)

    def test_spending_trends_toggle(self):
        base = (
            reverse("reports:income_statement", args=[self.team.slug])
            + "?start_date=2026-09-01&end_date=2026-09-30&view=monthly"
        )
        off = self.client.get(base)
        self.assertNotIn("Goal spending", [s["name"] for s in off.context["trend_chart_data"]["expense_groups"]])
        on = self.client.get(base + "&goals=1")
        self.assertIn("Goal spending", [s["name"] for s in on.context["trend_chart_data"]["expense_groups"]])
        self.assertIn("view=monthly", on.context["goals_toggle_qs"])

    def test_cash_flow_net_is_after_goal_spending(self):
        page = self.client.get(
            reverse("reports:cash_flow", args=[self.team.slug]) + "?start_month=2026-09&end_month=2026-09"
        )
        self.assertEqual(page.context["stats"]["net"], Decimal("-17600"))
        self.assertEqual(page.context["chart_data"]["goal_spending"], [19400.0])

    def test_budget_vs_actual_leads_with_goals(self):
        page = self.client.get(reverse("reports:budget_vs_actual", args=[self.team.slug]) + "?month=2026-09")
        row = page.context["goal_rows"][0]
        # Needed is measured from the start of the month: (20,000 − 3,000) over
        # Sept..Feb = 6 months, whatever was assigned in September.
        self.assertEqual(row["needed"], Decimal("2833.33"))
        self.assertEqual(row["assigned"], Decimal("2000"))
        self.assertEqual(row["spent"], Decimal("19400"))
        body = page.content.decode()
        self.assertLess(body.index('data-testid="bva-goals-table"'), body.index('data-testid="bva-expenses-table"'))

    def test_account_activity_reads_a_goal_like_an_expense(self):
        from apps.reports.services import ReportService

        service = ReportService(self.team)
        activity = service.get_account_activity(self.car.account, SEPT, date(2026, 9, 30))
        self.assertFalse(activity["is_balance_account"])
        self.assertEqual(activity["total"], Decimal("19400"))
        chart = service.get_budget_vs_actual_chart_data(self.car.account, SEPT, date(2026, 9, 30))
        self.assertEqual(chart["account_type"], "goal")
        self.assertEqual(chart["budgeted"], [2000.0])
        self.assertEqual(chart["actual"], [19400.0])
        self.assertEqual(chart["available"], [-14400.0])

    def test_goal_progress_report_has_spent_and_left(self):
        page = self.client.get(reverse("reports:goal_progress", args=[self.team.slug]))
        row = page.context["goal_rows"][0]
        self.assertEqual(
            (row["saved"], row["spent"], row["left"]), (Decimal("5000"), Decimal("19400"), Decimal("-14400"))
        )
        self.assertIsNotNone(page.context["chart_data"]["goals"][0]["spent"])

    def test_monthly_review_goal_spending_card(self):
        from apps.monthly_review.services.review import build_review

        review = build_review(self.team, SEPT)
        cards = [i for i in review["insights"] if i.kind == "goal_spending"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].severity, "info")
        self.assertIn("funded over 2 months", cards[0].title)
        self.assertNotIn("Goal: Car", [row["name"] for row in review["net_worth"]["by_account"]])

    def test_accounts_board_shows_left_and_splits_goals_from_equity(self):
        page = self.client.get(reverse("accounts:accounts_home", args=[self.team.slug]))
        types = {section["key"]: section for section in page.context["manage_props"]["types"]}
        goal_rows = [a for g in types["goal"]["groups"] for a in g["accounts"]]
        self.assertEqual([a["balance"] for a in goal_rows if a["isGoal"]], ["-14400.00"])
        equity_names = {g["name"] for g in types["equity"]["groups"]}
        self.assertIn("Opening Balances", equity_names)
        self.assertNotIn(GOALS_GROUP_NAME, equity_names)


class GoalActivityReportCommandTest(GoalsFixture):
    def test_lists_lines_on_goal_accounts(self):
        self.spend_from_car(date(2026, 9, 5), "123.45")
        out = io.StringIO()
        call_command("goal_activity_report", "--team", self.team.slug, "--csv", stdout=out)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(lines[0].split(",")[:4], ["team", "goal", "date", "amount"])
        self.assertIn("envelope-team,Car,2026-09-05,123.45", lines[1])
