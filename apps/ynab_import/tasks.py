"""
The apply step, off the request.

6,600 entries and 13,300 lines is not work to do while a browser waits, so the
import runs in Celery and the wizard polls. Progress is reported through
`celery_progress`, which keeps it in the result backend rather than the database:
the write itself is one transaction, so a progress row written inside it would not
be visible to anyone until the import had already finished.
"""

import logging

from celery import shared_task
from celery_progress.backend import ProgressRecorder
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event

from .models import YnabImport
from .services.apply import ApplyError, apply_plan
from .services.build import BuildError, build, parse_choices
from .services.progress import ProgressChannel
from .services.reconcile import reconcile
from .services.session import analyse_record

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_ynab_import(self, import_id: int):
    record = YnabImport.objects.select_related("team", "created_by").filter(id=import_id).first()
    if record is None:
        logger.warning("YNAB import %s no longer exists", import_id)
        return None
    if record.status != YnabImport.STATUS_UPLOADED:
        # Already run, or already running. A second worker picking the same import up
        # would write the whole history twice.
        return record.as_dict()

    recorder = ProgressRecorder(self)
    channel = ProgressChannel(record.id)

    record.status = YnabImport.STATUS_RUNNING
    record.progress = 0
    record.step = "Reading your export"
    record.started_at = timezone.now()
    record.save(update_fields=["status", "progress", "step", "started_at", "updated_at"])

    def report(percent: int, step: str):
        """
        Two channels, because each fails in a way the other does not.

        The result backend is Redis and so is not inside the import's transaction;
        the second connection is the database, so it still works where results are
        turned off. Neither may fail the import: losing the progress bar is a far
        better outcome than losing the books.
        """
        try:
            recorder.set_progress(percent, 100, description=step)
        except Exception:  # noqa: BLE001 - progress is a nicety; the import is not
            logger.debug("Could not report YNAB import progress to the result backend", exc_info=True)
        channel.report(percent, step)

    try:
        report(2, "Reading your export")
        analysis = analyse_record(record)
        choices = parse_choices(analysis, record.choices)
        plan = build(analysis, choices)
        result = apply_plan(record.team, plan, user=record.created_by, on_progress=report)
        checks = reconcile(analysis, plan)
    except (ApplyError, BuildError) as error:
        channel.close()
        record.status = YnabImport.STATUS_FAILED
        record.error = str(error)
        record.finished_at = timezone.now()
        record.save(update_fields=["status", "error", "finished_at", "updated_at"])
        return record.as_dict()
    except Exception as error:  # noqa: BLE001 - the wizard must say something, whatever broke
        channel.close()
        logger.exception("YNAB import %s failed", import_id)
        record.status = YnabImport.STATUS_FAILED
        record.error = f"The import could not be completed: {error}"
        record.finished_at = timezone.now()
        record.save(update_fields=["status", "error", "finished_at", "updated_at"])
        return record.as_dict()

    channel.close()

    with transaction.atomic():
        record.status = YnabImport.STATUS_DONE
        record.progress = 100
        record.step = "Done"
        record.finished_at = timezone.now()
        record.result = {
            "created": result.as_dict(),
            "summary": plan.stats,
            "notes": plan.notes,
            "reconciliation": checks.as_dict(),
        }
        # The export is in the ledger now. Keeping a second copy of someone's entire
        # financial history in a staging table buys nothing.
        record.register_csv = ""
        record.plan_csv = ""
        record.save()

    _finish_onboarding(record)

    log_event(
        AuditEvent.YNAB_IMPORT,
        user=record.created_by,
        team=record.team,
        metadata={
            "created": result.as_dict(),
            "first_date": plan.stats.get("first_date"),
            "last_date": plan.stats.get("last_date"),
            "reconciliation_passed": checks.passed,
            # Every inference the user accepted, so a figure that later looks wrong
            # can be traced back to the decision that produced it.
            "choices": record.choices,
        },
    )
    return record.as_dict()


# Guided tasks a YNAB import has plainly done. `report` and `net_worth` are left
# open on purpose: they are "go and look at this", and looking at five years of
# your own spending laid out is the whole payoff of having migrated.
SATISFIED_TASKS = ("import", "categorize", "budget")


def _finish_onboarding(record: YnabImport):
    """
    An imported budget answers the questionnaire better than the user could.

    So the takeover is finished rather than waited for: the phase moves straight to
    the guided tasks, with the ones the import has evidently done already ticked. A
    team that has been through onboarding already is left alone.
    """
    if not getattr(settings, "ONBOARDING_ENABLED", False):
        return

    from apps.onboarding.models import OnboardingState

    state, _created = OnboardingState.objects.get_or_create(team=record.team)
    if state.is_finished:
        return

    state.complete()
    for slug in SATISFIED_TASKS:
        state.mark_task(slug)
    state.save()

    log_event(
        AuditEvent.ONBOARDING_COMPLETED,
        user=record.created_by,
        team=record.team,
        metadata={"via": "ynab_import", "accounts": record.result.get("created", {}).get("accounts")},
    )
