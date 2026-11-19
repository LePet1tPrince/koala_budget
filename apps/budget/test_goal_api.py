"""
The goal API (`apps/budget/api/goals.py`): response shapes, the goal form's validation
shared with the serializer, every action's write rule, and permissions.

Assign and withdraw are covered in `tests.py` (GoalAssignAvailableTest,
GoalWithdrawTest) and `test_goals_envelopes.py`; the link rules in `test_goal_links.py`.
"""

import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.budget.forms import GoalForm
from apps.budget.ledger import goal_allocation, set_goal_allocation
from apps.budget.models import Goal, GoalAccountLink
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

D = Decimal


def this_month():
    return timezone.localdate().replace(day=1)


def api_month(month):
    return month.strftime("%Y-%m")


class GoalApiFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Goal API", slug="goal-api")
        cls.book = cls.team.default_book
        cls.member = CustomUser.objects.create_user(username="goal-api-member@example.com", password="pw")
        cls.admin = CustomUser.objects.create_user(username="goal-api-admin@example.com", password="pw")
        cls.outsider = CustomUser.objects.create_user(username="goal-api-outsider@example.com", password="pw")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        elsewhere = Team.objects.create(name="Goal API Elsewhere", slug="goal-api-elsewhere")
        elsewhere.members.add(cls.outsider, through_defaults={"role": ROLE_ADMIN})
        cls.other_book = elsewhere.default_book

        assets = AccountGroup.objects.create(book=cls.book, name="GA Assets", account_type="asset")
        equity = AccountGroup.objects.create(book=cls.book, name="GA Equity", account_type="equity")
        expenses = AccountGroup.objects.create(book=cls.book, name="GA Expenses", account_type="expense")
        cls.checking = Account.objects.create(book=cls.book, name="GA Checking", account_group=assets)
        cls.savings = Account.objects.create(book=cls.book, name="GA Savings", account_group=assets)
        cls.opening = Account.objects.create(book=cls.book, name="GA Opening", account_group=equity)
        cls.groceries = Account.objects.create(book=cls.book, name="GA Groceries", account_group=expenses)
        cls.month = this_month()
        cls.last_month = (cls.month - timedelta(days=1)).replace(day=1)
        cls.entry(cls.checking, cls.opening, "3000", cls.last_month)
        cls.entry(cls.savings, cls.opening, "500", cls.last_month)

        cls.trip = Goal.objects.create(book=cls.book, name="GA Trip", target_amount=D("1000"))
        set_goal_allocation(cls.book, cls.trip, cls.last_month, D("200"))
        set_goal_allocation(cls.book, cls.trip, cls.month, D("100"))
        cls.theirs = Goal.objects.create(book=cls.other_book, name="Their Goal", target_amount=D("50"))

    @classmethod
    def entry(cls, debit, credit, amount, day):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="GA")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=D(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=D(amount))

    def setUp(self):
        self.client.force_login(self.member)

    def url(self, name, **kwargs):
        return reverse(name, kwargs={"team_slug": self.team.slug, "book_slug": self.book.slug, **kwargs})

    def post(self, name, body=None, **kwargs):
        return self.client.post(self.url(name, **kwargs), json.dumps(body or {}), content_type="application/json")

    def send(self, method, name, body=None, **kwargs):
        if method == "get":
            return self.client.get(self.url(name, **kwargs), body or {})
        return getattr(self.client, method)(
            self.url(name, **kwargs), json.dumps(body or {}), content_type="application/json"
        )

    def contribution_line(self, goal, month):
        return JournalLine.objects.get(
            account__paired_account_id=goal.account_id,
            journal_entry__source=JournalEntry.SOURCE_BUDGET,
            journal_entry__entry_date=month,
        )


