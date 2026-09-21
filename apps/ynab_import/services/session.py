"""
Re-reading a stored export.

The wizard walks several screens and then hands the work to a Celery worker, and
every one of those steps needs the parsed export. Parsing it is cheap (a quarter of
a second for the 10,500-row sample) and pure, so it is redone from the stored text
rather than cached -- one source of truth, no cache to invalidate, and a worker in
another container reads exactly the bytes the browser sent.
"""

from .analyse import Analysis, analyse
from .parse import parse_plan, parse_register


def analyse_record(record) -> Analysis:
    """The analysis for one stored upload."""
    return analyse(
        parse_register(record.register_csv.encode("utf-8")),
        parse_plan(record.plan_csv.encode("utf-8")),
    )
