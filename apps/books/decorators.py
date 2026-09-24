"""
Access checks for views under `/a/{team}/{book}/`.

A user may open a book iff they are a member of its team, with the role they
have on the team. The team comes from the URL and the book is looked up inside
it (`BooksMiddleware`), so the team decorators already enforce membership; these
add only "404 if the URL names no book".
"""

from functools import wraps

from django.http import Http404

from apps.teams.decorators import login_and_team_required, team_admin_required


def _require_book(view_func):
    @wraps(view_func)
    def _inner(request, *args, **kwargs):
        if not getattr(request, "book", None):
            raise Http404
        return view_func(request, *args, **kwargs)

    return _inner


def login_and_book_required(view_func):
    return login_and_team_required(_require_book(view_func))


def book_admin_required(view_func):
    return team_admin_required(_require_book(view_func))
