"""
Goal names, open-ended goals (a monthly contribution with no target) and editing
or undoing a past manual contribution from the goal page.
"""

import json
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from . import goal_links
from .forms import GoalForm
from .models import Goal, GoalAccountLink, GoalAllocation
from .services import PLAN_BEHIND, PLAN_ON_TRACK, GoalAllocationError, GoalService, goal_plan
from .views import _goal_card_progress

AUG = date(2026, 8, 1)
SEPT = date(2026, 9, 1)
OCT = date(2026, 10, 1)
D = Decimal


class Fixture(TestCase):
    """Checking holds 10,000. "Car" has 1,000 assigned in August and 500 in September."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Contrib Team", slug="contrib-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="contrib@example.com", password="pass12345")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        OnboardingState.objects.create(book=cls.book, completed_at="2026-01-01T00:00:00Z", phase="done")

        assets = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        equity = AccountGroup.objects.create(book=cls.book, name="Opening Balances", account_type="goal")
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=assets)
        cls.savings = Account.objects.create(book=cls.book, name="RRSP", account_group=assets)
        cls.opening = Account.objects.create(book=cls.book, name="Opening Balance", account_group=equity)
        cls.post(date(2026, 8, 1), cls.checking, cls.opening, "10000")

        cls.car = Goal.objects.create(book=cls.book, name="Car", target_amount=D("5000"))
        cls.aug = GoalAllocation.objects.create(book=cls.book, goal=cls.car, month=AUG, amount=D("1000"))
        cls.sept = GoalAllocation.objects.create(book=cls.book, goal=cls.car, month=SEPT, amount=D("500"))

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="entry", status="posted")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=D(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=D(amount))
        return entry

    def setUp(self):
        self.client.login(username="contrib@example.com", password="pass12345")

    def allocated(self, goal=None):
        return (
            Goal.objects.filter(pk=(goal or self.car).pk).with_progress(OCT).values_list("allocated", flat=True).get()
        )


class GoalNameTest(Fixture):
    def form(self, name, instance=None, **extra):
        data = {"name": name, "target_amount": "100", **extra}
        return GoalForm(data, instance=instance, book=self.book)

    def test_a_name_taken_by_an_open_goal_is_a_form_error(self):
        form = self.form("Car")
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["name"], ["You already have a goal named “Car”. Pick another name."])

    def test_a_name_taken_by_an_archived_goal_says_so(self):
        Goal.objects.create(book=self.book, name="Retirement", target_amount=D("1"), is_archived=True)
        form = self.form("Retirement")
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["name"],
            ["You have an archived goal named “Retirement”. Pick another name, or delete that goal."],
        )
        self.assertEqual(form.name_clash.name, "Retirement")

    def test_surrounding_spaces_do_not_dodge_the_check(self):
        self.assertFalse(self.form("  Car ").is_valid())

    def test_a_goal_keeps_its_own_name_on_edit(self):
        self.assertTrue(self.form("Car", instance=self.car).is_valid())

    def test_the_same_name_in_another_book_is_fine(self):
        other = Team.objects.create(name="Other", slug="other-contrib").default_book
        self.assertTrue(GoalForm({"name": "Car", "target_amount": "1"}, book=other).is_valid())

    def test_creating_a_duplicate_re_renders_the_form_instead_of_500(self):
        Goal.objects.create(book=self.book, name="Retirement", target_amount=D("1"), is_archived=True)
        response = self.client.post(
            reverse("budget:goal_create", args=self.book.url_args),
            {"name": "Retirement", "target_amount": "100", "outflow": "withdraw"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "You have an archived goal named “Retirement”. Pick another name, or delete that goal."
        )
        self.assertContains(response, 'data-testid="goal-name-clash-link"')
        self.assertEqual(Goal.objects.filter(book=self.book, name="Retirement").count(), 1)


class OpenEndedGoalTest(Fixture):
    def test_needs_a_target_or_a_monthly_contribution(self):
        form = GoalForm({"name": "Nothing"}, book=self.book)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(), ["Set a target amount, a monthly contribution, or both."])

    def test_a_monthly_contribution_alone_is_enough(self):
        form = GoalForm({"name": "RESP", "monthly_contribution": "208.33"}, book=self.book)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["target_amount"], D("0"))

    def test_a_target_date_needs_a_target_amount(self):
        form = GoalForm({"name": "RESP", "monthly_contribution": "100", "target_date": "2030-01-01"}, book=self.book)
        self.assertFalse(form.is_valid())
        self.assertIn("target_date", form.errors)

    def test_the_edit_form_shows_no_target_as_blank(self):
        goal = Goal.objects.create(book=self.book, name="RESP", target_amount=D("0"), monthly_contribution=D("100"))
        self.assertNotIn('value="0', str(GoalForm(instance=goal, book=self.book)["target_amount"]))

    def test_create_through_the_view(self):
        response = self.client.post(
            reverse("budget:goal_create", args=self.book.url_args),
            {"name": "Retirement", "monthly_contribution": "500", "outflow": "withdraw"},
        )
        self.assertEqual(response.status_code, 302)
        goal = Goal.objects.get(book=self.book, name="Retirement")
        self.assertFalse(goal.has_target)
        self.assertEqual(goal.monthly_contribution, D("500"))

    def open_goal(self, this_month="0"):
        goal = Goal.objects.create(book=self.book, name="RESP", target_amount=D("0"), monthly_contribution=D("200"))
        GoalAllocation.objects.create(book=self.book, goal=goal, month=AUG, amount=D("200"))
        if D(this_month):
            GoalAllocation.objects.create(book=self.book, goal=goal, month=SEPT, amount=D(this_month))
        return Goal.objects.filter(pk=goal.pk).with_progress(SEPT).get()

    def test_plan_asks_for_the_contribution_every_month_with_no_finish(self):
        plan = goal_plan(self.open_goal(), SEPT)
        self.assertEqual(plan["rate"], D("200"))
        self.assertEqual(plan["needed"], D("200"))
        self.assertIsNone(plan["finish"])

    @mock.patch("apps.budget.services.timezone.localdate", return_value=date(2026, 9, 15))
    def test_on_track_once_this_month_is_in_and_never_behind_mid_month(self, _today):
        self.assertIsNone(goal_plan(self.open_goal(), SEPT)["status"])
        Goal.objects.filter(name="RESP").delete()
        self.assertEqual(goal_plan(self.open_goal("200"), SEPT)["status"], PLAN_ON_TRACK)

    @mock.patch("apps.budget.services.timezone.localdate", return_value=date(2026, 10, 15))
    def test_a_past_month_without_the_contribution_is_behind(self, _today):
        self.assertEqual(goal_plan(self.open_goal("50"), SEPT)["status"], PLAN_BEHIND)

    def test_card_progress_is_this_months_contribution(self):
        goal = self.open_goal("50")
        self.assertEqual(_goal_card_progress(goal, goal.allocated, D("50")), (25.0, D("150")))
        self.assertEqual(_goal_card_progress(goal, goal.allocated, D("300")), (100.0, D("0")))

    def test_quick_assign_tops_up_this_months_contribution(self):
        goal = self.open_goal("50")
        response = self.client.post(
            reverse("budget:goal_assign_available", args=[*self.book.url_args, goal.pk]),
            json.dumps({"month": "2026-09-01"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["assigned"], 150.0)
        self.assertTrue(data["open_ended"])
        self.assertEqual(data["new_pct"], 100.0)
        self.assertFalse(data["completed"])

    def test_quick_assign_past_the_plan_adds_what_is_available(self):
        goal = self.open_goal("200")
        response = self.client.post(
            reverse("budget:goal_assign_available", args=[*self.book.url_args, goal.pk]),
            json.dumps({"month": "2026-09-01"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertGreater(response.json()["assigned"], 0)

    def test_pages_render(self):
        goal = self.open_goal("50")
        for url in (
            reverse("budget:goal_detail", args=[*self.book.url_args, goal.pk]),
            reverse("budget:goal_update", args=[*self.book.url_args, goal.pk]),
            reverse("web_book:home", args=self.book.url_args),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        page = self.client.get(reverse("budget:goals_list", args=self.book.url_args) + "?month=2026-09-01")
        self.assertContains(page, 'data-testid="goal-open-ended"')
        self.assertContains(page, "data-open-ended")


class ContributionEditTest(Fixture):
    def url(self, allocation):
        return reverse("budget:goal_contribution_edit", args=[*self.book.url_args, allocation.pk])

    def test_undo_removes_the_months_contribution(self):
        response = self.client.post(self.url(self.aug), {"action": "undo"})
        self.assertRedirects(response, reverse("budget:goal_detail", args=[*self.book.url_args, self.car.pk]))
        self.assertFalse(GoalAllocation.objects.filter(pk=self.aug.pk).exists())
        self.assertEqual(self.allocated(), D("500"))
        event = AuditEvent.objects.get(event_type=AuditEvent.GOAL_CONTRIBUTION_EDITED)
        self.assertEqual(event.metadata["from"], "1000.00")
        self.assertTrue(event.metadata["undo"])

    def test_edit_changes_the_amount(self):
        self.client.post(self.url(self.aug), {"amount": "1,200+50"})
        self.aug.refresh_from_db()
        self.assertEqual(self.aug.amount, D("1250.00"))
        self.assertEqual(self.allocated(), D("1750"))

    def test_editing_to_zero_is_an_undo(self):
        self.client.post(self.url(self.sept), {"amount": "0"})
        self.assertFalse(GoalAllocation.objects.filter(pk=self.sept.pk).exists())

    def test_a_withdrawal_can_be_undone(self):
        withdrawal = GoalAllocation.objects.create(book=self.book, goal=self.car, month=OCT, amount=D("-300"))
        self.client.post(self.url(withdrawal), {"action": "undo"})
        self.assertEqual(self.allocated(), D("1500"))

    def test_junk_amount_changes_nothing(self):
        self.client.post(self.url(self.aug), {"amount": "lots"})
        self.aug.refresh_from_db()
        self.assertEqual(self.aug.amount, D("1000"))
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEvent.GOAL_CONTRIBUTION_EDITED).exists())

    def test_cannot_take_back_money_already_spent(self):
        # 1,200 of the 1,500 allocated has been spent: only 300 is left.
        self.post(date(2026, 9, 10), self.car.account, self.checking, "1200")
        with self.assertRaisesMessage(GoalAllocationError, "only $300.00 is left"):
            GoalService(self.book).edit_allocation(self.aug, D("0"))
        GoalService(self.book).edit_allocation(self.aug, D("700"))  # takes out exactly 300
        self.aug.refresh_from_db()
        self.assertEqual(self.aug.amount, D("700"))

    def test_refused_on_a_closed_goal(self):
        Goal.objects.filter(pk=self.car.pk).update(closed_at="2026-09-30T00:00:00Z")
        response = self.client.post(self.url(self.aug), {"action": "undo"}, follow=True)
        self.assertContains(response, "This goal is closed.")
        self.assertTrue(GoalAllocation.objects.filter(pk=self.aug.pk).exists())

    def test_the_goal_page_offers_edit_and_undo_only_on_manual_rows(self):
        GoalAccountLink.objects.create(book=self.book, goal=self.car, account=self.savings, start_date=SEPT)
        self.post(date(2026, 9, 5), self.savings, self.checking, "250")  # arrives via the link
        page = self.client.get(reverse("budget:goal_detail", args=[*self.book.url_args, self.car.pk]))
        self.assertContains(page, 'data-kind="in"')
        self.assertContains(page, 'data-testid="contribution-undo-btn"', count=2)  # Aug + Sept only

    def test_closed_goal_page_has_no_edit_buttons(self):
        Goal.objects.filter(pk=self.car.pk).update(closed_at="2026-09-30T00:00:00Z")
        page = self.client.get(reverse("budget:goal_detail", args=[*self.book.url_args, self.car.pk]))
        self.assertNotContains(page, 'data-testid="contribution-undo-btn"')

    def test_get_is_refused(self):
        self.assertEqual(self.client.get(self.url(self.aug)).status_code, 405)

    def test_anonymous_and_non_members_cannot_edit(self):
        self.client.logout()
        response = self.client.post(self.url(self.aug), {"action": "undo"})
        self.assertEqual(response.status_code, 302)
        CustomUser.objects.create_user(username="stranger@example.com", password="pass12345")
        self.client.login(username="stranger@example.com", password="pass12345")
        response = self.client.post(self.url(self.aug), {"action": "undo"})
        self.assertIn(response.status_code, (302, 403, 404))
        self.assertTrue(GoalAllocation.objects.filter(pk=self.aug.pk).exists())


class RelinkAfterCloseTest(Fixture):
    """Closing a goal ends its links today; the account must be linkable again."""

    TODAY = date(2026, 10, 8)

    def close_retirement(self):
        retirement = Goal.objects.create(book=self.book, name="Retirement", target_amount=D("1000"))
        GoalAccountLink.objects.create(book=self.book, goal=retirement, account=self.savings, start_date=AUG)
        goal_links.end_all(retirement, self.TODAY)  # what closing it today does to its links
        Goal.objects.filter(pk=retirement.pk).update(closed_at="2026-10-08T12:00:00Z")
        retirement.refresh_from_db()
        return retirement

    def test_same_day_relink_starts_tomorrow_by_default(self):
        self.close_retirement()
        new = Goal.objects.create(book=self.book, name="Retirement 2", target_amount=D("1000"))
        start = goal_links.default_start(self.savings, self.TODAY)
        self.assertEqual(start, date(2026, 10, 9))
        goal_links.set_links(new, [goal_links.LinkRow(self.savings, start)], today=self.TODAY)
        self.assertTrue(GoalAccountLink.objects.open().filter(goal=new, account=self.savings).exists())

    def test_overlap_names_the_goal_and_the_earliest_date(self):
        self.close_retirement()
        new = Goal.objects.create(book=self.book, name="Retirement 2", target_amount=D("1000"))
        with self.assertRaisesMessage(
            goal_links.LinkError,
            "counted towards Retirement through Oct 8, 2026, so here it can count from Oct 9, 2026",
        ):
            goal_links.set_links(new, [goal_links.LinkRow(self.savings, self.TODAY)], today=self.TODAY)

    def test_further_future_is_still_refused(self):
        self.close_retirement()
        new = Goal.objects.create(book=self.book, name="Retirement 2", target_amount=D("1000"))
        with self.assertRaisesMessage(goal_links.LinkError, "can't be in the future"):
            goal_links.set_links(new, [goal_links.LinkRow(self.savings, date(2026, 10, 10))], today=self.TODAY)

    def test_the_form_shows_the_previous_goal_and_defaults_past_it(self):
        self.close_retirement()
        with mock.patch("apps.budget.goal_links.timezone.localdate", return_value=self.TODAY):
            page = self.client.get(reverse("budget:goal_create", args=self.book.url_args))
        self.assertContains(page, 'data-testid="goal-link-previous"')
        self.assertContains(page, 'value="2026-10-09"')

    def test_deleting_the_closed_goal_frees_the_history(self):
        retirement = self.close_retirement()
        GoalService(self.book).delete(retirement)
        new = Goal.objects.create(book=self.book, name="Retirement", target_amount=D("1000"))
        goal_links.set_links(new, [goal_links.LinkRow(self.savings, AUG)], today=self.TODAY)


class GoalDeleteTest(Fixture):
    def url(self, goal=None):
        return reverse("budget:goal_destroy", args=[*self.book.url_args, (goal or self.car).pk])

    def test_delete_removes_the_goal_its_contributions_links_and_account(self):
        GoalAccountLink.objects.create(book=self.book, goal=self.car, account=self.savings, start_date=SEPT)
        account_pk = self.car.account_id
        response = self.client.post(self.url())
        self.assertRedirects(response, reverse("budget:goals_list", args=self.book.url_args))
        self.assertFalse(Goal.objects.filter(pk=self.car.pk).exists())
        self.assertFalse(GoalAllocation.objects.filter(goal_id=self.car.pk).exists())
        self.assertFalse(GoalAccountLink.objects.filter(goal_id=self.car.pk).exists())
        self.assertFalse(Account.objects.filter(pk=account_pk).exists())
        event = AuditEvent.objects.get(event_type=AuditEvent.GOAL_DELETED)
        self.assertEqual(event.metadata["goal_name"], "Car")
        self.assertEqual(event.metadata["linked_accounts"], ["RRSP"])

    def test_what_was_left_returns_to_unassigned(self):
        from .unassigned import compute_unassigned

        before = compute_unassigned(self.book, OCT).amount
        GoalService(self.book).delete(self.car)
        self.assertEqual(compute_unassigned(self.book, OCT).amount, before + D("1500"))

    def test_closed_and_archived_goals_can_be_deleted_and_free_their_name(self):
        GoalService(self.book).close(self.car, OCT)
        Goal.objects.filter(pk=self.car.pk).update(is_archived=True)
        self.client.post(self.url())
        self.assertTrue(GoalForm({"name": "Car", "target_amount": "1"}, book=self.book).is_valid())

    def test_refused_while_transactions_are_categorized_to_it(self):
        self.post(date(2026, 9, 10), self.car.account, self.checking, "200")
        response = self.client.post(self.url(), follow=True)
        self.assertContains(response, "1 transaction is categorized to Car")
        self.assertTrue(Goal.objects.filter(pk=self.car.pk).exists())
        page = self.client.get(reverse("budget:goal_detail", args=[*self.book.url_args, self.car.pk]))
        self.assertContains(page, 'data-testid="goal-delete-blocked"')

    def test_the_goal_page_offers_delete(self):
        page = self.client.get(reverse("budget:goal_detail", args=[*self.book.url_args, self.car.pk]))
        self.assertContains(page, 'data-testid="goal-delete-confirm"')

    def test_get_is_refused_and_strangers_cannot_delete(self):
        self.assertEqual(self.client.get(self.url()).status_code, 405)
        CustomUser.objects.create_user(username="stranger2@example.com", password="pass12345")
        self.client.login(username="stranger2@example.com", password="pass12345")
        self.client.post(self.url())
        self.assertTrue(Goal.objects.filter(pk=self.car.pk).exists())


class ArchivedGoalsAreReachableTest(Fixture):
    """An archived goal holds its name and its accounts' history, so it must be findable."""

    def test_closed_view_lists_archived_goals_even_without_closed_at(self):
        # Archived before archiving closed goals: no closed_at.
        Goal.objects.create(book=self.book, name="Retirement", target_amount=D("1"), is_archived=True)
        page = self.client.get(reverse("budget:goals_list", args=self.book.url_args) + "?show=closed&month=2026-10-01")
        self.assertContains(page, "Retirement")
        self.assertContains(page, 'data-testid="closed-goal-archived"')
        self.assertEqual(page.context["closed_count"], 1)
        open_page = self.client.get(reverse("budget:goals_list", args=self.book.url_args) + "?month=2026-10-01")
        self.assertNotContains(open_page, 'data-testid="closed-goal-archived"')

    def test_link_errors_link_to_the_goal_in_the_way(self):
        retirement = Goal.objects.create(book=self.book, name="Retirement", target_amount=D("1"), is_archived=True)
        GoalAccountLink.objects.create(
            book=self.book, goal=retirement, account=self.savings, start_date=AUG, end_date=date(2026, 9, 30)
        )
        response = self.client.post(
            reverse("budget:goal_create", args=self.book.url_args),
            {
                "name": "Retirement 2",
                "monthly_contribution": "100",
                "outflow": "withdraw",
                "link_account": str(self.savings.pk),
                f"link_start_{self.savings.pk}": "2026-08-01",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "counted towards Retirement through Sep 30, 2026")
        self.assertContains(response, reverse("budget:goal_detail", args=[*self.book.url_args, retirement.pk]))
        self.assertContains(response, 'data-testid="goal-link-error-goal"')


class GoalBackLinkTest(Fixture):
    def back_href(self, goal):
        page = self.client.get(reverse("budget:goal_detail", args=[*self.book.url_args, goal.pk]))
        self.assertContains(page, 'data-testid="goal-back-link"')
        self.assertContains(page, "Back to Goals")
        return page

    def test_open_goal_links_to_the_goals_list(self):
        goals_url = reverse("budget:goals_list", args=self.book.url_args)
        page = self.back_href(self.car)
        self.assertContains(page, f'href="{goals_url}"')

    def test_closed_goal_links_to_the_closed_filter(self):
        Goal.objects.filter(pk=self.car.pk).update(closed_at="2026-09-30T00:00:00Z")
        goals_url = reverse("budget:goals_list", args=self.book.url_args)
        page = self.back_href(self.car)
        self.assertContains(page, f'href="{goals_url}?show=closed"')
