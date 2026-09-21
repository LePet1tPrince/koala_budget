"""
One row per attempt to import a Koala Budget export into a team.

Modelled directly on `apps.ynab_import.models.YnabImport`, for the same three
reasons: the apply step runs in Celery (the destination gets wiped and
rebuilt in one transaction, not request work); the wizard walks a preview
screen before applying, and a worker in another container needs the same
bytes the browser uploaded; and an import is a large, one-way change to a
team's books, so what happened should be answerable afterwards.

This feature has no wizard *choices* to make (there is nothing to infer --
both ends are Koala Budget, per `docs/export-import-plan.md` §1), so the row
is simpler than `YnabImport`: no `choices` field, and no `can_import` guard,
because every import wipes the destination first regardless of what is
already there (§4.1). The one thing this row carries that `YnabImport` does
not is a safety copy of the team's *own* books, taken automatically right
before the wipe (§4.4) -- the recovery path for "I imported the wrong file".
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.teams.models import BaseTeamModel

# Refuse an upload larger than this. The format is CSV-of-strings, not a
# denser binary encoding, so a team many times the size of anything real
# today still fits comfortably under it.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# How long the pre-wipe safety copy is kept before a periodic task blanks it.
# Long enough to cover closing the laptop and coming back tomorrow, or the
# next day; short enough that someone's entire financial history is not
# sitting in a staging table indefinitely once the import it was insurance
# against has clearly gone fine (§4.4).
SAFETY_EXPORT_WINDOW = timedelta(days=7)


class DataImport(BaseTeamModel):
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

    archive = models.BinaryField(
        default=b"", blank=True, help_text="The uploaded export (a zip), cleared once applied."
    )

    # Taken automatically inside the apply transaction, immediately before the
    # wipe (services/apply.py) -- never uploaded by the user. Blank until
    # then, and blanked again once SAFETY_EXPORT_WINDOW has passed.
    safety_archive = models.BinaryField(
        default=b"",
        blank=True,
        help_text="A copy of this team's own books, taken automatically right before the wipe.",
    )
    safety_archive_created_at = models.DateTimeField(null=True, blank=True)

    result = models.JSONField(
        default=dict, blank=True, help_text="What was written, the wipe counts, and how the checks came out."
    )
    error = models.TextField(blank=True)
    task_id = models.CharField(max_length=255, blank=True, help_text="The Celery task running this import.")
    progress = models.PositiveSmallIntegerField(default=0, help_text="Percent complete, for the apply screen.")
    step = models.CharField(max_length=100, blank=True, help_text="What the import is doing right now.")

    started_at = models.DateTimeField(null=True, blank=True, help_text="When the worker picked this import up.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_imports",
    )
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Data import"
        verbose_name_plural = "Data imports"

    def __str__(self):
        return f"Data import for {self.team} ({self.status})"

    @property
    def is_finished(self) -> bool:
        return self.status in (self.STATUS_DONE, self.STATUS_FAILED)

    @property
    def safety_archive_available(self) -> bool:
        if not self.safety_archive or self.safety_archive_created_at is None:
            return False
        return timezone.now() - self.safety_archive_created_at < SAFETY_EXPORT_WINDOW

    @property
    def elapsed_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or timezone.now()
        return max(0.0, (end - self.started_at).total_seconds())

    @property
    def eta_seconds(self) -> int | None:
        """
        A guess at what is left, from what the run has managed so far.

        Silent below a tenth of the way in, same reasoning as the YNAB
        importer's: the wipe and the early inserts are nothing like the rate
        that dominates the rest of the run.
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
            "started": self.started_at is not None,
            "elapsed_seconds": self.elapsed_seconds,
            "eta_seconds": self.eta_seconds,
            "safety_archive_available": self.safety_archive_available,
        }
