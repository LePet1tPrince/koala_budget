from datetime import date

from django.db.utils import IntegrityError
from django.test import TestCase

from apps.monthly_review.models import MonthlyReviewState
from apps.teams.models import Team


class MonthlyReviewStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book

    def test_month_normalized_to_first_of_month(self):
        state = MonthlyReviewState.objects.create(book=self.book, month=date(2026, 8, 15))
        self.assertEqual(state.month, date(2026, 8, 1))

    def test_is_finished_false_by_default(self):
        state = MonthlyReviewState.objects.create(book=self.book, month=date(2026, 8, 1))
        self.assertFalse(state.is_finished)

    def test_complete_marks_finished(self):
        state = MonthlyReviewState.objects.create(book=self.book, month=date(2026, 8, 1))
        state.complete()
        state.save()
        self.assertTrue(state.is_finished)
        self.assertIsNotNone(state.completed_at)

    def test_dismiss_marks_finished(self):
        state = MonthlyReviewState.objects.create(book=self.book, month=date(2026, 8, 1))
        state.dismiss()
        state.save()
        self.assertTrue(state.is_finished)

    def test_advance_records_steps_seen(self):
        state = MonthlyReviewState.objects.create(book=self.book, month=date(2026, 8, 1))
        state.advance(1)
        state.advance(2)
        state.advance(1)
        self.assertEqual(state.step, 1)
        self.assertEqual(state.steps_seen, [1, 2])

    def test_unique_together_team_month(self):
        MonthlyReviewState.objects.create(book=self.book, month=date(2026, 8, 1))
        with self.assertRaises(IntegrityError):
            MonthlyReviewState.objects.create(book=self.book, month=date(2026, 8, 1))


class HealthStepRemovedMigrationTests(TestCase):
    """0005 shifts stored walkthrough positions down by one now the health step is a modal."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book

    def _migration(self):
        import importlib

        return importlib.import_module("apps.monthly_review.migrations.0005_health_step_removed")

    def test_shift_down_moves_every_step_back_one(self):
        from django.apps import apps

        on_health = MonthlyReviewState.objects.create(book=self.book, month=date(2026, 7, 1), step=0, steps_seen=[0])
        mid_way = MonthlyReviewState.objects.create(
            book=self.book, month=date(2026, 8, 1), step=4, steps_seen=[0, 1, 2, 3, 4]
        )

        self._migration().shift_down(apps, None)

        on_health.refresh_from_db()
        mid_way.refresh_from_db()
        self.assertEqual((on_health.step, on_health.steps_seen), (0, []))
        self.assertEqual((mid_way.step, mid_way.steps_seen), (3, [0, 1, 2, 3]))
