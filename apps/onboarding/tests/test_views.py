"""
Tests for the onboarding takeover and its JSON endpoints.

The flow is server-driven -- the client renders what the server says and posts
answers back -- so these cover the rules the UI is not trusted to enforce.
"""

import json
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Account
from apps.budget.models import Goal
from apps.onboarding.models import OnboardingState
from apps.onboarding.questions import QUESTION_CATALOG
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


def _answer_everything() -> dict:
    return {q.id: [o.value for o in q.options] for q in QUESTION_CATALOG if q.options}


class OnboardingViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Fresh Team", slug="fresh-team")
        cls.user = CustomUser.objects.create_user(username="member", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.client.force_login(self.user)
        self.home_url = reverse("onboarding:home", args=[self.team.slug])
        self.answers_url = reverse("onboarding:api_answers", args=[self.team.slug])
        self.complete_url = reverse("onboarding:api_complete", args=[self.team.slug])
        self.skip_url = reverse("onboarding:api_skip", args=[self.team.slug])
        self.preview_url = reverse("onboarding:api_preview_coa", args=[self.team.slug])

    def post_json(self, url, payload=None):
        return self.client.post(
            url,
            data=json.dumps(payload or {}),
            content_type="application/json",
            headers={"accept": "application/json"},
        )


class TakeoverPageTest(OnboardingViewTestCase):
    def test_renders_and_creates_state_lazily(self):
        self.assertFalse(OnboardingState.objects.filter(team=self.team).exists())

        response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(OnboardingState.objects.filter(team=self.team).exists())

    def test_props_carry_the_catalog(self):
        response = self.client.get(self.home_url)
        props = response.context["onboarding_props"]

        self.assertEqual(len(props["questions"]), len(QUESTION_CATALOG))
        self.assertEqual(props["teamSlug"], self.team.slug)

    def test_props_carry_no_chart_of_accounts_rules(self):
        """What an answer creates is the server's business, not the client's."""
        response = self.client.get(self.home_url)

        for question in response.context["onboarding_props"]["questions"]:
            for option in question["options"]:
                with self.subTest(option=option["value"]):
                    self.assertEqual(set(option), {"value", "label", "help_text", "catch_all"})

    def test_finished_team_is_sent_home(self):
        state = OnboardingState.objects.create(team=self.team)
        state.complete()
        state.save()

        response = self.client.get(self.home_url)
        self.assertRedirects(response, reverse("web_team:home", args=[self.team.slug]))

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.home_url)
        self.assertNotEqual(response.status_code, 200)


