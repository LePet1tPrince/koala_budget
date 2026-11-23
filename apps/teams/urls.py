from django.urls import path
from rest_framework import routers

from . import views

app_name = "teams"

urlpatterns = [
    path("", views.manage_teams, name="teams_home"),
    path("manage/", views.manage_teams, name="manage_teams"),
    path("manage/<path:path>", views.manage_teams, name="manage_teams"),
    # invitation acceptance views
    path("invitation/<slug:invitation_id>/", views.accept_invitation, name="accept_invitation"),
    path("invitation/<slug:invitation_id>/signup/", views.SignupAfterInvite.as_view(), name="signup_after_invite"),
]

team_urlpatterns = (
    [
        # team management views
        path("", views.manage_team, name="manage_team"),
        path("members/<int:membership_id>/", views.team_membership_details, name="team_membership_details"),
        path("members/<int:membership_id>/remove/", views.remove_team_membership, name="remove_team_membership"),
    ],
    "single_team",
)

# DRF config for API views (required for React Teams, implementation, optional otherwise)
router = routers.DefaultRouter()
router.register("api/teams", views.TeamViewSet)
urlpatterns += router.urls + [
    path("api/user-invitations/", views.UserInvitations.as_view(), name="user_invitations_api"),
    # An invitation for the signed-in user to read and accept, by the id in the emailed link.
    path("api/invitations/<uuid:invitation_id>/", views.InvitationAcceptView.as_view(), name="invitation_api"),
]

single_team_router = routers.DefaultRouter()
single_team_router.register("api/invitations", views.InvitationViewSet)
single_team_router.register("api/memberships", views.MembershipViewSet, basename="membership")
team_urlpatterns[0].extend(single_team_router.urls)
