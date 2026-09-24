from rest_framework import permissions
from rest_framework.exceptions import NotFound

from apps.teams.permissions import _request_allowed_for_team, _view_for_members_edit_for_admins


def _request_allowed_for_book(request) -> bool:
    if not _request_allowed_for_team(request):
        return False
    if not getattr(request, "book", None):
        # A member asking for a book their team doesn't have: a 404, as a missing
        # book is everywhere else, not a 403 that says the URL means something.
        raise NotFound
    return True


class BookAccessPermissions(permissions.BasePermission):
    """A member of the URL's team, on a URL that names one of its books."""

    def has_permission(self, request, view):
        return _request_allowed_for_book(request)


class BookModelAccessPermissions(permissions.BasePermission):
    """
    For viewsets over a `BaseBookModel`. Members read; admins edit.

    The object check compares the row's book with the URL's rather than trusting
    the queryset alone: a viewset whose `get_queryset` forgot its book filter
    must still refuse another book's row.
    """

    def has_permission(self, request, view):
        return _request_allowed_for_book(request)

    def has_object_permission(self, request, view, obj):
        if obj.book_id != request.book.id:
            return False
        return _view_for_members_edit_for_admins(request, request.team)
