"""
Tells every app page whether the guided task rail belongs on it.

Deliberately cheap: one query for the onboarding row, and nothing else (see
`services.rail`, shared with the nav-state API). The rail loads its tasks itself,
from `api/tasks/`, so all the page hands it is the book it belongs to.
"""

from .services.rail import shows_task_rail


def onboarding_rail(request):
    # The rail walks one set of books, so it belongs only on pages inside one: the
    # URL's book, not the nav book a team-level page falls back to.
    book = getattr(request, "book", None)
    if not book or not request.user.is_authenticated or not getattr(request, "team_membership", None):
        return {}

    if not shows_task_rail(book):
        return {}

    return {"onboarding_rail": {"book_base": book.base_url}}
