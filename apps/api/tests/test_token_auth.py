"""
Session-token auth for the phone app: allauth headless `app` client tokens, sent as
`X-Session-Token`, resolved by `SessionTokenMiddleware` and `SessionTokenAuthentication`.

Every client here enforces CSRF (`enforce_csrf_checks=True`): Django's test client
waives CSRF by default, which would make the CSRF assertions vacuous.
"""

import json
from unittest import mock

from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.audit.utils import get_current_user
from apps.books.helpers import SESSION_BOOK_BY_TEAM
from apps.books.tests.factories import build_book_data, second_book
from apps.budget.services import GoalService
from apps.journal.models import JournalEntry
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

LOGIN_URL = "/_allauth/app/v1/auth/login"
PASSWORD = "correct horse battery staple"


def make_user(email):
    user = CustomUser.objects.create_user(username=email, email=email, password=PASSWORD)
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


class TokenAuthTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user("phone@example.com")
        cls.team = Team.objects.create(name="Phone Team", slug="phone-team")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.data = build_book_data(cls.team.default_book, "QQPHONEQQ", cls.user)
        cls.book = cls.data.book

        cls.other = make_user("other@example.com")
        cls.other_team = Team.objects.create(name="Other Team", slug="other-team")
        cls.other_team.members.add(cls.other, through_defaults={"role": ROLE_ADMIN})
        cls.other_data = build_book_data(cls.other_team.default_book, "QQOTHERQQ", cls.other)

    def setUp(self):
        # The auth rate limiter and DRF throttles count in the cache.
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)

    def login(self, email="phone@example.com"):
        response = self.client.post(
            LOGIN_URL, data=json.dumps({"email": email, "password": PASSWORD}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["meta"]["session_token"]

    def book_url(self, name, book=None, **kwargs):
        book = book or self.book
        return reverse(name, kwargs={"team_slug": book.team.slug, "book_slug": book.slug, **kwargs})

    def entry_body(self, description="From the phone"):
        return json.dumps(
            {
                "entry_date": "2026-03-10",
                "description": description,
                "lines": [
                    {"account": self.data.groceries.id, "dr_amount": "5.00", "cr_amount": "0"},
                    {"account": self.data.chequing.id, "dr_amount": "0", "cr_amount": "5.00"},
                ],
            }
        )


class LoginTest(TokenAuthTestCase):
    def test_app_login_returns_a_session_token(self):
        response = self.client.post(
            LOGIN_URL,
            data=json.dumps({"email": self.user.email, "password": PASSWORD}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["meta"]["is_authenticated"])
        self.assertTrue(body["meta"]["session_token"])
        self.assertEqual(body["data"]["user"]["id"], self.user.id)

    def test_wrong_password_returns_no_token(self):
        response = self.client.post(
            LOGIN_URL, data=json.dumps({"email": self.user.email, "password": "nope"}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("session_token", response.json().get("meta", {}))


class TokenRequestTest(TokenAuthTestCase):
    def test_token_reads_a_drf_book_endpoint(self):
        token = self.login()
        response = self.client.get(self.book_url("journal:journal-entry-list"), headers={"X-Session-Token": token})
        self.assertEqual(response.status_code, 200)
        self.assertIn("QQPHONEQQ", response.content.decode())

    def test_token_writes_without_csrf_and_the_audit_row_names_the_user(self):
        token = self.login()
        response = self.client.post(
            self.book_url("journal:journal-entry-list"),
            data=self.entry_body(),
            content_type="application/json",
            headers={"X-Session-Token": token},
        )
        self.assertEqual(response.status_code, 201, response.content)
        entry = JournalEntry.objects.get(book=self.book, description="From the phone")
        log = AuditLog.objects.get(
            journal_entry_id=entry.pk, source_model="JournalEntry", action=AuditLog.ACTION_CREATE
        )
        self.assertEqual(log.user, self.user)

    def test_token_reaches_a_board_write_without_csrf(self):
        token = self.login()
        response = self.client.post(
            self.book_url("accounts:board-set-hidden"),
            data=json.dumps({"account_id": self.data.groceries.id, "is_hidden": True}),
            content_type="application/json",
            headers={"X-Session-Token": token},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.data.groceries.refresh_from_db()
        self.assertTrue(self.data.groceries.is_hidden)

    def test_token_signs_in_a_plain_django_page(self):
        # Not a DRF view: only `SessionTokenMiddleware` can have set `request.user`
        # (DRF authentication never runs), so a 200 rather than a redirect to login
        # is the middleware's doing.
        token = self.login()
        response = self.client.get(self.book_url("web_book:home"), headers={"X-Session-Token": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.user, self.user)

    def test_token_plain_form_post_skips_csrf_and_is_audited_as_the_user(self):
        # A no-JS form view (plain Django): the middleware must both waive CSRF for
        # the header token and sign the user in before `AuditUserMiddleware` stashes
        # them for the audit signals, or the write would be audited as nobody.
        token = self.login()
        seen = []
        update_allocation = GoalService.update_allocation

        def spy(service, *args, **kwargs):
            seen.append(get_current_user())
            return update_allocation(service, *args, **kwargs)

        with mock.patch.object(GoalService, "update_allocation", spy):
            response = self.client.post(
                self.book_url("budget:goal_allocate", pk=self.data.goal.pk),
                data={"month": "2026-03-01", "amount": "75"},
                headers={"X-Session-Token": token},
            )
        self.assertEqual(response.status_code, 302, response.content)
        self.assertNotIn(reverse("account_login"), response["Location"])
        self.assertEqual(seen, [self.user])

    def test_a_token_request_sets_no_session_cookie_and_keeps_state_on_the_token(self):
        token = self.login()
        client = Client(enforce_csrf_checks=True)  # no cookies at all, like the phone
        response = client.get(self.book_url("book_api:nav_state"), headers={"X-Session-Token": token})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("sessionid", response.cookies)
        # The last-opened book was remembered on the token's own session.
        from allauth.headless.internal.sessionkit import lookup_session

        session = lookup_session(token)
        self.assertEqual(session[SESSION_BOOK_BY_TEAM], {str(self.team.id): self.book.id})


class TokenRefusedTest(TokenAuthTestCase):
    def test_an_invalid_token_is_a_401_on_the_api(self):
        response = self.client.get(self.book_url("journal:journal-entry-list"), headers={"X-Session-Token": "bogus"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "X-Session-Token")

    def test_an_invalid_token_authenticates_nothing(self):
        before = JournalEntry.objects.count()
        response = self.client.post(
            self.book_url("journal:journal-entry-list"),
            data=self.entry_body(),
            content_type="application/json",
            headers={"X-Session-Token": "bogus"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(JournalEntry.objects.count(), before)
        # A page sees an anonymous user and sends them to sign in.
        page = self.client.get(self.book_url("web_book:home"), headers={"X-Session-Token": "bogus"})
        self.assertEqual(page.status_code, 302)
        self.assertIn(reverse("account_login"), page["Location"])

    def test_a_logged_out_token_stops_working(self):
        token = self.login()
        self.client.delete("/_allauth/app/v1/auth/session", headers={"X-Session-Token": token})
        response = self.client.get(self.book_url("journal:journal-entry-list"), headers={"X-Session-Token": token})
        self.assertEqual(response.status_code, 401)

    def test_anonymous_without_a_token_is_still_a_403(self):
        response = self.client.get(self.book_url("journal:journal-entry-list"))
        self.assertEqual(response.status_code, 403)

    def test_a_token_cannot_read_another_users_book(self):
        token = self.login()
        other_book = self.other_data.book
        response = self.client.get(
            self.book_url("journal:journal-entry-list", book=other_book), headers={"X-Session-Token": token}
        )
        self.assertIn(response.status_code, (403, 404))
        self.assertNotIn("QQOTHERQQ", response.content.decode())
        nav = self.client.get(self.book_url("book_api:nav_state", book=other_book), headers={"X-Session-Token": token})
        self.assertIn(nav.status_code, (403, 404))

    def test_a_token_cannot_reach_another_book_of_a_team_it_is_not_in(self):
        token = self.login()
        hidden = second_book(self.other_team)
        response = self.client.get(self.book_url("rules:rule-list", book=hidden), headers={"X-Session-Token": token})
        self.assertIn(response.status_code, (403, 404))


class SessionCookieTest(TokenAuthTestCase):
    def test_a_session_post_without_csrf_is_still_refused(self):
        self.client.force_login(self.user)
        before = JournalEntry.objects.count()
        response = self.client.post(
            self.book_url("journal:journal-entry-list"), data=self.entry_body(), content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF", response.json()["detail"])
        self.assertEqual(JournalEntry.objects.count(), before)

    def test_a_session_post_without_csrf_to_a_board_write_is_still_refused(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.book_url("accounts:board-set-hidden"),
            data=json.dumps({"account_id": self.data.groceries.id, "is_hidden": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_a_cookie_session_wins_over_a_token_and_keeps_csrf(self):
        token = self.login("other@example.com")
        self.client.force_login(self.user)
        response = self.client.post(
            self.book_url("journal:journal-entry-list"),
            data=self.entry_body(),
            content_type="application/json",
            headers={"X-Session-Token": token},
        )
        self.assertEqual(response.status_code, 403)
        # Reads go through as the cookie's user, not the token's.
        response = self.client.get(self.book_url("journal:journal-entry-list"), headers={"X-Session-Token": token})
        self.assertEqual(response.status_code, 200)
        self.assertIn("QQPHONEQQ", response.content.decode())
