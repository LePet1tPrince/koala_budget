"""
Server-rendered pages that embed an API body (`json_script`) for their own scripts
instead of having them fetch it: each embedded body must be exactly what the API
endpoint answers for the same parameters, so the page and the phone app read one
contract. The pages are listed in `TemplateDataPropsTest.EMBEDDED_API_BODIES`.
"""

import json
import re

from django.test import TestCase
from django.urls import reverse

from apps.books.tests.factories import MONTH, build_book_data
from apps.onboarding.models import OnboardingState
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser
from apps.utils.months import format_month

from .test_api_surface import TemplateDataPropsTest

RANGE = {"start_date": MONTH.isoformat(), "end_date": MONTH.replace(day=31).isoformat()}

# (template, json_script id) -> (page URL name, page params, API URL name, API params, needs the account pk)
CASES = {
    ("web/app_home.html", "home-data"): ("web_book:home", {}, "book_api:home", {}, False),
    ("reports/spending.html", "spending-report-data"): (
        "reports:spending",
        {**RANGE, "columns": "month"},
        "reports:api_spending",
        {**RANGE, "columns": "month"},
        False,
    ),
    ("reports/net_worth.html", "net-worth-report-data"): (
        "reports:net_worth",
        {"start_month": "2026-02", "end_month": format_month(MONTH)},
        "reports:api_net_worth",
        {"start_month": "2026-02", "end_month": format_month(MONTH)},
        False,
    ),
    ("budget/goals_list.html", "goals-data"): (
        "budget:goals_list",
        {"month": MONTH.isoformat()},
        "budget:api_goals",
        {"month": format_month(MONTH)},
        False,
    ),
    ("accounts/account_detail.html", "account-charts-data"): (
        "accounts:account_detail",
        RANGE,
        "accounts:account-charts",
        RANGE,
        True,
    ),
}


def embedded(response, element_id):
    match = re.search(
        rf'<script id="{re.escape(element_id)}" type="application/json">(.*?)</script>', response.content.decode(), re.S
    )
    return json.loads(match.group(1)) if match else None


class EmbeddedApiBodiesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Embedded", slug="embedded")
        cls.user = CustomUser.objects.create_user(username="embedded@example.com", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.data = build_book_data(cls.team.default_book, "QQEMBEDQQ", cls.user)
        state, _ = OnboardingState.objects.get_or_create(book=cls.data.book)
        state.complete()
        state.finish_tasks()
        state.save()

    def setUp(self):
        self.client.force_login(self.user)

    def test_every_embedded_body_has_a_case(self):
        self.assertEqual(set(CASES), set(TemplateDataPropsTest.EMBEDDED_API_BODIES))

    def test_each_embedded_body_is_the_api_answer(self):
        for (template, element_id), (page, page_params, api, api_params, by_account) in CASES.items():
            with self.subTest(template=template):
                args = [*self.data.book.url_args, *([self.data.chequing.pk] if by_account else [])]
                response = self.client.get(reverse(page, args=args), page_params)
                self.assertEqual(response.status_code, 200)
                self.assertIn(template, [t.name for t in response.templates])
                body = embedded(response, element_id)
                self.assertIsNotNone(body, f"#{element_id} is not on the page")
                answer = self.client.get(reverse(api, args=args), api_params)
                self.assertEqual(answer.status_code, 200)
                self.assertEqual(body, answer.json())

    def test_the_embedded_body_is_escaped(self):
        """`json_script` escapes `<`, so a name can't close the script element."""
        self.data.groceries.name = "</script><b>x"
        self.data.groceries.save()
        response = self.client.get(reverse("reports:spending", args=self.data.book.url_args), RANGE)
        self.assertNotIn("</script><b>x", response.content.decode())
        names = [
            a["name"] for g in embedded(response, "spending-report-data")["expenses"]["groups"] for a in g["accounts"]
        ]
        self.assertIn("</script><b>x", names)
