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
