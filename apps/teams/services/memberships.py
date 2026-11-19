"""
Who may change a team membership, and how -- shared by the membership pages
(`views/membership_views.py`) and the memberships API (`views/api_views.py`).

* Admins change other members' roles; nobody changes their own (so a team always
  keeps the admin making the change).
* Admins remove anyone; a member may remove only themselves (leave the team).
* The team's only admin can't be removed: make someone else an admin first.
"""

from django.utils.translation import gettext as _

from ..models import Membership
from ..roles import ROLE_ADMIN


class MembershipNotAllowed(Exception):
    """The acting user may not do this to that membership at all (a 403)."""


class MembershipRefused(Exception):
    """Allowed in principle, but not to this membership now (a 400)."""


def check_role_change(acting: Membership | None, membership: Membership):
    # `not acting`, not `is None`: the views pass `request.team_membership`, a lazy object.
    if not acting or not acting.is_admin():
        raise MembershipNotAllowed(_("You don't have permission to edit team members in that team."))
    if membership.user_id == acting.user_id:
        raise MembershipRefused(_("You aren't allowed to change your own role."))


def check_removal(acting: Membership | None, membership: Membership):
    removing_self = bool(acting) and membership.user_id == acting.user_id
    if not removing_self and (not acting or not acting.is_admin()):
        raise MembershipNotAllowed(_("You don't have permission to remove others from that team."))
    if membership.role == ROLE_ADMIN:
        admin_count = Membership.objects.filter(team_id=membership.team_id, role=ROLE_ADMIN).count()
        if admin_count == 1:
            raise MembershipRefused(
                _(
                    "You cannot remove the only administrator from a team. "
                    "Make another team member an administrator and try again."
                )
            )
