"""
One row per attempt to import a Koala Budget export into a book.

Modelled directly on `apps.ynab_import.models.YnabImport`, for the same three
reasons: the apply step runs in Celery (the destination gets wiped and
rebuilt in one transaction, not request work); the wizard walks a preview
screen before applying, and a worker in another container needs the same
bytes the browser uploaded; and an import is a large, one-way change to a
set of books, so what happened should be answerable afterwards.

This feature has no wizard *choices* to make (there is nothing to infer --
both ends are Koala Budget, per `docs/export-import-plan.md` §1), so the row
is simpler than `YnabImport`: no `choices` field, and no `can_import` guard,
because every import wipes the destination first regardless of what is
already there (§4.1). The one thing this row carries that `YnabImport` does
not is a safety copy of the book's *own* contents, taken automatically right
before the wipe (§4.4) -- the recovery path for "I imported the wrong file".
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.books.models import BaseBookModel
from apps.utils.models import ImportJob

# Refuse an upload larger than this. The format is CSV-of-strings, not a
# denser binary encoding, so a book many times the size of anything real
# today still fits comfortably under it.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# How long the pre-wipe safety copy is kept before a periodic task blanks it.
# Long enough to cover closing the laptop and coming back tomorrow, or the
# next day; short enough that someone's entire financial history is not
# sitting in a staging table indefinitely once the import it was insurance
# against has clearly gone fine (§4.4).
SAFETY_EXPORT_WINDOW = timedelta(days=7)


class DataImport(BaseBookModel, ImportJob):
    archive = models.BinaryField(
        default=b"", blank=True, help_text="The uploaded export (a zip), cleared once applied."
    )

    # Taken automatically right before the wipe (tasks.py) -- never uploaded by
    # the user. Blank until then, and blanked again once SAFETY_EXPORT_WINDOW
    # has passed.
    safety_archive = models.BinaryField(
        default=b"",
        blank=True,
        help_text="A copy of this team's own books, taken automatically right before the wipe.",
    )
    safety_archive_created_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_imports",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Data import"
        verbose_name_plural = "Data imports"

    def __str__(self):
        return f"Data import for {self.book} ({self.status})"

    @property
    def safety_archive_available(self) -> bool:
        if not self.safety_archive or self.safety_archive_created_at is None:
            return False
        return timezone.now() - self.safety_archive_created_at < SAFETY_EXPORT_WINDOW

    def as_dict(self) -> dict:
        return {**super().as_dict(), "safety_archive_available": self.safety_archive_available}
