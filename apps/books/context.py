"""
The current set of books, as a context variable.

The same shape as `apps.teams.context`: middleware sets it for a request under a
book URL, and code running outside a request (a Celery task, a management
command) sets it with the `current_book` context manager -- and must unset it,
or the next task on the same worker inherits it.
"""

import contextlib
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

import sentry_sdk

from apps.teams.context import _unwrap_lazy

if TYPE_CHECKING:
    from apps.books.models import Book

_context: ContextVar["Book | None"] = ContextVar("book", default=None)


class EmptyBookContextException(Exception):
    pass


def get_current_book() -> "Book | None":
    """The book set in the current thread/context by `set_current_book`, or None."""
    with contextlib.suppress(LookupError):
        return _context.get()
    return None


def _tag(book):
    if book and hasattr(book, "slug"):
        sentry_sdk.get_current_scope().set_tag("book", book.slug)
    else:
        sentry_sdk.get_current_scope().remove_tag("book")


def set_current_book(book: "Book | None") -> Token:
    book = _unwrap_lazy(book)
    token = _context.set(book)
    _tag(book)
    return token


def unset_current_book(token: Token | None = None):
    """Reset to the value before `token` was set, or to None without a token."""
    if token is None:
        _context.set(None)
    else:
        try:
            _context.reset(token)
        except ValueError:
            # Under ASGI, middleware's `process_view` and `__call__` can run in
            # different contexts, and a token only resets the context that made
            # it. Clearing is what the reset would have achieved there.
            _context.set(None)
    _tag(get_current_book())


@contextmanager
def current_book(book: "Book | None"):
    """Set the book for a block of code outside a request."""
    token = set_current_book(book)
    try:
        yield
    finally:
        unset_current_book(token)