class SaveAnswersTest(OnboardingViewTestCase):
    def test_saves_and_advances(self):
        response = self.post_json(self.answers_url, {"answers": {"housing": "rent"}})

        self.assertEqual(response.status_code, 200)
        state = OnboardingState.objects.get(team=self.team)
        self.assertEqual(state.answers["housing"], ["rent"])

    def test_answers_merge_rather_than_replace(self):
        """Posting one phase at a time must not drop the previous one."""
        self.post_json(self.answers_url, {"answers": {"housing": "rent"}})
        self.post_json(self.answers_url, {"answers": {"kids": "yes"}})

        state = OnboardingState.objects.get(team=self.team)
        self.assertEqual(state.answers["housing"], ["rent"])
        self.assertEqual(state.answers["kids"], ["yes"])

    def test_unknown_question_is_dropped(self):
        self.post_json(self.answers_url, {"answers": {"not_a_question": "yes"}})

        self.assertEqual(OnboardingState.objects.get(team=self.team).answers, {})

    def test_unknown_option_is_dropped(self):
        self.post_json(self.answers_url, {"answers": {"housing": "houseboat"}})

        self.assertEqual(OnboardingState.objects.get(team=self.team).answers, {})

    def test_malformed_body_is_tolerated(self):
        response = self.client.post(self.answers_url, data="not json", content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_reports_what_is_still_missing(self):
        response = self.post_json(self.answers_url, {"answers": {"housing": "rent"}})

        missing = response.json()["unanswered_required"]
        self.assertIn("income_sources", missing)
        self.assertNotIn("housing", missing)

    def test_get_is_refused(self):
        self.assertEqual(self.client.get(self.answers_url).status_code, 405)


class CompleteTest(OnboardingViewTestCase):
    def test_builds_the_chart_of_accounts(self):
        response = self.post_json(self.complete_url, {"answers": _answer_everything()})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Account.objects.filter(team=self.team, name="Mortgage").exists())
        self.assertTrue(OnboardingState.objects.get(team=self.team).completed_at)

    def test_only_the_answered_accounts_are_created(self):
        self.post_json(
            self.complete_url,
            {
                "answers": {
                    "income_sources": ["employment"],
                    "household_shape": "solo",
                    "housing": "rent",
                    "kids": "no",
                    "transport": ["transit"],
                    "debts": ["none"],
                    "savings": ["none"],
                    "extras": ["none"],
                }
            },
        )

        names = set(Account.objects.filter(team=self.team).values_list("name", flat=True))
        self.assertIn("Rent", names)
        self.assertNotIn("Mortgage", names)
        self.assertNotIn("Vehicle", names)

    def test_refuses_while_a_required_question_is_unanswered(self):
        response = self.post_json(self.complete_url, {"answers": {"housing": "rent"}})

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["unanswered_required"])
        self.assertFalse(Account.objects.filter(team=self.team).exists())
        self.assertFalse(OnboardingState.objects.get(team=self.team).is_finished)

    def test_is_idempotent(self):
        """A double submit must not double the chart of accounts."""
        answers = _answer_everything()
        self.post_json(self.complete_url, {"answers": answers})
        before = Account.objects.filter(team=self.team).count()

        self.post_json(self.complete_url, {"answers": answers})
        self.assertEqual(Account.objects.filter(team=self.team).count(), before)

    def test_creates_the_first_goal_when_named(self):
        answers = {**_answer_everything(), "first_goal": {"name": "Emergency fund", "target_amount": "5000"}}
        self.post_json(self.complete_url, {"answers": answers})

        goal = Goal.objects.get(team=self.team)
        self.assertEqual(goal.name, "Emergency fund")
        self.assertEqual(goal.target_amount, Decimal("5000.00"))

    def test_goal_account_avoids_the_system_equity_group(self):
        """Goal.save() falls back to any equity group; a user's goal must not land in a system one."""
        answers = {**_answer_everything(), "first_goal": {"name": "New bike", "target_amount": "900"}}
        self.post_json(self.complete_url, {"answers": answers})

        goal = Goal.objects.get(team=self.team)
        self.assertFalse(goal.account.account_group.is_system)

    def test_a_blank_goal_name_creates_nothing(self):
        answers = {**_answer_everything(), "first_goal": {"name": "  ", "target_amount": "100"}}
        self.post_json(self.complete_url, {"answers": answers})

        self.assertFalse(Goal.objects.filter(team=self.team).exists())


class SkipTest(OnboardingViewTestCase):
    def test_applies_the_fallback_template(self):
        """Skipping must not leave a team with no accounts to work in."""
        self.post_json(self.skip_url)

        self.assertTrue(Account.objects.filter(team=self.team).exists())
        self.assertTrue(OnboardingState.objects.get(team=self.team).skipped_at)

    def test_a_plain_form_post_redirects_rather_than_returning_json(self):
        """The no-JS fallback posts a form; landing on raw JSON would be a dead end."""
        response = self.client.post(self.skip_url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("web_team:home", args=[self.team.slug]))

    def test_skipping_twice_is_harmless(self):
        self.post_json(self.skip_url)
        response = self.post_json(self.skip_url)

        self.assertEqual(response.status_code, 200)