class GoalReadTest(GoalApiFixture):
    def test_list_has_the_cards_their_totals_and_unassigned(self):
        response = self.client.get(self.url("budget:api_goals"), {"month": api_month(self.month)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"month", "closed", "goals", "summary", "closed_count", "unassigned"})
        self.assertEqual(data["month"], api_month(self.month))
        self.assertFalse(data["closed"])
        [card] = data["goals"]
        self.assertEqual(card["id"], self.trip.pk)
        self.assertEqual(card["name"], "GA Trip")
        self.assertEqual(card["allocated"], "300.00")
        self.assertEqual(card["this_month"], "100.00")
        self.assertEqual(card["remaining"], "700.00")
        self.assertEqual(card["left"], "300.00")
        self.assertEqual(card["pct"], 30.0)
        self.assertEqual(card["state"], "saving")
        self.assertEqual(card["linked_accounts"], [])
        self.assertIsNone(card["plan"])
        self.assertEqual(data["summary"]["total_saved"], "300.00")
        self.assertEqual(data["summary"]["goal_count"], 1)
        self.assertEqual(data["closed_count"], 0)
        # 3,500 of net worth less the 300 the goal holds.
        self.assertEqual(data["unassigned"]["amount"], "3200.00")

    def test_list_defaults_to_this_month_and_lists_closed_goals_on_request(self):
        Goal.objects.create(book=self.book, name="GA Old", target_amount=D("10"), closed_at=timezone.now())
        data = self.client.get(self.url("budget:api_goals")).json()
        self.assertEqual(data["month"], api_month(self.month))
        self.assertEqual([g["name"] for g in data["goals"]], ["GA Trip"])
        self.assertEqual(data["closed_count"], 1)
        closed = self.client.get(self.url("budget:api_goals"), {"closed": "true"}).json()
        self.assertEqual([g["name"] for g in closed["goals"]], ["GA Old"])

    def test_a_malformed_month_is_a_400(self):
        response = self.client.get(self.url("budget:api_goals"), {"month": "June"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("month", response.json())

    def test_the_list_matches_the_goals_page(self):
        page = self.client.get(self.url("budget:goals_list"), {"month": self.month.isoformat()})
        item = page.context["goal_items"][0]
        card = self.client.get(self.url("budget:api_goals"), {"month": api_month(self.month)}).json()["goals"][0]
        self.assertEqual(D(card["allocated"]), item["saved"])
        self.assertEqual(D(card["remaining"]), item["remaining"])
        self.assertEqual(card["pct"], item["pct"])

    def test_detail_and_activity(self):
        GoalAccountLink.objects.create(book=self.book, goal=self.trip, account=self.savings, start_date=date.today())
        response = self.client.get(self.url("budget:api_goal", pk=self.trip.pk), {"month": api_month(self.month)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], self.trip.pk)
        self.assertEqual([link["account_name"] for link in data["open_links"]], ["GA Savings"])
        self.assertEqual(data["past_links"], [])
        self.assertTrue(data["can_edit_contributions"])
        self.assertIsNone(data["delete_blocked"])
        self.assertEqual(data["spending"], [])
        self.assertEqual(data["linked_accounts"], [{"id": self.savings.pk, "name": "GA Savings"}])

        activity = self.client.get(self.url("budget:api_goal_activity", pk=self.trip.pk)).json()
        self.assertEqual(activity["goal_id"], self.trip.pk)
        kinds = [(e["kind"], e["amount"]) for e in activity["events"]]
        self.assertIn(("assigned", "100.00"), kinds)
        self.assertIn(("assigned", "200.00"), kinds)
        manual = [e for e in activity["events"] if e["kind"] == "assigned"]
        self.assertTrue(all(e["line_id"] for e in manual))


class GoalWriteTest(GoalApiFixture):
    def test_create_with_a_linked_account(self):
        response = self.post(
            "budget:api_goals",
            {
                "name": "GA Emergency",
                "target_amount": "10000",
                "outflow": "spend",
                "links": [{"account_id": self.savings.pk, "include_starting_balance": True}],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        goal = Goal.objects.get(name="GA Emergency")
        self.assertEqual(data["id"], goal.pk)
        self.assertEqual(goal.outflow, Goal.OUTFLOW_SPEND)
        self.assertEqual(goal.book, self.book)
        self.assertEqual([link["account_id"] for link in data["open_links"]], [self.savings.pk])
        self.assertEqual(data["allocated"], "500.00")  # the balance already there
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.GOAL_ACCOUNT_LINKED).exists())

    def test_create_validates_as_the_form_does(self):
        cases = {
            "name": {"name": "GA Trip", "target_amount": "10"},
            "non_field_errors": {"name": "GA Nothing"},
            "target_date": {"name": "GA Dated", "monthly_contribution": "10", "target_date": "2030-01-01"},
            "target_amount": {"name": "GA Negative", "target_amount": "-1"},
        }
        for field, body in cases.items():
            with self.subTest(field=field):
                response = self.post("budget:api_goals", body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
                form = GoalForm(body, book=self.book)
                self.assertFalse(form.is_valid())
        self.assertIn("already have a goal", self.post("budget:api_goals", cases["name"]).json()["name"][0])
        self.assertFalse(Goal.objects.filter(name__in=["GA Nothing", "GA Dated", "GA Negative"]).exists())

    def test_an_open_ended_goal_needs_only_a_monthly_contribution(self):
        response = self.post("budget:api_goals", {"name": "GA Retire", "monthly_contribution": "200"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(response.json()["has_target"])
        self.assertEqual(Goal.objects.get(name="GA Retire").target_amount, D("0"))

    def test_a_refused_link_saves_nothing(self):
        other = Goal.objects.create(book=self.book, name="GA Holder", target_amount=D("10"))
        GoalAccountLink.objects.create(book=self.book, goal=other, account=self.savings, start_date=date.today())
        response = self.post(
            "budget:api_goals",
            {"name": "GA Blocked", "target_amount": "10", "links": [{"account_id": self.savings.pk}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already feeds", response.json()["links"][0])
        self.assertFalse(Goal.objects.filter(name="GA Blocked").exists())
        self.assertFalse(Account.objects.filter(name="Goal: GA Blocked").exists())

    def test_patch_changes_only_what_it_names_and_keeps_links(self):
        GoalAccountLink.objects.create(book=self.book, goal=self.trip, account=self.savings, start_date=date.today())
        response = self.send("patch", "budget:api_goal", {"description": "Lisbon"}, pk=self.trip.pk)
        self.assertEqual(response.status_code, 200, response.content)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.description, "Lisbon")
        self.assertEqual(self.trip.target_amount, D("1000"))
        self.assertTrue(GoalAccountLink.objects.open().filter(goal=self.trip).exists())

    def test_put_with_no_links_unlinks(self):
        link = GoalAccountLink.objects.create(
            book=self.book, goal=self.trip, account=self.savings, start_date=date.today()
        )
        response = self.send(
            "put", "budget:api_goal", {"name": "GA Trip", "target_amount": "1500", "links": []}, pk=self.trip.pk
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["target_amount"], "1500.00")
        self.assertFalse(GoalAccountLink.objects.filter(pk=link.pk, end_date__isnull=True).exists())

    def test_renaming_onto_another_goal_is_refused(self):
        Goal.objects.create(book=self.book, name="GA Car", target_amount=D("10"))
        response = self.send("patch", "budget:api_goal", {"name": "GA Car"}, pk=self.trip.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json())

    def test_destroy_and_its_guard(self):
        self.entry(self.trip.account, self.checking, "20", self.month)
        response = self.send("delete", "budget:api_goal", pk=self.trip.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("categorized", response.json()["non_field_errors"][0])
        free = Goal.objects.create(book=self.book, name="GA Free", target_amount=D("10"))
        response = self.send("delete", "budget:api_goal", pk=free.pk)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Goal.objects.filter(pk=free.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.GOAL_DELETED).exists())


class GoalActionTest(GoalApiFixture):
    def test_allocate_sets_the_month(self):
        response = self.post(
            "budget:api_goal_allocate", {"month": api_month(self.month), "amount": "250"}, pk=self.trip.pk
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["amount"], "250.00")
        self.assertEqual(data["goal"]["this_month"], "250.00")
        self.assertEqual(goal_allocation(self.book, self.trip, self.month), D("250"))
        refused = self.post(
            "budget:api_goal_allocate", {"month": api_month(self.month), "amount": "-5"}, pk=self.trip.pk
        )
        self.assertEqual(refused.status_code, 400)
        self.assertIn("amount", refused.json())

    def test_complete_marks_it_funded(self):
        response = self.post("budget:api_goal_complete", pk=self.trip.pk)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_complete"])
        self.assertTrue(response.json()["funded"])
        self.trip.refresh_from_db()
        self.assertTrue(self.trip.is_complete)

    def test_close_releases_what_is_left(self):
        response = self.post("budget:api_goal_close", {"month": api_month(self.month)}, pk=self.trip.pk)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["released"], "300.00")
        self.assertEqual(data["goal"]["state"], "closed")
        self.assertEqual(data["unassigned"]["amount"], "3500.00")
        again = self.post("budget:api_goal_close", {"month": api_month(self.month)}, pk=self.trip.pk)
        self.assertEqual(again.status_code, 400)

    def test_a_negative_goal_closes_only_with_cover(self):
        self.entry(self.trip.account, self.checking, "400", self.month)
        refused = self.post("budget:api_goal_close", {"month": api_month(self.month)}, pk=self.trip.pk)
        self.assertEqual(refused.status_code, 400)
        self.assertIsNone(Goal.objects.get(pk=self.trip.pk).closed_at)
        covered = self.post("budget:api_goal_close", {"month": api_month(self.month), "cover": True}, pk=self.trip.pk)
        self.assertEqual(covered.status_code, 200)
        self.assertEqual(covered.json()["covered"], "100.00")

    def test_archive_closes_then_archives(self):
        response = self.post("budget:api_goal_archive", {"month": api_month(self.month)}, pk=self.trip.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["released"], "300.00")
        self.trip.refresh_from_db()
        self.assertTrue(self.trip.is_archived)
        self.assertIsNotNone(self.trip.closed_at)
        # An archived goal can't be closed (it is a 404, as on the page).
        self.assertEqual(self.post("budget:api_goal_close", pk=self.trip.pk).status_code, 404)

    def test_unlink(self):
        link = GoalAccountLink.objects.create(
            book=self.book, goal=self.trip, account=self.savings, start_date=date.today() - timedelta(days=10)
        )
        GoalAccountLink.objects.filter(pk=link.pk).update(created_at=timezone.now() - timedelta(days=10))
        response = self.post("budget:api_goal_unlink", link_pk=link.pk)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["end_date"], timezone.localdate().isoformat())
        self.assertFalse(data["removed"])
        self.assertEqual(self.post("budget:api_goal_unlink", link_pk=link.pk).status_code, 400)

    def test_unlinking_a_link_made_today_removes_it(self):
        link = GoalAccountLink.objects.create(
            book=self.book, goal=self.trip, account=self.savings, start_date=date.today()
        )
        data = self.post("budget:api_goal_unlink", link_pk=link.pk).json()
        self.assertTrue(data["removed"])
        self.assertIsNone(data["end_date"])
        self.assertFalse(GoalAccountLink.objects.filter(pk=link.pk).exists())

    def test_contribution_edit_and_undo(self):
        line = self.contribution_line(self.trip, self.last_month)
        response = self.post("budget:api_goal_contribution", {"amount": "150"}, line_pk=line.pk)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data["old"], data["amount"]), ("200.00", "150.00"))
        self.assertEqual(goal_allocation(self.book, self.trip, self.last_month), D("150"))
        line = self.contribution_line(self.trip, self.last_month)
        undone = self.post("budget:api_goal_contribution", {"undo": True}, line_pk=line.pk)
        self.assertEqual(undone.status_code, 200)
        self.assertEqual(goal_allocation(self.book, self.trip, self.last_month), D("0"))
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEvent.GOAL_CONTRIBUTION_EDITED).count(), 2)

    def test_contribution_edit_refuses_taking_back_spent_money(self):
        self.entry(self.trip.account, self.checking, "250", self.month)
        line = self.contribution_line(self.trip, self.last_month)
        response = self.post("budget:api_goal_contribution", {"amount": "0"}, line_pk=line.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("spent", response.json()["non_field_errors"][0])
        missing = self.post("budget:api_goal_contribution", {}, line_pk=line.pk)
        self.assertEqual(missing.status_code, 400)
        self.assertIn("amount", missing.json())

    def test_link_preview_writes_nothing(self):
        response = self.post(
            "budget:api_goal_link_preview",
            {"goal_id": self.trip.pk, "links": [{"account_id": self.savings.pk, "include_starting_balance": True}]},
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["adds"], "500.00")
        self.assertEqual(D(data["unassigned_after"]), D(data["unassigned_before"]) - D("500"))
        self.assertFalse(GoalAccountLink.objects.exists())

    def test_link_preview_for_a_new_goal(self):
        response = self.post("budget:api_goal_link_preview", {"links": [{"account_id": self.savings.pk}]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["left_before"], "0.00")
        self.assertFalse(Goal.objects.filter(name="__preview__").exists())


class GoalPermissionsTest(GoalApiFixture):
    def requests(self):
        month = api_month(self.month)
        line = self.contribution_line(self.trip, self.month)
        link = GoalAccountLink.objects.create(
            book=self.book, goal=self.trip, account=self.savings, start_date=date.today()
        )
        return [
            ("get", "budget:api_goals", {}, None),
            ("get", "budget:api_goal", {"pk": self.trip.pk}, None),
            ("get", "budget:api_goal_activity", {"pk": self.trip.pk}, None),
            ("post", "budget:api_goals", {}, {"name": "GA Perm", "target_amount": "5"}),
            ("patch", "budget:api_goal", {"pk": self.trip.pk}, {"description": "perm"}),
            ("post", "budget:api_goal_allocate", {"pk": self.trip.pk}, {"month": month, "amount": "120"}),
            ("post", "budget:api_goal_assign", {"pk": self.trip.pk}, {"month": month, "amount": "1"}),
            ("post", "budget:api_goal_withdraw", {"pk": self.trip.pk}, {"month": month, "amount": "1"}),
            ("post", "budget:api_goal_complete", {"pk": self.trip.pk}, {}),
            ("post", "budget:api_goal_link_preview", {}, {"links": []}),
            ("post", "budget:api_goal_contribution", {"line_pk": line.pk}, {"amount": "110"}),
            ("post", "budget:api_goal_unlink", {"link_pk": link.pk}, None),
            ("post", "budget:api_goal_close", {"pk": self.trip.pk}, {"month": month}),
        ]

    def test_members_read_and_write(self):
        for method, name, kwargs, body in self.requests():
            with self.subTest(name=name, method=method):
                response = self.send(method, name, body, **kwargs)
                self.assertIn(response.status_code, (200, 201), response.content)

    def test_non_members_are_refused_and_change_nothing(self):
        requests = self.requests()
        self.client.force_login(self.outsider)
        for method, name, kwargs, body in requests:
            with self.subTest(name=name, method=method):
                self.assertIn(self.send(method, name, body, **kwargs).status_code, (403, 404))
        self.trip.refresh_from_db()
        self.assertIsNone(self.trip.closed_at)
        self.assertEqual(goal_allocation(self.book, self.trip, self.month), D("100"))
        self.assertFalse(Goal.objects.filter(name="GA Perm").exists())

    def test_anonymous_is_refused(self):
        requests = self.requests()
        self.client.logout()
        for method, name, kwargs, body in requests:
            with self.subTest(name=name, method=method):
                self.assertIn(self.send(method, name, body, **kwargs).status_code, (401, 403))

    def test_another_books_goal_is_a_404(self):
        for method, name in (
            ("get", "budget:api_goal"),
            ("get", "budget:api_goal_activity"),
            ("delete", "budget:api_goal"),
            ("post", "budget:api_goal_assign"),
            ("post", "budget:api_goal_close"),
        ):
            with self.subTest(name=name, method=method):
                response = self.send(method, name, {"month": api_month(self.month)}, pk=self.theirs.pk)
                self.assertEqual(response.status_code, 404)
        self.assertTrue(Goal.objects.filter(pk=self.theirs.pk, closed_at__isnull=True).exists())
