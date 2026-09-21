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
from celery_progress.backend import ProgressRecorder
from django.utils import timezone

from .models import DataImport
from .services import apply, read
from .services.progress import ProgressChannel
from .services.schema import DocumentError

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_data_import(self, import_id: int):
    record = DataImport.objects.select_related("team", "created_by").filter(id=import_id).first()
    if record is None:
        logger.warning("Data import %s no longer exists", import_id)
        return None
    if record.status != DataImport.STATUS_UPLOADED:
        # Already run, or already running -- a second worker picking up the
        # same row would wipe and rewrite the team twice.
        return record.as_dict()

    recorder = ProgressRecorder(self)
    channel = ProgressChannel(record.id)

    record.status = DataImport.STATUS_RUNNING
    record.progress = 0
    record.step = "Reading your export"
    record.started_at = timezone.now()
    record.save(update_fields=["status", "progress", "step", "started_at", "updated_at"])

    def report(percent: int, step: str):
        try:
            recorder.set_progress(percent, 100, description=step)
        except Exception:  # noqa: BLE001 - progress is a nicety; the import is not
            logger.debug("Could not report data import progress to the result backend", exc_info=True)
        channel.report(percent, step)

    def fail(message: str):
        channel.close()
        record.status = DataImport.STATUS_FAILED
        record.error = message
        record.finished_at = timezone.now()
        record.save(update_fields=["status", "error", "finished_at", "updated_at"])
        return record.as_dict()

    try:
        report(2, "Reading your export")
        read.read_archive(bytes(record.archive))  # validates before anything else runs
    except DocumentError as error:
        return fail(str(error))
    except Exception as error:  # noqa: BLE001 - the wizard must say something, whatever broke
        logger.exception("Data import %s failed while reading the archive", import_id)
        return fail(f"The import could not be completed: {error}")

    try:
        report(8, "Backing up this team's own books")
        safety_archive = apply.build_safety_archive(record.team)
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
        result = apply.apply_archive(record.team, bytes(record.archive), user=record.created_by, on_progress=report)
    except (DocumentError, apply.ApplyError) as error:
        return fail(str(error))
    except Exception as error:  # noqa: BLE001 - the wizard must say something, whatever broke
        logger.exception("Data import %s failed while writing", import_id)
        return fail(f"The import could not be completed: {error}")

    channel.close()

    record.status = DataImport.STATUS_DONE
    record.progress = 100
    record.step = "Done"
    record.finished_at = timezone.now()
    record.result = result.as_dict()
    # The archive is in the ledger now. Keeping a second copy of someone's
    # entire financial history in a staging table buys nothing -- the same
    # reasoning YnabImport clears its staged CSVs on. The safety copy is
    # deliberately NOT cleared here; it has its own retention window.
    record.archive = b""
    record.save()

    # AuditEvent.DATA_WIPED and DATA_IMPORTED are already logged inside
    # apply_archive's own transaction (§4.3: they must roll back together
    # with a failed import, not be logged separately afterwards).
    return record.as_dict()
