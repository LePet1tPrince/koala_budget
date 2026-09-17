"""Tests for OnboardingState."""

from django.db.utils import IntegrityError
from django.test import TestCase

from apps.onboarding.models import OnboardingState
from apps.onboarding.questions import CATALOG_VERSION, active_phases
from apps.teams.context import set_current_team
from apps.teams.models import Team


class OnboardingStateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Stateful", slug="stateful")

    def test_defaults(self):
        state = OnboardingState.objects.create(team=self.team)

        self.assertEqual(state.phase, OnboardingState.PHASE_WELCOME)
        self.assertEqual(state.answers, {})
        self.assertEqual(state.tasks_done, [])
        self.assertEqual(state.catalog_version, CATALOG_VERSION)
        self.assertFalse(state.is_finished)

    def test_one_row_per_team(self):
        """Team-scoped, not user-scoped -- a second member must not re-onboard."""
        OnboardingState.objects.create(team=self.team)

        with self.assertRaises(IntegrityError):
            OnboardingState.objects.create(team=self.team)

    def test_start_moves_to_the_first_question_phase(self):
        state = OnboardingState.objects.create(team=self.team)
        state.start()

        self.assertEqual(state.phase, OnboardingState.PHASE_QUESTIONS)
        self.assertEqual(state.question_phase, active_phases()[0])
        self.assertIsNotNone(state.started_at)

    def test_start_does_not_reset_the_clock(self):
        """Resuming is not starting again; the funnel measures from the first visit."""
        state = OnboardingState.objects.create(team=self.team)
        state.start()
        first = state.started_at

        state.start()
        self.assertEqual(state.started_at, first)

    def test_complete_and_skip_both_finish(self):
        completed = OnboardingState.objects.create(team=self.team)
        completed.complete()
        self.assertTrue(completed.is_finished)
        self.assertEqual(completed.phase, OnboardingState.PHASE_DONE)

        other = Team.objects.create(name="Skipper", slug="skipper")
        skipped = OnboardingState.objects.create(team=other)
        skipped.skip()
        self.assertTrue(skipped.is_finished)
        self.assertEqual(skipped.phase, OnboardingState.PHASE_DONE)

    def test_mark_task_is_idempotent(self):
        state = OnboardingState.objects.create(team=self.team)
        state.mark_task("import")
        state.mark_task("import")

        self.assertEqual(state.tasks_done, ["import"])

    def test_mark_task_preserves_order(self):
        state = OnboardingState.objects.create(team=self.team)
        state.mark_task("import")
        state.mark_task("categorize")

        self.assertEqual(state.tasks_done, ["import", "categorize"])

    def test_answers_round_trip_through_the_database(self):
        state = OnboardingState.objects.create(team=self.team, answers={"savings": ["tfsa", "rrsp"], "housing": "rent"})
        state.refresh_from_db()

        self.assertEqual(state.answers["savings"], ["tfsa", "rrsp"])
        self.assertEqual(state.answers["housing"], "rent")


class TeamScopingTest(TestCase):
    """`for_team` is the manager views use; it must not leak across teams."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Mine", slug="mine")
        cls.other = Team.objects.create(name="Theirs", slug="theirs")
        OnboardingState.objects.create(team=cls.team)
        OnboardingState.objects.create(team=cls.other)

    def test_for_team_filters_to_the_current_team(self):
        set_current_team(self.team)
        try:
            states = list(OnboardingState.for_team.all())
        finally:
            set_current_team(None)

        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].team, self.team)
