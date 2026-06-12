from rest_framework import permissions
from rest_framework.request import Request

from .models import Team
from .roles import is_admin, is_member


class TeamAccessPermissions(permissions.BasePermission):
    """
    Permission to only allow admins of a team to edit the team object.

    Members of the team still have read-only access.
    """

    def has_permission(self, request, view):
        # DRF only calls has_object_permission for detail actions, so without this
        # check list/create (and custom non-detail actions) would be open to anyone.
        return _request_allowed_for_team(request)

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request
        # so we'll always allow GET, HEAD or OPTIONS requests for members
        return _view_for_members_edit_for_admins(request, obj)


class TeamModelAccessPermissions(permissions.BasePermission):
    """
    Use this permission to only allow admins of a team to edit the underlying object.
    Assumes the model instance has a `team` attribute.

    Members of the team still have read-only access.
    """

    def has_permission(self, request, view):
        # DRF only calls has_object_permission for detail actions, so without this
        # check list/create (and custom non-detail actions) would be open to anyone.
        return _request_allowed_for_team(request)

    def has_object_permission(self, request, view, obj):
        return _view_for_members_edit_for_admins(request, obj.team)


def _request_allowed_for_team(request: Request) -> bool:
    # Require an authenticated member of the team in context. Object-level checks
    # still restrict edits of existing objects to admins.
    team = getattr(request, "team", None)
    if not team or not request.user or not request.user.is_authenticated:
        return False
    return is_member(request.user, team)


def _view_for_members_edit_for_admins(request: Request, team: Team):
    if request.method in permissions.SAFE_METHODS:
        return is_member(request.user, team)
    return is_admin(request.user, team)
