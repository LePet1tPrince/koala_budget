from django.utils.functional import SimpleLazyObject

from .context import set_current_book, unset_current_book
from .helpers import get_book_for_request, last_book_for_team, remember_book


def _get_book(request, view_kwargs):
    if not hasattr(request, "_cached_book"):
        book = get_book_for_request(request, view_kwargs)
        if book:
            remember_book(request, book)
        request._cached_book = book
    return request._cached_book


def _get_default_book(request, view_kwargs):
    if not hasattr(request, "_cached_default_book"):
        book = _get_book(request, view_kwargs)
        if not book:
            # `default_team` is the URL's team on a team-level page and the last
            # team used on an account page, so this is always a book of the team
            # the navigation is showing.
            book = last_book_for_team(request, getattr(request, "default_team", None))
        request._cached_default_book = book
    return request._cached_default_book


class BooksMiddleware:
    """
    Sets `request.book` and `request.default_book`. Must follow `TeamsMiddleware`:
    a book is looked up inside `request.team`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        finally:
            unset_current_book(getattr(request, "_book_context_token", None))

    def process_view(self, request, view_func, view_args, view_kwargs):
        # The book named by `book_slug` within `request.team`; None on team-level
        # and account pages, and for a slug that isn't one of this team's books
        # (which the book decorators and permissions answer with a 404).
        request.book = SimpleLazyObject(lambda: _get_book(request, view_kwargs))

        # `request.book`, or on a page without one, the book last opened in the
        # nav team. For the chrome only -- see `get_nav_book`.
        request.default_book = SimpleLazyObject(lambda: _get_default_book(request, view_kwargs))

        request._book_context_token = set_current_book(request.book)
