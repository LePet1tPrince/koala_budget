from rest_framework import permissions, status
from rest_framework.exceptions import APIException, NotFound

from apps.teams.permissions import _request_allowed_for_team, _view_for_members_edit_for_admins


class BooksReadOnly(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "subscription_required"


def assert_book_writable(request) -> None:
    """
    The DRF half of the subscription gate (`apps.subscriptions.middleware`), for a
    request that authenticated inside DRF: the middleware only sees session users.
    """
    from apps.subscriptions.entitlement import is_entitled
    from apps.subscriptions.middleware import read_only_message

    if request.method not in permissions.SAFE_METHODS and not is_entitled(request.team):
        raise BooksReadOnly(read_only_message(request))


def _request_allowed_for_book(request) -> bool:
    if not _request_allowed_for_team(request):
        return False
    if not getattr(request, "book", None):
        # A member asking for a book their team doesn't have: a 404, as a missing
        # book is everywhere else, not a 403 that says the URL means something.
        raise NotFound
    assert_book_writable(request)
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


class BookAdminWritePermissions(BookAccessPermissions):
    """
    For function views that write without an object to check: members read,
    only admins write -- the same rule `BookModelAccessPermissions` applies to
    an existing row, for an endpoint that creates one.
    """

    def has_permission(self, request, view):
        return super().has_permission(request, view) and _view_for_members_edit_for_admins(request, request.team)
