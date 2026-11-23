"""API and pages: the happy path, statement-sign payloads, and who may do what."""

from datetime import date
from decimal import Decimal

from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import ACCOUNT_TYPE_ASSET, Account, AccountGroup
from apps.books.context import current_book
from apps.reconciliation.models import Reconciliation
from apps.reconciliation.services import session
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .base import ReconciliationTestCase

API = "reconcile/api/reconciliations/"


class ApiHappyPathTests(ReconciliationTestCase):
    def test_start_tick_finish_as_a_plain_member(self):
        pay = self.entry(self.chequing, self.salary, "100.00", on=date(2026, 8, 3))
        rent = self.entry(self.chequing, self.groceries, "-40.00", on=date(2026, 8, 4))

        resp = self.api(
            "post",
            API,
            {"account": self.chequing.id, "statement_date": "2026-08-31", "statement_balance": "60.00"},
            user=self.member,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        draft = resp.json()
        # Both are dated within the statement, so a new draft opens with them ticked.
        self.assertEqual(draft["auto_ticked"], 2)
        self.assertEqual(draft["summary"]["difference"], "0.00")
        self.assertEqual({line["id"] for line in draft["lines"]}, {pay.id, rent.id})

        resp = self.api("post", f"{API}{draft['id']}/tick/", {"line_ids": [rent.id], "ticked": False})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["summary"]["difference"], "-40.00")
        resp = self.api("post", f"{API}{draft['id']}/tick/", {"line_ids": [rent.id], "ticked": True})
        self.assertEqual(resp.json()["summary"]["difference"], "0.00")

        resp = self.api("post", f"{API}{draft['id']}/finish/", {})
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], "completed")
        self.assertTrue(body["intact"])

    def test_preselected_lines_arrive_ticked(self):
        pay = self.entry(self.chequing, self.salary, "100.00", on=date(2026, 8, 3))
        resp = self.api(
            "post",
            API,
            {
                "account": self.chequing.id,
                "statement_date": "2026-08-31",
                "statement_balance": "100.00",
                "line_ids": [pay.id],
            },
        )
        self.assertEqual(resp.json()["summary"]["difference"], "0.00")
        self.assertTrue(resp.json()["lines"][0]["ticked"])

    def test_new_draft_ticks_lines_through_the_statement_date(self):
        inside = self.entry(self.chequing, self.salary, "100.00", on=date(2026, 8, 31))
        older = self.entry(self.chequing, self.groceries, "-5.00", on=date(2026, 6, 2))
        later = self.entry(self.chequing, self.groceries, "-40.00", on=date(2026, 9, 2))
        resp = self.api(
            "post", API, {"account": self.chequing.id, "statement_date": "2026-08-31", "statement_balance": "95.00"}
        )
        body = resp.json()
        ticked = {line["id"]: line["ticked"] for line in body["lines"]}
        self.assertEqual(ticked, {inside.id: True, older.id: True, later.id: False})
        self.assertEqual(body["auto_ticked"], 2)
        self.assertEqual(body["summary"]["difference"], "0.00")

    def test_preselection_is_not_auto_ticked_around(self):
        chosen = self.entry(self.chequing, self.salary, "100.00", on=date(2026, 8, 3))
        other = self.entry(self.chequing, self.groceries, "-5.00", on=date(2026, 8, 4))
        body = self.api(
            "post",
            API,
            {
                "account": self.chequing.id,
                "statement_date": "2026-08-31",
                "statement_balance": "100.00",
                "line_ids": [chosen.id],
            },
        ).json()
        ticked = {line["id"]: line["ticked"] for line in body["lines"]}
        self.assertEqual(ticked, {chosen.id: True, other.id: False})
        self.assertEqual(body["auto_ticked"], 0)

    def test_line_that_left_a_finished_statement_is_not_auto_ticked(self):
        kept = self.entry(self.chequing, self.salary, "100.00", on=date(2026, 7, 10))
        pulled = self.entry(self.chequing, self.groceries, "-5.00", on=date(2026, 7, 11))
        july = session.start(self.chequing, date(2026, 7, 31), Decimal("95.00"), self.user, [kept.id, pulled.id])
        session.finish(july, self.user)
        pulled.refresh_from_db()
        pulled.is_reconciled = False  # unreconciled after the statement was finished
        pulled.save()
        fresh = self.entry(self.chequing, self.groceries, "-1.00", on=date(2026, 8, 3))

        body = self.api(
            "post", API, {"account": self.chequing.id, "statement_date": "2026-08-31", "statement_balance": "94.00"}
        ).json()
        ticked = {line["id"]: line["ticked"] for line in body["lines"]}
        self.assertEqual(ticked, {pulled.id: False, fresh.id: True})
        self.assertEqual(body["auto_ticked"], 1)

    def test_joining_an_open_draft_keeps_its_ticks(self):
        line = self.entry(self.chequing, self.salary, "100.00", on=date(2026, 8, 3))
        draft = session.start(self.chequing, date(2026, 8, 31), Decimal("100.00"), self.user)
        body = self.api(
            "post", API, {"account": self.chequing.id, "statement_date": "2026-08-31", "statement_balance": "1.00"}
        ).json()
        self.assertEqual(body["id"], draft.id)
        self.assertEqual(body["auto_ticked"], 0)
        self.assertFalse(body["lines"][0]["ticked"])
        self.assertEqual(line.id, body["lines"][0]["id"])

    def test_card_payload_is_in_statement_sign(self):
        charge = self.entry(self.card, self.groceries, "-284.56", on=date(2026, 8, 5))
        resp = self.api(
            "post", API, {"account": self.card.id, "statement_date": "2026-08-31", "statement_balance": "284.56"}
        )
        body = resp.json()
        self.assertEqual(body["statement_balance"], "284.56")
        self.assertEqual(body["lines"][0]["amount"], "284.56")
        self.assertEqual(body["lines"][0]["id"], charge.id)

    def test_difference_hint_and_stale_adjustment(self):
        a = self.entry(self.chequing, self.coffee, "-12.75", on=date(2026, 8, 30))
        b = self.entry(self.chequing, self.coffee, "-12.75", on=date(2026, 8, 30))
        draft = self.api(
            "post",
            API,
            {
                "account": self.chequing.id,
                "statement_date": "2026-08-31",
                "statement_balance": "-12.75",
                "line_ids": [a.id, b.id],
            },
        ).json()
        self.assertEqual(draft["summary"]["difference"], "12.75")
        self.assertIn("duplicate", [h["kind"] for h in draft["hints"]])

        self.assertEqual(self.api("post", f"{API}{draft['id']}/finish/", {}).status_code, 400)
        stale = self.api("post", f"{API}{draft['id']}/finish/", {"adjust": True, "expected_difference": "1.00"})
        self.assertEqual(stale.status_code, 409)

    def test_undo_via_api(self):
        line = self.entry(self.chequing, self.salary, "10.00")
        rec = session.start(self.chequing, date(2026, 8, 31), Decimal("10.00"), self.user, [line.id])
        session.finish(rec, self.user)
        resp = self.api("post", f"{API}{rec.id}/undo/", user=self.member)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "undone")

    def test_accounts_list(self):
        resp = self.api("get", f"{API}accounts/")
        names = {a["name"] for a in resp.json()["accounts"]}
        self.assertEqual(names, {"Chequing", "Savings", "Cash", "Visa"})
        self.assertFalse(resp.json()["all_intact"])

    def test_hub_says_all_intact_once_every_account_holds(self):
        for account in (self.chequing, self.savings, self.cash, self.card):
            rec = session.start(account, date(2026, 8, 31), Decimal("0"), self.user)
            session.finish(rec, self.user)
        resp = self.api("get", f"{API}accounts/")
        self.assertTrue(resp.json()["all_intact"])
        self.assertTrue(all(a["last_statement"]["intact"] for a in resp.json()["accounts"]))

    def test_page_is_what_the_account_page_opens_on(self):
        line = self.entry(self.chequing, self.salary, "10.00")
        draft = session.start(self.chequing, date(2026, 8, 31), Decimal("10.00"), self.user, [line.id])
        resp = self.api("get", f"{API}page/?account={self.chequing.id}", user=self.member)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["account"]["id"], self.chequing.id)
        self.assertEqual(data["draft_id"], draft.id)
        self.assertIsNone(data["previous"])
        self.assertEqual(data["history"], [])
        self.assertIn("default_statement_date", data)
        self.assertIn("reconciled_balance", data)
        # The feed's pickers ride along only for an account with a feed.
        self.assertEqual(bool(data["all_accounts"]), self.chequing.has_feed)

    def test_page_for_a_non_reconcilable_or_missing_account_is_a_404(self):
        self.assertEqual(self.api("get", f"{API}page/?account={self.salary.id}").status_code, 404)
        self.assertEqual(self.api("get", f"{API}page/?account=nope").status_code, 404)
        self.assertEqual(self.api("get", f"{API}page/").status_code, 404)

    def test_statement_detail_via_api(self):
        line = self.entry(self.chequing, self.salary, "10.00")
        rec = session.start(self.chequing, date(2026, 8, 31), Decimal("10.00"), self.user, [line.id])
        session.finish(rec, self.user)
        resp = self.api("get", f"{API}{rec.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "completed")
        self.assertTrue(resp.json()["intact"])
        self.assertEqual([row["id"] for row in resp.json()["lines"]], [line.id])

    def test_bad_start_is_a_400(self):
        resp = self.api(
            "post", API, {"account": self.chequing.id, "statement_date": "not-a-date", "statement_balance": "1"}
        )
        self.assertEqual(resp.status_code, 400)


class PermissionTests(ReconciliationTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_team = Team.objects.create(name="Other", slug="other-team")
        cls.other_book = cls.other_team.default_book
        cls.outsider = CustomUser.objects.create_user(username="outsider", password="pass")
        cls.other_team.members.add(cls.outsider, through_defaults={"role": ROLE_ADMIN})
        group = AccountGroup.objects.create(book=cls.other_book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cls.foreign_account = Account.objects.create(book=cls.other_book, name="Theirs", account_group=group)

    def _draft(self):
        return session.start(self.chequing, date(2026, 8, 31), Decimal("0"), self.user)

    def test_anonymous_is_refused(self):
        client = APIClient()
        with current_book(self.book):
            resp = client.get(self.url(f"{API}accounts/"))
        self.assertIn(resp.status_code, (401, 403))

    def test_outsider_cannot_use_this_teams_api(self):
        draft = self._draft()
        resp = self.api("post", f"{API}{draft.id}/tick/", {"line_ids": [], "ticked": True}, user=self.outsider)
        self.assertIn(resp.status_code, (403, 404))

    def test_another_teams_account_is_a_404(self):
        resp = self.api(
            "post",
            API,
            {"account": self.foreign_account.id, "statement_date": "2026-08-31", "statement_balance": "0"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_another_teams_line_cannot_be_ticked(self):
        draft = self._draft()
        foreign_group = self.foreign_account.account_group
        other = Account.objects.create(book=self.other_book, name="Cat", account_group=foreign_group)
        from apps.journal.models import JournalEntry, JournalLine

        je = JournalEntry.objects.create(book=self.other_book, entry_date=date(2026, 8, 1), description="x")
        line = JournalLine.objects.create(
            journal_entry=je, book=self.other_book, account=self.foreign_account, dr_amount=Decimal("1")
        )
        JournalLine.objects.create(journal_entry=je, book=self.other_book, account=other, cr_amount=Decimal("1"))
        resp = self.api("post", f"{API}{draft.id}/tick/", {"line_ids": [line.id], "ticked": True})
        self.assertEqual(resp.status_code, 400)
        line.refresh_from_db()
        self.assertIsNone(line.reconciliation_id)


class PageTests(ReconciliationTestCase):
    def setUp(self):
        super().setUp()
        self.web = Client()
        self.web.force_login(self.user)

    def test_hub_renders(self):
        resp = self.web.get(reverse("reconciliation:hub", args=[self.team.slug, self.book.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Chequing")

    def test_account_page_renders_its_mount(self):
        resp = self.web.get(
            reverse("reconciliation:account", args=[self.team.slug, self.book.slug, self.card.id]) + "?lines=4,5"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'data-account-id="{self.card.id}"')
        self.assertContains(resp, 'id="book-base"')
        self.assertNotContains(resp, "reconcile-props")

    def test_income_account_page_is_a_404(self):
        resp = self.web.get(reverse("reconciliation:account", args=[self.team.slug, self.book.slug, self.salary.id]))
        self.assertEqual(resp.status_code, 404)

    def test_statement_page_undoes_through_the_api(self):
        line = self.entry(self.chequing, self.salary, "10.00")
        rec = session.start(self.chequing, date(2026, 8, 31), Decimal("10.00"), self.user, [line.id])
        session.finish(rec, self.user)
        resp = self.web.get(reverse("reconciliation:statement", args=[self.team.slug, self.book.slug, rec.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Intact")
        self.assertContains(resp, f'data-statement-undo="{rec.id}"')
        resp = self.api("post", f"{API}{rec.id}/undo/")
        self.assertEqual(resp.status_code, 200)
        rec.refresh_from_db()
        self.assertEqual(rec.status, Reconciliation.STATUS_UNDONE)

    def test_non_member_cannot_see_the_hub(self):
        outsider = CustomUser.objects.create_user(username="nosy", password="pass")
        web = Client()
        web.force_login(outsider)
        resp = web.get(reverse("reconciliation:hub", args=[self.team.slug, self.book.slug]))
        self.assertNotEqual(resp.status_code, 200)
