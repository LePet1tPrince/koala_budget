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
        self.assertEqual(draft["summary"]["difference"], "60.00")
        self.assertEqual({line["id"] for line in draft["lines"]}, {pay.id, rent.id})

        resp = self.api("post", f"{API}{draft['id']}/tick/", {"line_ids": [pay.id, rent.id], "ticked": True})
        self.assertEqual(resp.status_code, 200, resp.content)
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

    def test_account_page_renders_with_props(self):
        resp = self.web.get(
            reverse("reconciliation:account", args=[self.team.slug, self.book.slug, self.card.id]) + "?lines=4,5"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="reconcile-props"')
        self.assertContains(resp, "preselect_line_ids")

    def test_income_account_page_is_a_404(self):
        resp = self.web.get(reverse("reconciliation:account", args=[self.team.slug, self.book.slug, self.salary.id]))
        self.assertEqual(resp.status_code, 404)

    def test_statement_page_and_undo_form(self):
        line = self.entry(self.chequing, self.salary, "10.00")
        rec = session.start(self.chequing, date(2026, 8, 31), Decimal("10.00"), self.user, [line.id])
        session.finish(rec, self.user)
        resp = self.web.get(reverse("reconciliation:statement", args=[self.team.slug, self.book.slug, rec.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Intact")
        resp = self.web.post(reverse("reconciliation:statement_undo", args=[self.team.slug, self.book.slug, rec.id]))
        self.assertEqual(resp.status_code, 302)
        rec.refresh_from_db()
        self.assertEqual(rec.status, Reconciliation.STATUS_UNDONE)

    def test_non_member_cannot_see_the_hub(self):
        outsider = CustomUser.objects.create_user(username="nosy", password="pass")
        web = Client()
        web.force_login(outsider)
        resp = web.get(reverse("reconciliation:hub", args=[self.team.slug, self.book.slug]))
        self.assertNotEqual(resp.status_code, 200)
