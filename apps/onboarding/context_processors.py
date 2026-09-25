"""
Tells every app page whether the guided task rail belongs on it.

Deliberately cheap: one query for the onboarding row, and nothing else. The rail
fetches its own task state from `api/tasks/` once it mounts, so the gate
computation -- several existence queries -- never runs on a page that is not
going to show a rail.
"""

from django.urls import reverse

from .models import OnboardingState


def onboarding_rail(request):
    # The rail walks one set of books, so it belongs only on pages inside one: the
    # URL's book, not the nav book a team-level page falls back to.
    book = getattr(request, "book", None)
    if not book or not request.user.is_authenticated or not getattr(request, "team_membership", None):
        return {}

    state = OnboardingState.objects.filter(book=book).only("phase").first()
    if state is None or not state.shows_tasks:
        return {}

    return {
        "onboarding_rail": {
            "tasksUrl": reverse("onboarding:api_tasks", args=book.url_args),
            "taskUrl": reverse("onboarding:api_task", args=book.url_args),
            "openingBalancesUrl": reverse("onboarding:api_opening_balances", args=book.url_args),
            "path": request.path,
        }
    }
