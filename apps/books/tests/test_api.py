"""The books API: the team's book list and actions, and one book's settings."""

import json
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.books.helpers import create_book
from apps.books.models import Book
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

from .factories import build_book_data, snapshot


def make_user(email, team=None, role=ROLE_ADMIN):
    user = CustomUser.objects.create_user(username=email, email=email, password="pass")
    if team is not None:
        team.members.add(user, through_defaults={"role": role})
    return user


class BooksAPITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Books API", slug="books-api")
        cls.admin = make_user("admin@books-api.test", cls.team, ROLE_ADMIN)
        cls.member = make_user("member@books-api.test", cls.team, ROLE_MEMBER)
        cls.outsider = make_user("outsider@books-api.test")
        cls.personal = cls.team.default_book
        cls.business = create_book(cls.team, "Business")

    def list_url(self, team=None):
        return reverse("books_team:book-list", args=[(team or self.team).slug])

    def detail_url(self, book, action=None):
        name = f"books_team:book-{action}" if action else "books_team:book-detail"
        return reverse(name, args=[book.team.slug, book.slug])

    def post(self, url, body=None):
        return self.client.post(url, data=json.dumps(body or {}), content_type="application/json")


class BookListTest(BooksAPITestCase):
    def test_a_member_lists_every_book_archived_ones_last(self):
        self.business.archive()
        self.client.force_login(self.member)
        response = self.client.get(self.list_url())
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual([row["slug"] for row in rows], ["personal", "business"])
        personal, business = rows
        self.assertEqual(personal["base_url"], f"/a/{self.team.slug}/personal/")
        self.assertTrue(personal["is_default"])
        # The only open book can be neither archived nor deleted; the archived one can be deleted.
        self.assertEqual((personal["can_archive"], personal["can_delete"]), (False, False))
        self.assertEqual(
            (business["is_archived"], business["can_archive"], business["can_delete"]), (True, False, True)
        )

    def test_retrieve_by_slug(self):
        self.client.force_login(self.member)
        response = self.client.get(self.detail_url(self.business))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Business")

    def test_another_teams_book_is_a_404(self):
        other = Team.objects.create(name="Other", slug="other-books-api")
        create_book(other, "Secret")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("books_team:book-detail", args=[self.team.slug, "secret"]))
        self.assertEqual(response.status_code, 404)

    def test_a_non_member_and_an_anonymous_user_are_refused(self):
        self.assertEqual(self.client.get(self.list_url()).status_code, 403)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.list_url()).status_code, 403)
        self.assertEqual(self.client.get(self.detail_url(self.personal)).status_code, 403)


