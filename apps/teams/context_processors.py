from django.http import Http404

from apps.teams.helpers import get_nav_team, get_open_invitations_for_user


def team(request):
    return {
        "team": getattr(request, "team", None),
        # `team` is None on non-team URLs, which is right for page content but
        # wrong for the chrome around it -- see `get_nav_team`. Navigation
        # templates use this instead so the sidebar survives Profile and
        # Change Password.
        "nav_team": get_nav_team(request),
    }


def user_teams(request):
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {}

    try:
        # The team switcher is chrome, so it follows the nav team: on an
        # account page the switcher should still name the team the user is in
        # and still offer the others, rather than emptying out.
        current_team = get_nav_team(request)
        if not current_team:
            return {}
    except Http404:
        # if the above raises a 404 it can cause a 500 error instead of letting it propagate
        return {}

    other_membership = request.user.membership_set
    if current_team and current_team.pk:
        other_membership = other_membership.exclude(team=current_team)

    pending_invitations = get_open_invitations_for_user(request.user)
    return {
        "other_teams": {
            membership.team.name: membership.team.dashboard_url
            for membership in other_membership.select_related("team")
        },
        "user_pending_invitations": pending_invitations,
    }
