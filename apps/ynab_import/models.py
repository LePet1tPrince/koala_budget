"""
One row per attempt to import a YNAB export.

The row exists for three reasons, in order of how much they cost to do without:

* the apply step runs in Celery (6,600 entries is not request work), and a worker
  cannot read a file out of the request that started it;
* the wizard walks several screens before applying, and re-uploading a 1 MB CSV at
  every step to keep the server stateless is a worse trade than storing it once;
* an import is a large, one-way change to a team's books, and what was imported
  should be answerable afterwards.

The exports are held as text rather than files so a worker in another container
reads the same bytes the browser sent, with no shared volume or object store to
configure. They are cleared once the import finishes -- keeping someone's entire
financial history in a staging table after it has been imported into the ledger
buys nothing.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.teams.models import BaseTeamModel

# Refuse an upload larger than this. The sample export's register is 1.1 MB at
# 7,572 rows; 20 MB is a budget many times bigger than any real one.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class YnabImport(BaseTeamModel):
    STATUS_UPLOADED = "uploaded"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_UPLOADED, "Uploaded"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UPLOADED)

    register_csv = models.TextField(blank=True, help_text="The uploaded register export, cleared once applied.")
    plan_csv = models.TextField(blank=True, help_text="The uploaded plan export, cleared once applied.")

    choices = models.JSONField(
        default=dict,
        blank=True,
        help_text="The wizard's answers: account types, income mapping, which savings categories are goals.",
    )
    result = models.JSONField(
        default=dict,
        blank=True,
        help_text="What was written, and how the reconciliation came out.",
    )
    error = models.TextField(blank=True)
    task_id = models.CharField(max_length=255, blank=True, help_text="The Celery task running this import.")
    progress = models.PositiveSmallIntegerField(default=0, help_text="Percent complete, for the wizard's apply screen.")
    step = models.CharField(max_length=100, blank=True, help_text="What the import is doing right now.")

    started_at = models.DateTimeField(null=True, blank=True, help_text="When the worker picked this import up.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ynab_imports",
    )
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "YNAB import"
        verbose_name_plural = "YNAB imports"

    def __str__(self):
        return f"YNAB import for {self.team} ({self.status})"

    @property
    def is_finished(self) -> bool:
        return self.status in (self.STATUS_DONE, self.STATUS_FAILED)

    @property
    def elapsed_seconds(self) -> float | None:
        """How long the worker has been at it, or took."""
        if self.started_at is None:
            return None
        end = self.finished_at or timezone.now()
        return max(0.0, (end - self.started_at).total_seconds())

    @property
    def eta_seconds(self) -> int | None:
        """
        A guess at what is left, from what the run has managed so far.

        Deliberately silent below a tenth of the way in: the opening phase creates
        accounts and payees, which is nothing like the per-transaction rate that
        dominates the rest, so an estimate made from it would be confidently wrong.
        """
        elapsed = self.elapsed_seconds
        if self.is_finished or elapsed is None or self.progress < 10:
            return None
        return max(0, int(round(elapsed * (100 - self.progress) / self.progress)))

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "step": self.step,
            "error": self.error,
            "result": self.result,
            # The wizard shows a bar for a job it cannot see, so it is told how long
            # this has been going and what is left rather than left to guess.
            "started": self.started_at is not None,
            "elapsed_seconds": self.elapsed_seconds,
            "eta_seconds": self.eta_seconds,
        }
