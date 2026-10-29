"""
Saying how far a long import has got, from inside the transaction doing it.

An import of any size runs as one `transaction.atomic` block, so a row it
updates is invisible to every other connection until the whole thing commits --
which is exactly when the progress stops being interesting. A progress bar fed
from that row sits at zero for the entire import and then jumps to the end,
which is worse than no bar: it tells the user their import is doing nothing.

So progress goes out on two channels that fail independently:

* the Celery result backend, which is Redis rather than the database and so is
  not inside the transaction at all;
* a **second database connection**, opened here and therefore outside the
  import's transaction, whose updates commit one at a time.

The second is what makes the row's `progress` mean what it says -- including for
a user who reloads the page mid-import, since a Celery result expires and the
row does not. Neither channel is allowed to fail the import: an import that
worked but could not say so is a far better outcome than the reverse.

Shared by `apps.ynab_import` and `apps.portability`, which had byte-identical
copies of this apart from a log message. The mechanism here (a connection
outside the caller's transaction, a lock timeout, raw SQL) is subtle enough
that two copies meant a fix to one would silently miss the other.
"""

import contextlib
import logging

from celery.result import AsyncResult
from celery_progress.backend import Progress
from django.db import DEFAULT_DB_ALIAS, connections
from django.utils import timezone

logger = logging.getLogger(__name__)


class ProgressChannel:
    """
    A connection of its own, for writing progress while a transaction is open.

    `model` is the import-record model to update; it must carry `progress`,
    `step` and `updated_at` fields. `label` names the import in the one log
    line this can emit, so a warning says which feature could not report.

    Opened lazily so an import in an environment where a second connection
    cannot be had (a connection cap, a pooler) still runs -- it just reports
    through Celery alone.
    """

    #: Longest `step` text the column will take.
    STEP_MAX_LENGTH = 100

    #: Short enough that a blocked update fails rather than stalling the
    #: import; see `_set_lock_timeout`.
    LOCK_TIMEOUT = "2s"

    def __init__(self, import_id: int, *, model, label: str = "import"):
        self.import_id = import_id
        self.model = model
        self.label = label
        self._connection = None
        self._broken = False

    def report(self, percent: int, step: str):
        if self._broken:
            return
        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute(*self._statement(percent, step))
            # The connection is its own transaction, so this update is visible
            # to the polling web process immediately rather than at the end.
            connection.commit()
        except Exception:  # noqa: BLE001 - progress is a nicety; the import is not
            logger.warning("Could not record %s progress", self.label, exc_info=True)
            self._broken = True
            self.close()

    def close(self):
        if self._connection is not None:
            # Nothing useful to do about a close that fails, and the import is over.
            with contextlib.suppress(Exception):
                self._connection.close()
            self._connection = None

    def _ensure_connection(self):
        if self._connection is None:
            connection = connections.create_connection(DEFAULT_DB_ALIAS)
            connection.set_autocommit(False)
            self._set_lock_timeout(connection)
            self._connection = connection
        return self._connection

    @classmethod
    def _set_lock_timeout(cls, connection):
        """
        Never let saying-how-it-is-going hold up the thing it is reporting on.

        This connection writes to a row the import's own transaction could in
        principle be holding, and a second connection waiting on that lock
        would wait until the import finished -- deadlocking the import against
        its own progress bar. A short timeout turns that into a failed update,
        which the caller already treats as "report through Celery alone".
        """
        with contextlib.suppress(Exception):  # not every backend has it; none of them need it
            with connection.cursor() as cursor:
                cursor.execute(f"SET lock_timeout = '{cls.LOCK_TIMEOUT}'")
            connection.commit()

    def _statement(self, percent: int, step: str):
        """
        Written as SQL, because the ORM can only reach connections the handler
        knows about and this one is deliberately not among them. Table and
        column names come from the model, so a rename cannot leave this behind.
        """
        meta = self.model._meta
        column = {field.name: field.column for field in meta.fields}
        sql = (
            f'UPDATE "{meta.db_table}" '
            f'SET "{column["progress"]}" = %s, "{column["step"]}" = %s, "{column["updated_at"]}" = %s '
            f'WHERE "{column["id"]}" = %s'
        )
        return sql, [
            max(0, min(100, int(percent))),
            step[: self.STEP_MAX_LENGTH],
            timezone.now(),
            self.import_id,
        ]


# ---------------------------------------------------------------------------
# Reading it back: the status endpoint both import wizards poll
# ---------------------------------------------------------------------------

# The bar never shows a full sweep while work is still going on: 100% is reserved
# for a row that says so.
NEARLY_DONE = 99

# How long a task Celery calls finished may leave its row untouched before it is
# treated as a worker that died rather than one that is a moment behind.
DEAD_WORKER_GRACE_SECONDS = 20

WORKER_DIED_ERROR = (
    "The import stopped before it finished. Nothing was written -- it is applied in one go, so a "
    "run that does not reach the end leaves your books exactly as they were. Check the worker log, "
    "then start again."
)


def live_progress(record) -> dict | None:
    """What Celery makes of the task, or None when there is no result backend to ask."""
    try:
        return Progress(AsyncResult(record.task_id)).get_info()
    except Exception:  # noqa: BLE001 - a missing result backend must not break the page
        logger.debug("No live progress for %s %s", type(record).__name__, record.id, exc_info=True)
        return None


def worker_is_gone(record) -> bool:
    """
    Whether a task Celery calls finished has stopped writing to its row.

    The grace period is what separates a dead worker from the ordinary race: the
    task returns, and a moment later the same worker commits the row. Only silence
    that outlasts the grace period is a death.
    """
    last_seen = record.updated_at or record.started_at
    if last_seen is None:
        return True
    return (timezone.now() - last_seen).total_seconds() > DEAD_WORKER_GRACE_SECONDS


def status_payload(record) -> dict:
    """
    Where an import has got to, for the wizard's status poll.

    `record` is a `YnabImport` or a `DataImport`: a row with `as_dict()`,
    `is_finished`, `task_id`, `status`/`error`/`finished_at` and `STATUS_FAILED`.

    The row is authoritative -- a reloaded page must show a finished import as
    finished -- and Celery is consulted only for progress the row has not caught up
    with yet, since the two are written from the same worker microseconds apart.

    The one thing Celery is trusted for outright is *death*. A worker that is
    killed (an out-of-memory container, a deploy mid-import) never reaches the code
    that marks the row failed, so the row says "running" forever. Without this the
    wizard sits at whatever it last saw, waiting for a worker that is not coming.
    """
    payload = record.as_dict()
    if record.is_finished or not record.task_id:
        return payload

    live = live_progress(record)
    if live is None:
        return payload

    if live["complete"]:
        # `celery_progress` reports 100% for a finished task whether it succeeded or
        # failed, so that number must never reach the bar while the row still says
        # running -- that is the full-bar-forever the user would otherwise stare at.
        if worker_is_gone(record):
            record.status = record.STATUS_FAILED
            record.error = WORKER_DIED_ERROR
            record.finished_at = timezone.now()
            record.save(update_fields=["status", "error", "finished_at", "updated_at"])
            return record.as_dict()
        # Still within the moment between the task returning and the row being
        # written: report near-complete rather than complete, and let the next poll
        # see the row itself.
        payload["progress"] = max(payload["progress"], NEARLY_DONE)
        return payload

    progress = live.get("progress") or {}
    percent = int(progress.get("percent") or 0)
    payload["progress"] = min(NEARLY_DONE, max(payload["progress"], percent))
    payload["step"] = progress.get("description") or payload["step"]
    payload["started"] = payload["started"] or not progress.get("pending")
    return payload
