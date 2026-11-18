from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.bank_feed.services import nav as feed_nav
from apps.books.tests.factories import build_book_data, second_book
from apps.budget.unassigned import current_unassigned
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser
from apps.utils.months import format_month


class NavStateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Nav Team", slug="nav")
        cls.admin = CustomUser.objects.create_user(username="nav@example.com", password="pass")
        cls.member = CustomUser.objects.create_user(username="member@example.com", password="pass")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        cls.data = build_book_data(cls.team.default_book, "QQNAVQQ", cls.admin)
        cls.book = cls.data.book

    def url(self, book=None):
        return reverse("book_api:nav_state", args=(book or self.book).url_args)

    def test_the_chrome_figures(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["inbox_count"], feed_nav.inbox_count(self.book))
        self.assertGreater(body["inbox_count"], 0)

        institutions = body["feed_institutions"]
        self.assertEqual([i["name"] for i in institutions], ["Bank of QQNAVQQ", None])
        self.assertEqual(
            institutions[0]["accounts"],
            [{"id": self.data.chequing.id, "name": "Chequing QQNAVQQ", "is_bank_account": True}],
        )
        self.assertEqual([a["id"] for a in institutions[1]["accounts"]], [self.data.savings.id])

        unassigned = current_unassigned(self.book)
        self.assertEqual(
            body["unassigned"],
            {
                "month": format_month(date.today()),
                "amount": f"{unassigned.amount:.2f}",
                "state": unassigned.state,
                "label": str(unassigned.label),
                "expected_income": None,
            },
        )
        # The fixture finished its walkthrough.
        self.assertEqual(body["onboarding_rail"], {"visible": False})

    def test_matches_what_the_sidebar_renders(self):
        """The processors and the endpoint read the same functions."""
        self.client.force_login(self.admin)
        page = self.client.get(reverse("web_book:home", args=self.book.url_args))
        self.assertEqual(page.status_code, 200)
        body = self.client.get(self.url()).json()
        self.assertEqual(body["inbox_count"], page.context["inbox_count"])
        self.assertEqual(
            [[a["id"] for a in i["accounts"]] for i in body["feed_institutions"]],
            [[a.id for a in i["accounts"]] for i in page.context["nav_feed_institutions"]],
        )
        self.assertEqual(body["unassigned"]["amount"], page.context["unassigned_pill"]["raw"])

    def test_rail_and_expected_income_when_on(self):
        OnboardingState.objects.filter(book=self.book).update(phase=OnboardingState.PHASE_TASKS)
        self.book.budget_future_income = True
        self.book.save()
        self.client.force_login(self.admin)
        body = self.client.get(self.url()).json()
        self.assertEqual(body["onboarding_rail"], {"visible": True})
        expected = body["unassigned"]["expected_income"]
        self.assertEqual(expected["label"], "Expected income")
        self.assertRegex(expected["amount"], r"^-?\d+\.\d{2}$")

    def test_an_empty_book(self):
        book = second_book(self.team)
        self.client.force_login(self.admin)
        body = self.client.get(self.url(book)).json()
        self.assertEqual(body["inbox_count"], 0)
        self.assertEqual(body["feed_institutions"], [])
        self.assertEqual(body["unassigned"]["amount"], "0.00")
        self.assertEqual(body["unassigned"]["state"], "zero")

    def test_permissions(self):
        # Anonymous.
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        # Not a member of the team.
        outsider = CustomUser.objects.create_user(username="out@example.com", password="pass")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        # A member, on a book slug the team doesn't have.
        self.client.force_login(self.member)
        response = self.client.get(reverse("book_api:nav_state", args=(self.team.slug, "no-such-book")))
        self.assertEqual(response.status_code, 404)

    def test_reads_only(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url()).status_code, 405)
