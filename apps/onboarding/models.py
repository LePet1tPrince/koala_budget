from django.db import models
from django.utils import timezone

from apps.teams.models import BaseTeamModel

from .questions import CATALOG_VERSION, active_phases


class OnboardingState(BaseTeamModel):
    """
    One row per team, tracking where that team is in the guided walkthrough.

    Team-scoped rather than user-scoped: the walkthrough sets up the team's books,
    so a second member joining an already-onboarded team should not be asked to
    set them up again.

    Nothing financial lives here. The answers are the *input* that generated the
    chart of accounts; the accounts themselves are ordinary `Account` rows, and
    deleting this row would lose the record of how the books were set up but not
    the books.
    """

    PHASE_WELCOME = "welcome"
    PHASE_QUESTIONS = "questions"
    PHASE_REVIEW = "review"
    PHASE_TASKS = "tasks"
    PHASE_DONE = "done"

    PHASE_CHOICES = [
        (PHASE_WELCOME, "Welcome"),
        (PHASE_QUESTIONS, "Questions"),
        (PHASE_REVIEW, "Chart of accounts review"),
        (PHASE_TASKS, "Guided tasks"),
        (PHASE_DONE, "Done"),
    ]

    answers = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw questionnaire answers, keyed by question id. Interpret against catalog_version.",
    )
    catalog_version = models.PositiveSmallIntegerField(
        default=CATALOG_VERSION,
        help_text="Version of the question catalog these answers were given against.",
    )
    phase = models.CharField(max_length=20, choices=PHASE_CHOICES, default=PHASE_WELCOME)
    question_phase = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Which questionnaire phase the user is on, while phase is 'questions'.",
    )
    tasks_done = models.JSONField(
        default=list,
        blank=True,
        help_text="Slugs of guided tasks the user has completed or skipped.",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    skipped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ["team"]

    def __str__(self):
        return f"Onboarding for {self.team} ({self.phase})"

    @property
    def is_finished(self) -> bool:
        """Finished either way -- completed or deliberately skipped."""
        return bool(self.completed_at or self.skipped_at)

    def mark_seen(self):
        """
        Record that the takeover was opened, without advancing past the welcome.

        Separate from `start()` so the funnel measures from the first sight of the
        flow, while the phase only moves when the user actually begins.
        """
        if self.started_at is None:
            self.started_at = timezone.now()

    def start(self):
        """The user has begun answering; move off the welcome screen."""
        self.mark_seen()
        self.phase = self.PHASE_QUESTIONS
        phases = active_phases()
        self.question_phase = phases[0] if phases else ""

    def complete(self):
        self.completed_at = timezone.now()
        self.phase = self.PHASE_DONE

    def skip(self):
        self.skipped_at = timezone.now()
        self.phase = self.PHASE_DONE

    def mark_task(self, slug: str):
        """Record a guided task as done. Idempotent -- a repeat is not an error."""
        if slug not in self.tasks_done:
            self.tasks_done = [*self.tasks_done, slug]
