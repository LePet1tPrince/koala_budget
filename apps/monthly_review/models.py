from django.db import models
from django.utils import timezone

from apps.books.models import BaseBookModel


class MonthlyReviewState(BaseBookModel):
    """
    One row per book per month, tracking progress through the guided monthly
    review walkthrough for that month.

    Figures are never stored here -- the review always recomputes from the
    ledger, so correcting an old transaction corrects every review that
    touches it. This row only remembers where the user got to and whether
    they finished, so a month can be revisited without re-walking it.
    """

    month = models.DateField(help_text="First day of the reviewed month.")
    step = models.PositiveSmallIntegerField(default=0)
    steps_seen = models.JSONField(default=list, blank=True)
    baseline = models.CharField(max_length=4, default="3m")
    notes = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ["book", "month"]
        ordering = ["-month"]

    def __str__(self):
        return f"Monthly review for {self.book} — {self.month:%Y-%m}"

    def save(self, *args, **kwargs):
        self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)

    @property
    def is_finished(self) -> bool:
        """Past the walkthrough, either way -- completed or dismissed."""
        return bool(self.completed_at or self.dismissed_at)

    def mark_seen(self):
        if self.started_at is None:
            self.started_at = timezone.now()

    def start(self):
        self.mark_seen()

    def advance(self, step: int):
        """Record the current step and that it has been seen."""
        self.step = step
        if step not in self.steps_seen:
            self.steps_seen = [*self.steps_seen, step]

    def complete(self):
        self.completed_at = timezone.now()

    def dismiss(self):
        self.dismissed_at = timezone.now()
