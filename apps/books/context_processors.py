from django.http import Http404

from .helpers import get_nav_book
from .models import Book


def book(request):
    """
    `book` is the URL's book (None on team-level and account pages) and is what
    page content uses. `nav_book` is what the chrome uses -- see `get_nav_book` --
    and `nav_books` are the open books of the nav team, for the switcher.
    """
    try:
        nav_book = get_nav_book(request)
    except Http404:
        # Evaluating the lazy book can raise; let the view's own 404 surface
        # instead of turning it into a template-rendering 500.
        return {"book": None, "nav_book": None, "nav_books": []}

    nav_books = []
    if nav_book is not None and getattr(request, "user", None) and request.user.is_authenticated:
        nav_books = list(Book.objects.filter(team_id=nav_book.team_id, is_archived=False))
    return {
        "book": getattr(request, "book", None),
        "nav_book": nav_book,
        "nav_books": nav_books,
    }
