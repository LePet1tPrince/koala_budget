"""
One row per attempt to import a YNAB export.

The row exists for three reasons, in order of how much they cost to do without:

* the apply step runs in Celery (6,600 entries is not request work), and a worker
  cannot read a file out of the request that started it;
* the wizard walks several screens before applying, and re-uploading a 1 MB CSV at
  every step to keep the server stateless is a worse trade than storing it once;
* an import is a large, one-way change to a set of books, and what was imported
  should be answerable afterwards.

The exports are held as text rather than files so a worker in another container
reads the same bytes the browser sent, with no shared volume or object store to
configure. They are cleared once the import finishes -- keeping someone's entire
financial history in a staging table after it has been imported into the ledger
buys nothing.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.books.models import BaseBookModel
from apps.utils.models import ImportJob

# Refuse an upload larger than this. The sample export's register is 1.1 MB at
# 7,572 rows; 20 MB is a budget many times bigger than any real one.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# How long a finished import stays the answer to "what happened?" when someone
# opens the import page again. Long enough to cover closing the laptop and coming
# back tomorrow; short enough that an import from last month does not greet a user
# who came looking for something else.
RESUME_WINDOW = timedelta(hours=24)


class YnabImportQuerySet(models.QuerySet):
    def resumable(self, book, now=None):
        """
        The import worth showing when this book's import page is opened.

        Two cases, and they are the whole point of the row outliving the browser:

        * one still going -- the user closed the tab, or never had it open, since
          the work is in a worker and does not need them;
        * one that finished or failed recently -- so coming back gets the result,
          or the reason, rather than a page that behaves as though it never
          happened.

        An upload that was never applied is neither: nothing is running and nothing
        was written, so the wizard should start where it always does.
        """
        now = now or timezone.now()
        in_flight = Q(status=self.model.STATUS_RUNNING) | Q(status=self.model.STATUS_UPLOADED, task_id__gt="")
        recently_finished = Q(
            status__in=(self.model.STATUS_DONE, self.model.STATUS_FAILED),
            finished_at__gte=now - RESUME_WINDOW,
        )
        return self.filter(book=book).filter(in_flight | recently_finished).order_by("-created_at").first()


class YnabImport(BaseBookModel, ImportJob):
    objects = YnabImportQuerySet.as_manager()

    register_csv = models.TextField(blank=True, help_text="The uploaded register export, cleared once applied.")
    plan_csv = models.TextField(blank=True, help_text="The uploaded plan export, cleared once applied.")

    choices = models.JSONField(
        default=dict,
        blank=True,
        help_text="The wizard's answers: account types, income mapping, which savings categories are goals.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ynab_imports",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "YNAB import"
        verbose_name_plural = "YNAB imports"

    def __str__(self):
        return f"YNAB import for {self.book} ({self.status})"
