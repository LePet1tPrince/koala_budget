from apps.teams.roles import ROLE_ADMIN

from .entitlement import team_access as get_team_access


def team_access(request):
    """
    `team_access` (an `entitlement.Access`) and `team_access_is_admin` for the
    app chrome's trial / read-only banner, on pages of a team the user belongs to.
    """
    membership = getattr(request, "team_membership", None)
    if not membership:
        return {}
    return {"team_access": get_team_access(request.team), "team_access_is_admin": membership.role == ROLE_ADMIN}
