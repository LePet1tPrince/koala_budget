from datetime import date

from django.urls import reverse
from django.utils.functional import SimpleLazyObject

from apps.teams.helpers import get_nav_team

from .unassigned import OVER_ASSIGNED_LABEL, UNASSIGNED_LABEL, compute_unassigned, pill_context


def unassigned_pill(request):
    """
    The Unassigned figure for the sidebar pill on every app page.

    It follows the nav team (like the Inbox badge) so the pill stays put on the
    account pages, and it is always the current month: the pill answers "how much
    has no job right now". The figure is lazy, so a page that never renders the
    pill (marketing pages, auth pages) never pays for the calculation.
    """
    team = get_nav_team(request)
    if not team or not request.user.is_authenticated:
        return {}
    # `default_team` is membership-checked; a URL team only is once the membership exists.
    if getattr(request, "team", None) and not getattr(request, "team_membership", None):
        return {}
    return {
        "unassigned_pill": SimpleLazyObject(lambda: pill_context(compute_unassigned(team, date.today()))),
        "unassigned_url": reverse("budget:api_unassigned", args=[team.slug]),
        "unassigned_labels": {"unassigned": UNASSIGNED_LABEL, "over_assigned": OVER_ASSIGNED_LABEL},
    }
