"""
Tells every app page whether the guided task rail belongs on it.

Deliberately cheap: one query for the onboarding row, and nothing else (see
`services.rail`, shared with the nav-state API).
"""

from django.urls import reverse

from .services.rail import shows_task_rail


def onboarding_rail(request):
    # The rail walks one set of books, so it belongs only on pages inside one: the
    # URL's book, not the nav book a team-level page falls back to.
    book = getattr(request, "book", None)
    if not book or not request.user.is_authenticated or not getattr(request, "team_membership", None):
        return {}

    if not shows_task_rail(book):
        return {}

    return {
        "onboarding_rail": {
            "tasksUrl": reverse("onboarding:api_tasks", args=book.url_args),
            "taskUrl": reverse("onboarding:api_task", args=book.url_args),
            "openingBalancesUrl": reverse("onboarding:api_opening_balances", args=book.url_args),
            "path": request.path,
        }
    }
