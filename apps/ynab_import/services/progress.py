"""
Progress reporting for a YNAB import, over `apps.utils.progress`.

The mechanism -- a second database connection so the row's `progress` is
readable while the import's transaction is still open -- is shared with
`apps.portability`. See `apps/utils/progress.py` for why it works the way it
does.

This stays a subclass rather than a re-export so the model is bound once here
rather than at every call site, and so a test patching this app's channel
cannot reach into the other app's.
"""

from apps.utils.progress import ProgressChannel as BaseProgressChannel

from ..models import YnabImport


class ProgressChannel(BaseProgressChannel):
    def __init__(self, import_id: int):
        super().__init__(import_id, model=YnabImport, label="YNAB import")
