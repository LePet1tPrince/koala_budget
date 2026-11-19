from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.permissions import IsAuthenticatedOrHasUserAPIKey

from ..helpers import get_open_invitations_for_user
from ..invitations import (
    InvitationNotAcceptable,
    check_can_accept,
    clear_invite_from_session,
    process_invitation,
    send_invitation,
)
from ..models import Invitation, Membership, Team
from ..permissions import TeamAccessPermissions, TeamMemberPermissions, TeamModelAccessPermissions
from ..roles import is_admin, is_member
from ..serializers import (
    AcceptedInvitationSerializer,
    InvitationDetailSerializer,
    InvitationSerializer,
    MembershipSerializer,
    OpenInvitationSerializer,
    TeamSerializer,
)
from ..services.memberships import MembershipNotAllowed, MembershipRefused, check_removal, check_role_change


@extend_schema_view(
    create=extend_schema(operation_id="teams_create"),
    list=extend_schema(operation_id="teams_list"),
    retrieve=extend_schema(operation_id="teams_retrieve"),
    update=extend_schema(operation_id="teams_update"),
    partial_update=extend_schema(operation_id="teams_partial_update"),
    destroy=extend_schema(operation_id="teams_destroy"),
)
class TeamViewSet(viewsets.ModelViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
    permission_classes = (IsAuthenticatedOrHasUserAPIKey, TeamAccessPermissions)

    def get_queryset(self):
        # filter queryset based on logged in user
        return self.request.user.teams.order_by("name")

    def perform_create(self, serializer):
        # ensure logged in user is set on the model during creation
        team = serializer.save()
        team.members.add(self.request.user, through_defaults={"role": "admin"})


@extend_schema(tags=["teams"])
@extend_schema_view(
    create=extend_schema(operation_id="invitations_create"),
    list=extend_schema(operation_id="invitations_list"),
    retrieve=extend_schema(operation_id="invitations_retrieve"),
    update=extend_schema(operation_id="invitations_update"),
    partial_update=extend_schema(operation_id="invitations_partial_update"),
    destroy=extend_schema(operation_id="invitations_destroy"),
)
class InvitationViewSet(viewsets.ModelViewSet):
    queryset = Invitation.objects.all()
    serializer_class = InvitationSerializer
    permission_classes = (IsAuthenticatedOrHasUserAPIKey, TeamModelAccessPermissions)

    @property
    def team(self):
        team = get_object_or_404(Team, slug=self.kwargs["team_slug"])
        if is_member(self.request.user, team):
            return team
        else:
            raise PermissionDenied()

    def _ensure_team_match(self, team):
        if team != self.team:
            raise DRFValidationError("Team set in invitation must match URL")

    def _ensure_no_pending_invite(self, team, email):
        if Invitation.objects.filter(team=team, email=email, is_accepted=False):
            raise DRFValidationError(
                {
                    # this mimics the same validation format used by the serializer
                    # so it can work easily on the front end.
                    "email": [
                        _(
                            "There is already a pending invitation for {}."
                            'You can resend it by clicking "Resend Invitation".'
                        ).format(email)
                    ]
                }
            )

    def get_queryset(self):
        # filter queryset based on logged in user and team
        return self.queryset.filter(team=self.team)

    def perform_create(self, serializer):
        # ensure logged in user is set on the model during creation
        # and can access the underlying team
        team = serializer.validated_data["team"]
        self._ensure_team_match(team)
        self._ensure_no_pending_invite(team, serializer.validated_data["email"])

        # unfortunately, the permissions class doesn't handle creation well
        # https://www.django-rest-framework.org/api-guide/permissions/#limitations-of-object-level-permissions
        if not is_admin(self.request.user, team):
            raise PermissionDenied()

        invitation = serializer.save(invited_by=self.request.user)
        send_invitation(invitation)

    def perform_update(self, serializer):
        # An invitation stays in the team it was made in. Moving it (a writable `team`)
        # would let an admin of any team -- anyone can create one -- point an invitation
        # to their own address at another team and accept it (security log, WP10).
        self._ensure_team_match(serializer.validated_data.get("team", serializer.instance.team))
        serializer.save()

    @extend_schema(
        operation_id="invitations_resend",
        request=None,
        responses={200: InvitationSerializer},
        description="Email the invitation again (admins).",
    )
    @action(detail=True, methods=["post"])
    def resend(self, request, team_slug, pk):
        # `get_object` runs the object check: only the team's admins may write.
        invitation = self.get_object()
        send_invitation(invitation)
        return Response(self.get_serializer(invitation).data)


def _membership_error(error):
    if isinstance(error, MembershipNotAllowed):
        return PermissionDenied(str(error))
    return DRFValidationError({"non_field_errors": [str(error)]})


@extend_schema(tags=["teams"])
@extend_schema_view(
    list=extend_schema(operation_id="memberships_list", description="The team's members, by email."),
    retrieve=extend_schema(operation_id="memberships_retrieve"),
    partial_update=extend_schema(
        operation_id="memberships_partial_update",
        description="Change a member's role (admins; never your own).",
    ),
    destroy=extend_schema(
        operation_id="memberships_destroy",
        description=(
            "Remove a member (admins), or leave the team (anyone, their own membership). "
            "The team's only admin can't be removed."
        ),
    ),
)
class MembershipViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Membership.objects.none()  # for the schema; `get_queryset` is the team's
    serializer_class = MembershipSerializer
    # Members read; who may change what is `services.memberships`, checked per request below.
    permission_classes = (IsAuthenticatedOrHasUserAPIKey, TeamMemberPermissions)
    http_method_names = ["get", "patch", "delete", "head", "options"]
    pagination_class = None

    def get_queryset(self):
        return Membership.objects.filter(team=self.request.team).select_related("user").order_by("user__email")

    def _acting_membership(self):
        return Membership.objects.filter(team=self.request.team, user=self.request.user).first()

    def update(self, request, *args, **kwargs):
        # Who may change this role, before what they sent is validated.
        try:
            check_role_change(self._acting_membership(), self.get_object())
        except (MembershipNotAllowed, MembershipRefused) as error:
            raise _membership_error(error) from None
        return super().update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        try:
            check_removal(self._acting_membership(), instance)
        except (MembershipNotAllowed, MembershipRefused) as error:
            raise _membership_error(error) from None
        instance.delete()


class UserInvitations(APIView):
    permission_classes = [IsAuthenticatedOrHasUserAPIKey]

    @extend_schema(
        tags=["teams"],
        operation_id="user_invitations",
        request=None,
        responses=inline_serializer(
            "UserInvitationsResponse",
            {"results": OpenInvitationSerializer(many=True)},
        ),
    )
    def get(self, request):
        open_invitations = get_open_invitations_for_user(request.user)
        return Response(
            {
                "results": open_invitations,
            }
        )


def _invitation_or_404(invitation_id) -> Invitation:
    return get_object_or_404(Invitation.objects.select_related("team", "invited_by"), id=invitation_id)


class InvitationAcceptView(APIView):
    """
    A team invitation, for the person it was sent to: `GET` describes it, `POST`
    accepts it. The API form of the invitation page (`teams:accept_invitation`),
    which keeps the invitation in the session across sign-in; here the client holds
    the id (from the emailed link) and calls this once signed in.

    Accepting needs the invitation's email address on the user's account and
    verified, as the page requires before it offers the button.
    """

    # A signed-in person (session or session token): joining a team is not something an API key does.
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["teams"],
        operation_id="invitation_details_retrieve",
        responses={200: InvitationDetailSerializer},
    )
    def get(self, request, invitation_id):
        invitation = _invitation_or_404(invitation_id)
        member = is_member(request.user, invitation.team)
        reason = None
        if not member:
            try:
                check_can_accept(invitation, request.user)
            except InvitationNotAcceptable as error:
                reason = str(error)
        data = {
            "id": invitation.id,
            "team_name": invitation.team.name,
            "invited_by": invitation.invited_by.get_display_name(),
            "email": invitation.email,
            "role": invitation.role,
            "is_accepted": invitation.is_accepted,
            "is_member": member,
            "can_accept": not member and reason is None,
            "cannot_accept_reason": reason,
        }
        return Response(InvitationDetailSerializer(data).data)

    @extend_schema(
        tags=["teams"],
        operation_id="invitation_accept",
        request=None,
        responses={200: AcceptedInvitationSerializer},
        description=(
            "Join the invitation's team. Already a member: nothing changes and `joined` is false. "
            "Refused (400) for an accepted invitation or one sent to an address the user hasn't verified."
        ),
    )
    def post(self, request, invitation_id):
        invitation = _invitation_or_404(invitation_id)
        team = invitation.team
        joined = False
        if not is_member(request.user, team):
            try:
                check_can_accept(invitation, request.user)
            except InvitationNotAcceptable as error:
                raise DRFValidationError({"non_field_errors": [str(error)]}) from None
            process_invitation(invitation, request.user)
            joined = True
        clear_invite_from_session(request)
        role = Membership.objects.get(team=team, user=request.user).role
        data = {"team_id": team.id, "team_slug": team.slug, "team_name": team.name, "role": role, "joined": joined}
        return Response(AcceptedInvitationSerializer(data).data)
