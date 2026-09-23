"""
Progress reporting for a data import, over `apps.utils.progress`.

The mechanism -- a second database connection so the row's `progress` is
readable while `apply_archive`'s transaction is still open -- is shared with
`apps.ynab_import`, which has the same problem. See that module for why it
works the way it does.

This stays a subclass rather than a re-export so the model is bound once here
rather than at every call site, and so a test patching this app's channel
cannot reach into the other app's.
"""

from apps.utils.progress import ProgressChannel as BaseProgressChannel

from ..models import DataImport


class ProgressChannel(BaseProgressChannel):
    def __init__(self, import_id: int):
        super().__init__(import_id, model=DataImport, label="data import")
