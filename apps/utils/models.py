from django.db import models
from django.utils import timezone


class BaseModel(models.Model):
    """
    Base model that includes default created / updated timestamps.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False, help_text="Set to true to archive this item")
    archived_at = models.DateTimeField(null=True, blank=True, help_text="Date this item was archived")

    class Meta:
        abstract = True

    def archive(self):
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save()

    def restore(self):
        self.is_archived = False
        self.archived_at = None
        self.save()

    @property
    def is_active(self):
        return not self.is_archived


class ImportJob(models.Model):
    """
    A long import a Celery worker runs and a wizard polls (`apps.utils.progress`).

    Shared by `YnabImport` and `DataImport`, which add what they stage and who
    started them. Concrete subclasses also extend `BaseModel` (`updated_at`).
    """

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
    result = models.JSONField(
        default=dict, blank=True, help_text="What was written, and how the reconciliation came out."
    )
    error = models.TextField(blank=True)
    task_id = models.CharField(max_length=255, blank=True, help_text="The Celery task running this import.")
    progress = models.PositiveSmallIntegerField(default=0, help_text="Percent complete, for the wizard's apply screen.")
    step = models.CharField(max_length=100, blank=True, help_text="What the import is doing right now.")
    started_at = models.DateTimeField(null=True, blank=True, help_text="When the worker picked this import up.")
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

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
        A guess at what is left, from the rate so far. Silent below a tenth of
        the way in: the opening phase (a wipe, accounts and payees) runs nothing
        like the per-row rate that dominates the rest.
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
        }

    def start(self, step: str):
        self.status = self.STATUS_RUNNING
        self.progress = 0
        self.step = step
        self.started_at = timezone.now()
        self.save(update_fields=["status", "progress", "step", "started_at", "updated_at"])

    def fail(self, message: str) -> dict:
        self.status = self.STATUS_FAILED
        self.error = message
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "error", "finished_at", "updated_at"])
        return self.as_dict()

    def finish(self, result: dict, **cleared):
        """Done: record `result`, and blank the staged upload (`cleared`) -- it is in the ledger now."""
        self.status = self.STATUS_DONE
        self.progress = 100
        self.step = "Done"
        self.finished_at = timezone.now()
        self.result = result
        for name, value in cleared.items():
            setattr(self, name, value)
        self.save()
