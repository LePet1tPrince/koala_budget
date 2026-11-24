"""
The apply step, off the request. Modelled directly on
`apps.ynab_import.tasks.run_ynab_import` -- see that module for the reasoning
behind running this in Celery and reporting progress the way `progress.py`
does.

The one structural difference from the YNAB task: the safety export
(`apply.build_safety_archive`) is taken and saved **before**
`apply.apply_archive`'s transaction opens, not inside it -- see
`apply.build_safety_archive`'s own docstring for why a rollback must not be
able to take the safety copy down with it.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.utils.progress import reporter

from .models import DataImport
from .services import apply, read
from .services.progress import ProgressChannel
from .services.schema import DocumentError

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_data_import(self, import_id: int):
    record = DataImport.objects.select_related("book", "created_by").filter(id=import_id).first()
    if record is None:
        logger.warning("Data import %s no longer exists", import_id)
        return None
    if record.status != DataImport.STATUS_UPLOADED:
        # Already run, or already running -- a second worker picking up the
        # same row would wipe and rewrite the book twice.
        return record.as_dict()

    channel = ProgressChannel(record.id)
    report = reporter(self, channel)
    record.start("Reading your export")

    def fail(message: str):
        channel.close()
        return record.fail(message)

    try:
        report(2, "Reading your export")
        read.read_archive(bytes(record.archive))  # validates before anything else runs
    except DocumentError as error:
        return fail(str(error))
    except Exception as error:  # noqa: BLE001 - the wizard must say something, whatever broke
        logger.exception("Data import %s failed while reading the archive", import_id)
        return fail(f"The import could not be completed: {error}")

    try:
        report(8, "Backing up this set of books")
        safety_archive = apply.build_safety_archive(record.book)
        safety_taken_at = timezone.now()
        # A plain save, outside any transaction `apply_archive` will open --
        # this has to commit on its own so it survives that transaction
        # rolling back. See apply.build_safety_archive's docstring. The
        # in-memory `record` is updated too, or the unconditional
        # `record.save()` at the end of a successful run -- which writes
        # every field -- would overwrite this back to its stale, empty value.
        DataImport.objects.filter(id=record.id).update(
            safety_archive=safety_archive,
            safety_archive_created_at=safety_taken_at,
            updated_at=safety_taken_at,
        )
        record.safety_archive = safety_archive
        record.safety_archive_created_at = safety_taken_at
    except Exception as error:  # noqa: BLE001 - the wizard must say something, whatever broke
        logger.exception("Data import %s failed while taking the safety copy", import_id)
        return fail(f"The import could not be completed: {error}")

    try:
        result = apply.apply_archive(record.book, bytes(record.archive), user=record.created_by, on_progress=report)
    except (DocumentError, apply.ApplyError) as error:
        return fail(str(error))
    except Exception as error:  # noqa: BLE001 - the wizard must say something, whatever broke
        logger.exception("Data import %s failed while writing", import_id)
        return fail(f"The import could not be completed: {error}")

    channel.close()
    # The archive is in the ledger now. The safety copy is deliberately kept:
    # it has its own retention window.
    record.finish(result.as_dict(), archive=b"")
    _finish_onboarding(record)

    # AuditEvent.DATA_WIPED and DATA_IMPORTED are already logged inside
    # apply_archive's own transaction (§4.3: they must roll back together
    # with a failed import, not be logged separately afterwards).
    return record.as_dict()


def _finish_onboarding(record: DataImport):
    """
    A loaded export is a set of books that was already set up somewhere else,
    so the walkthrough has nothing left to ask -- "Load an export" is one of the
    three ways to start a new book. Leaves a book already past onboarding alone.
    """
    if not getattr(settings, "ONBOARDING_ENABLED", False):
        return

    from apps.onboarding.models import OnboardingState

    state, _created = OnboardingState.objects.get_or_create(book=record.book)
    if state.is_finished:
        return
    state.complete()
    state.finish_tasks()
    state.save()