class PermissionTest(OnboardingViewTestCase):
    """A team's onboarding is not reachable by anyone outside it."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.outsider = CustomUser.objects.create_user(username="outsider", password="pass")
        cls.other_team = Team.objects.create(name="Other", slug="other-fresh")
        cls.other_team.members.add(cls.outsider, through_defaults={"role": ROLE_ADMIN})

    def test_non_member_cannot_view(self):
        self.client.force_login(self.outsider)
        self.assertNotEqual(self.client.get(self.home_url).status_code, 200)

    def test_non_member_cannot_complete(self):
        self.client.force_login(self.outsider)
        response = self.post_json(self.complete_url, {"answers": _answer_everything()})

        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(Account.objects.filter(team=self.team).exists())

    def test_non_member_cannot_skip(self):
        self.client.force_login(self.outsider)
        self.post_json(self.skip_url)

        self.assertFalse(OnboardingState.objects.filter(team=self.team, skipped_at__isnull=False).exists())


class TeamHomeRedirectTest(OnboardingViewTestCase):
    @override_settings(ONBOARDING_ENABLED=True)
    def test_unonboarded_team_is_redirected(self):
        response = self.client.get(reverse("web_team:home", args=[self.team.slug]))
        self.assertRedirects(response, self.home_url)

    @override_settings(ONBOARDING_ENABLED=True)
    def test_finished_team_reaches_the_dashboard(self):
        self.post_json(self.skip_url)

        response = self.client.get(reverse("web_team:home", args=[self.team.slug]))
        self.assertEqual(response.status_code, 200)

    @override_settings(ONBOARDING_ENABLED=False)
    def test_disabling_onboarding_leaves_the_dashboard_alone(self):
        response = self.client.get(reverse("web_team:home", args=[self.team.slug]))
        self.assertEqual(response.status_code, 200)


VALID_ANSWERS = {
    "income_sources": ["employment"],
    "household_shape": "solo",
    "housing": "rent",
    "kids": "no",
    "transport": ["transit"],
    "debts": ["none"],
    "savings": ["tfsa"],
    "extras": ["none"],
}


class PreviewCoaTest(OnboardingViewTestCase):
    def test_returns_sections_without_writing_anything(self):
        response = self.post_json(self.preview_url, {"answers": VALID_ANSWERS})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["sections"])
        self.assertFalse(Account.objects.filter(team=self.team).exists())
        self.assertFalse(OnboardingState.objects.get(team=self.team).is_finished)

    def test_reflects_the_answers(self):
        response = self.post_json(self.preview_url, {"answers": VALID_ANSWERS})

        shown = {n for s in response.json()["sections"] for g in s["groups"] for n in g["accounts"]}
        self.assertIn("Rent", shown)
        self.assertNotIn("Mortgage", shown)

    def test_applies_edits_to_the_preview(self):
        response = self.post_json(
            self.preview_url,
            {"answers": VALID_ANSWERS, "edits": {"removed": ["Rent"], "renamed": {"Groceries": "Food"}}},
        )

        shown = {n for s in response.json()["sections"] for g in s["groups"] for n in g["accounts"]}
        self.assertNotIn("Rent", shown)
        self.assertIn("Food", shown)

    def test_an_invalid_edit_is_refused(self):
        response = self.post_json(
            self.preview_url, {"answers": VALID_ANSWERS, "edits": {"renamed": {"Groceries": "Dining Out"}}}
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["error"])

    def test_non_member_is_refused(self):
        outsider = CustomUser.objects.create_user(username="nosy", password="pass")
        self.client.force_login(outsider)

        self.assertNotEqual(self.post_json(self.preview_url, {"answers": VALID_ANSWERS}).status_code, 200)


class CompleteWithEditsTest(OnboardingViewTestCase):
    def test_edits_are_applied_to_what_gets_created(self):
        self.post_json(
            self.complete_url,
            {
                "answers": VALID_ANSWERS,
                "edits": {
                    "removed": ["Tenant Insurance"],
                    "renamed": {"Groceries": "Food & Drink"},
                    "added": [{"group": "Variable Expenses", "name": "Concerts"}],
                },
            },
        )

        names = set(Account.objects.filter(team=self.team).values_list("name", flat=True))
        self.assertNotIn("Tenant Insurance", names)
        self.assertNotIn("Groceries", names)
        self.assertIn("Food & Drink", names)
        self.assertIn("Concerts", names)

    def test_an_invalid_edit_creates_nothing(self):
        """All-or-nothing: a refused edit must not leave a half-built chart."""
        response = self.post_json(
            self.complete_url,
            {"answers": VALID_ANSWERS, "edits": {"added": [{"group": "Nowhere", "name": "Mystery"}]}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Account.objects.filter(team=self.team).exists())
        self.assertFalse(OnboardingState.objects.get(team=self.team).is_finished)

    def test_the_system_account_survives_a_removal_attempt(self):
        response = self.post_json(
            self.complete_url,
            {"answers": VALID_ANSWERS, "edits": {"removed": ["Reconciliation Adjustments"]}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Account.objects.filter(team=self.team).exists())

    def test_an_account_cannot_be_smuggled_into_the_system_group(self):
        """
        The edit shape is why this is not expressible: additions name a group from
        the generated chart, and `is_system` is never client-supplied.
        """
        self.post_json(
            self.complete_url,
            {
                "answers": VALID_ANSWERS,
                "edits": {"added": [{"group": "Equity Adjustments", "name": "Sneaky"}]},
            },
        )

        sneaky = Account.objects.filter(team=self.team, name="Sneaky").first()
        if sneaky is not None:
            self.assertFalse(sneaky.is_system)

    def test_malformed_edits_fall_back_to_the_unedited_chart(self):
        self.post_json(self.complete_url, {"answers": VALID_ANSWERS, "edits": "not an object"})

        self.assertTrue(Account.objects.filter(team=self.team, name="Rent").exists())
