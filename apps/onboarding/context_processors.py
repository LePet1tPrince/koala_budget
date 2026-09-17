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
    team = getattr(request, "team", None)
    if not team or not request.user.is_authenticated:
        return {}

    state = OnboardingState.objects.filter(team=team).only("phase").first()
    if state is None or not state.shows_tasks:
        return {}

    return {
        "onboarding_rail": {
            "tasksUrl": reverse("onboarding:api_tasks", args=[team.slug]),
            "taskUrl": reverse("onboarding:api_task", args=[team.slug]),
            "openingBalancesUrl": reverse("onboarding:api_opening_balances", args=[team.slug]),
            "path": request.path,
        }
    }
