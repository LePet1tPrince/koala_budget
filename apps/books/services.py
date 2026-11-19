"""
What happens when a set of books is created, archived, restored, deleted or has its
settings changed -- the write and its audit event -- shared by the server-rendered
views (`views.py`) and the API (`api_views.py`), so the two cannot drift.

Who may do it and the type-the-name confirmation are the caller's: a view checks
them with its decorator and `ConfirmNameForm`, the API with its permission class
and `BookConfirmSerializer`, both through `validation.clean_confirm_name`.
"""

from datetime import date

from django.db import transaction
from django.utils.translation import gettext as _

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event

from .helpers import create_book
from .models import Book

SETTINGS_FIELDS = ("budget_future_income", "report_timeframe", "locked_through")


class LastOpenBookError(Exception):
    """Archiving or deleting this book would leave its team without an open one."""


def open_books(team):
    return Book.objects.filter(team=team, is_archived=False)


def has_other_open_book(book) -> bool:
    """Whether the team keeps an open book if `book` goes: neither archive nor delete may leave it with none."""
    return open_books(book.team_id).exclude(pk=book.pk).exists()


def create_team_book(request, team, name: str, start: str) -> Book:
    with transaction.atomic():
        book = create_book(team, name)
    log_event(
        AuditEvent.BOOK_CREATED, request=request, team=team, book=book, metadata={"name": book.name, "start": start}
    )
    return book


def ensure_can_archive(book):
    if not has_other_open_book(book):
        raise LastOpenBookError(_("This is the team's only set of books, so it can't be archived."))


def ensure_can_delete(book):
    if not has_other_open_book(book):
        raise LastOpenBookError(_("This is the team's only set of books, so it can't be deleted."))


def archive_book(request, book):
    """Archive `book` (the caller has checked `ensure_can_archive` and the confirmation)."""
    book.archive()
    log_event(AuditEvent.BOOK_ARCHIVED, request=request, team=book.team, book=book)


def restore_book(request, book):
    book.restore()
    log_event(AuditEvent.BOOK_RESTORED, request=request, team=book.team, book=book)


def delete_book(request, book) -> str:
    """
    Delete `book` and every row in it (the caller has checked `ensure_can_delete`
    and the confirmation). Returns the name it had.
    """
    from apps.portability.services.wipe import wipe_book

    name = book.name
    team = book.team
    with transaction.atomic():
        wipe_book(book)
        # Audit rows outlive the book (their FK is SET_NULL); the event says which one it was.
        log_event(AuditEvent.BOOK_DELETED, request=request, team=team, book=None, metadata={"name": name})
        book.delete()
    return name


def settings_snapshot(book) -> dict:
    """The audited settings as they are now; read *before* a form or serializer copies new values on."""
    return {field: getattr(book, field) for field in SETTINGS_FIELDS}


def record_settings_change(request, book, before: dict):
    """Audit what a settings save changed, against `settings_snapshot` taken before it."""
    changed = {}
    if before["budget_future_income"] != book.budget_future_income:
        changed["budget_future_income"] = book.budget_future_income
    if before["report_timeframe"] != book.report_timeframe:
        changed["report_timeframe"] = book.report_timeframe
    lock_before = before["locked_through"]
    if lock_before != book.locked_through:
        # Both ends, so the audit trail says which period was closed or reopened.
        changed["locked_through"] = book.locked_through.isoformat() if book.locked_through else None
        changed["locked_through_before"] = lock_before.isoformat() if lock_before else None
    if changed:
        log_event(AuditEvent.BOOK_SETTINGS_CHANGED, request=request, team=book.team, book=book, metadata=changed)


def unassigned_both_ways(book):
    """This month's Unassigned with the future-income setting as it is, and flipped."""
    from apps.budget.unassigned import compute_unassigned

    month = date.today().replace(day=1)
    current = compute_unassigned(book, month)
    flipped = compute_unassigned(book, month, future_income=not book.budget_future_income)
    return current, flipped