class BookCreateAPITest(BooksAPITestCase):
    def test_an_admin_creates_a_book(self):
        self.client.force_login(self.admin)
        response = self.post(self.list_url(), {"name": "Rental", "start": "ynab"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["slug"], "rental")
        book = Book.objects.get(team=self.team, slug="rental")
        event = AuditEvent.objects.get(event_type=AuditEvent.BOOK_CREATED, book=book)
        self.assertEqual(event.metadata, {"name": "Rental", "start": "ynab"})

    def test_a_duplicate_name_is_refused_case_insensitively(self):
        self.client.force_login(self.admin)
        response = self.post(self.list_url(), {"name": "business"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json())
        response = self.post(self.list_url(), {"name": "New", "start": "sideways"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("start", response.json())

    def test_a_member_cannot_create_a_book(self):
        self.client.force_login(self.member)
        self.assertEqual(self.post(self.list_url(), {"name": "Mine"}).status_code, 403)
        self.client.force_login(self.outsider)
        self.assertEqual(self.post(self.list_url(), {"name": "Mine"}).status_code, 403)
        self.assertFalse(Book.objects.filter(name="Mine").exists())


class BookArchiveAPITest(BooksAPITestCase):
    def test_archive_needs_the_name_and_restore_brings_it_back(self):
        self.client.force_login(self.admin)
        response = self.post(self.detail_url(self.business, "archive"), {"confirm": "Busines"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirm", response.json())

        response = self.post(self.detail_url(self.business, "archive"), {"confirm": "Business"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_archived"])
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.BOOK_ARCHIVED, book=self.business).exists())

        # Archiving an archived book changes nothing.
        self.assertEqual(self.post(self.detail_url(self.business, "archive"), {"confirm": "x"}).status_code, 200)

        response = self.post(self.detail_url(self.business, "restore"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_archived"])
        self.business.refresh_from_db()
        self.assertFalse(self.business.is_archived)

    def test_the_last_open_book_cannot_be_archived(self):
        self.business.archive()
        self.client.force_login(self.admin)
        response = self.post(self.detail_url(self.personal, "archive"), {"confirm": "Personal"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("non_field_errors", response.json())
        self.personal.refresh_from_db()
        self.assertFalse(self.personal.is_archived)

    def test_a_member_cannot_archive_or_restore(self):
        self.client.force_login(self.member)
        self.assertEqual(self.post(self.detail_url(self.business, "archive"), {"confirm": "Business"}).status_code, 403)
        self.assertEqual(self.post(self.detail_url(self.business, "restore")).status_code, 403)
        self.business.refresh_from_db()
        self.assertFalse(self.business.is_archived)


class BookDeleteAPITest(BooksAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.data = build_book_data(cls.business, "QQBIZQQ", cls.admin)
        cls.personal_data = build_book_data(cls.personal, "QQHOMEQQ", cls.admin)

    def test_delete_wipes_only_that_book(self):
        before = snapshot(self.personal)
        self.client.force_login(self.admin)
        self.assertEqual(self.post(self.detail_url(self.business, "delete"), {"confirm": "nope"}).status_code, 400)
        self.assertTrue(Book.objects.filter(pk=self.business.pk).exists())

        response = self.post(self.detail_url(self.business, "delete"), {"confirm": "Business"})
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Book.objects.filter(pk=self.business.pk).exists())
        self.assertEqual(snapshot(self.personal), before)
        event = AuditEvent.objects.get(event_type=AuditEvent.BOOK_DELETED)
        self.assertEqual(event.metadata, {"name": "Business"})

    def test_the_last_open_book_cannot_be_deleted(self):
        self.business.archive()
        self.client.force_login(self.admin)
        response = self.post(self.detail_url(self.personal, "delete"), {"confirm": "Personal"})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Book.objects.filter(pk=self.personal.pk).exists())

    def test_a_member_cannot_delete(self):
        self.client.force_login(self.member)
        response = self.post(self.detail_url(self.business, "delete"), {"confirm": "Business"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Book.objects.filter(pk=self.business.pk).exists())

    def test_delete_is_not_a_delete_verb(self):
        self.client.force_login(self.admin)
        response = self.client.delete(self.detail_url(self.business))
        self.assertEqual(response.status_code, 405)


class BookSettingsAPITest(BooksAPITestCase):
    def url(self, book=None):
        return reverse("books:api_settings", args=(book or self.personal).url_args)

    def patch(self, body, book=None):
        return self.client.patch(self.url(book), data=json.dumps(body), content_type="application/json")

    def test_an_admin_reads_the_settings_and_their_consequence(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["slug"], "personal")
        self.assertIsNone(data["locked_through"])
        preview = data["future_income_preview"]
        self.assertEqual(preview["month"], date.today().replace(day=1).isoformat())
        self.assertEqual(
            set(preview), {"month", "unassigned", "expected_income_label", "expected_income", "expected_income_flipped"}
        )

    def test_a_member_and_a_non_member_are_refused(self):
        # A member who is not an admin gets a 404, as `book_admin_required` answers.
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.patch({"name": "Mine"}).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_rename_and_change_the_address(self):
        self.client.force_login(self.admin)
        response = self.patch({"name": "Household", "slug": "Home"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["base_url"], f"/a/{self.team.slug}/home/")
        self.personal.refresh_from_db()
        self.assertEqual((self.personal.name, self.personal.slug), ("Household", "home"))

    def test_the_forms_rules_apply(self):
        self.client.force_login(self.admin)
        for body, field in (
            ({"slug": "budget"}, "slug"),
            ({"slug": "business"}, "slug"),
            ({"name": "BUSINESS"}, "name"),
            ({"household_adults": 11}, "household_adults"),
            ({"report_timeframe": "forever"}, "report_timeframe"),
            ({"locked_through": (date.today() + timedelta(days=1)).isoformat()}, "locked_through"),
        ):
            with self.subTest(body=body):
                response = self.patch(body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.personal.refresh_from_db()
        self.assertEqual((self.personal.name, self.personal.slug), ("Personal", "personal"))

    def test_close_a_period_keep_it_when_left_out_and_reopen_it(self):
        self.client.force_login(self.admin)
        closed = date.today() - timedelta(days=30)
        self.assertEqual(self.patch({"locked_through": closed.isoformat()}).status_code, 200)
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.locked_through, closed)
        event = AuditEvent.objects.get(event_type=AuditEvent.BOOK_SETTINGS_CHANGED, book=self.personal)
        self.assertEqual(event.metadata, {"locked_through": closed.isoformat(), "locked_through_before": None})

        # A save that leaves the field out keeps the lock.
        self.assertEqual(self.patch({"household_adults": 2}).status_code, 200)
        self.personal.refresh_from_db()
        self.assertEqual((self.personal.locked_through, self.personal.household_adults), (closed, 2))

        # Null reopens every period.
        self.assertEqual(self.patch({"locked_through": None}).status_code, 200)
        self.personal.refresh_from_db()
        self.assertIsNone(self.personal.locked_through)

    def test_the_future_income_change_is_audited(self):
        self.client.force_login(self.admin)
        response = self.patch({"budget_future_income": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["budget_future_income"])
        event = AuditEvent.objects.get(event_type=AuditEvent.BOOK_SETTINGS_CHANGED, book=self.personal)
        self.assertEqual(event.metadata, {"budget_future_income": True})

    def test_an_unknown_book_is_a_404(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("books:api_settings", args=[self.team.slug, "nope"]))
        self.assertEqual(response.status_code, 404)
