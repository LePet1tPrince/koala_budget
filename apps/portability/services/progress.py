"""
Saying how far an import has got, from inside the transaction that is doing it.

Modelled directly on `apps.ynab_import.services.progress.ProgressChannel` --
same problem, same fix. `apply_archive` is one `transaction.atomic` block, so
a row it updates is invisible to every other connection until the whole thing
commits, which is exactly when the progress stops being interesting. Progress
goes out on two channels that fail independently: the Celery result backend
(Redis, not inside the transaction at all), and a **second database
connection**, opened here, whose updates commit one at a time regardless of
what the import's own transaction is doing.
"""

import contextlib
import logging

from django.db import DEFAULT_DB_ALIAS, connections
from django.utils import timezone

logger = logging.getLogger(__name__)


class ProgressChannel:
    def __init__(self, import_id: int):
        self.import_id = import_id
        self._connection = None
        self._broken = False

    def report(self, percent: int, step: str):
        if self._broken:
            return
        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute(*self._statement(percent, step))
            connection.commit()
        except Exception:  # noqa: BLE001 - progress is a nicety; the import is not
            logger.warning("Could not record data import progress", exc_info=True)
            self._broken = True
            self.close()

    def close(self):
        if self._connection is not None:
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

    @staticmethod
    def _set_lock_timeout(connection):
        with contextlib.suppress(Exception):  # not every backend has it; none of them need it
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '2s'")
            connection.commit()

    def _statement(self, percent: int, step: str):
        from apps.portability.models import DataImport

        meta = DataImport._meta
        column = {field.name: field.column for field in meta.fields}
        sql = (
            f'UPDATE "{meta.db_table}" '
            f'SET "{column["progress"]}" = %s, "{column["step"]}" = %s, "{column["updated_at"]}" = %s '
            f'WHERE "{column["id"]}" = %s'
        )
        return sql, [max(0, min(100, int(percent))), step[:100], timezone.now(), self.import_id]
