"""
The signed-in user's own account as an API (`/users/api/...`): profile, profile
picture, API keys, a download of their data and deleting the account.

Every endpoint here needs the person themselves -- a session or a session token
(`IsAuthenticated`), not an API key: a key is for reading and writing books, not
for minting more keys, changing the sign-in email or deleting the account.
"""

from allauth.account.internal.flows.reauthentication import did_recently_authenticate
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.models import UserAPIKey

from . import services
from .serializers import (
    APIKeyCreatedSerializer,
    APIKeySerializer,
    AvatarUploadSerializer,
    DeleteAccountSerializer,
    ProfileSerializer,
    ProfileUpdateSerializer,
)


class ProfileView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(tags=["users"], operation_id="profile_retrieve", responses=ProfileSerializer)
    def get(self, request):
        return Response(ProfileSerializer(request.user, context={"request": request}).data)

    @extend_schema(
        tags=["users"],
        operation_id="profile_partial_update",
        request=ProfileSerializer,
        responses=ProfileUpdateSerializer,
        description=(
            "Change the profile; fields left out keep their value. A new email address that needs "
            "confirming is not applied yet: a confirmation link is emailed to it "
            "(`email_confirmation_sent`) and the address changes once it is followed."
        ),
    )
    def patch(self, request):
        user = request.user
        serializer = ProfileSerializer(user, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(user, field, value)
        sent = services.save_profile(request, user)
        context = {"request": request, "email_confirmation_sent": sent}
        return Response(ProfileUpdateSerializer(user, context=context).data)


class AvatarUploadView(APIView):
    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        tags=["users"],
        operation_id="profile_avatar_upload",
        request={"multipart/form-data": AvatarUploadSerializer},
        responses=ProfileSerializer,
    )
    def post(self, request):
        serializer = AvatarUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.avatar = serializer.validated_data["avatar"]
        user.save()
        return Response(ProfileSerializer(user, context={"request": request}).data)


@extend_schema(tags=["users"])
class APIKeyViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The user's API keys that still work; a revoked key is gone from the list."""

    queryset = UserAPIKey.objects.none()  # for the schema; `get_queryset` is the user's
    serializer_class = APIKeySerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = "prefix"
    pagination_class = None

    def get_queryset(self):
        return self.request.user.api_keys.filter(revoked=False).order_by("-created")

    @extend_schema(operation_id="api_keys_list")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        operation_id="api_keys_create",
        request=None,
        responses={201: APIKeyCreatedSerializer},
        description="Create an API key. The response carries the key itself; it is never shown again.",
    )
    def create(self, request):
        api_key, key = services.create_api_key(request.user)
        api_key.key = key
        return Response(APIKeyCreatedSerializer(api_key).data, status=status.HTTP_201_CREATED)

    @extend_schema(operation_id="api_keys_revoke", request=None, responses={200: APIKeySerializer})
    @action(detail=True, methods=["post"])
    def revoke(self, request, prefix):
        api_key = get_object_or_404(self.get_queryset(), prefix=prefix)
        services.revoke_api_key(api_key)
        return Response(APIKeySerializer(api_key).data)


class DownloadDataView(APIView):
    """All the user's data as a ZIP archive (GDPR data portability). A file download, not JSON."""

    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["users"],
        operation_id="download_data",
        responses={(200, "application/zip"): OpenApiTypes.BINARY},
    )
    def get(self, request):
        buffer = services.export_user_data(request.user)
        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        filename = f"koala_budget_data_{request.user.email}.zip"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class DeleteAccountView(APIView):
    """
    Permanently delete the signed-in user's account (`services.delete_user_account`:
    teams they are the only member of go with it, with every book in them).

    Confirmed twice: the account's email typed out, as on the page, and
    re-authentication -- the password for an account that has one; for one that
    signs in only through a social provider, a recent sign-in or allauth
    re-authentication (`/_allauth/{client}/v1/auth/reauthenticate` or the MFA one).
    """

    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["users"],
        operation_id="delete_account",
        request=DeleteAccountSerializer,
        responses={
            204: None,
            400: OpenApiResponse(description="The email or password did not match."),
            403: OpenApiResponse(description="Re-authenticate first (an account without a password)."),
        },
    )
    def post(self, request):
        serializer = DeleteAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if serializer.validated_data["confirmation"] != user.email:
            raise ValidationError({"confirmation": [_("Email confirmation did not match. Account was not deleted.")]})
        if user.has_usable_password():
            if not user.check_password(serializer.validated_data.get("password") or ""):
                raise ValidationError({"password": [_("That isn't your password. Account was not deleted.")]})
        elif not did_recently_authenticate(request._request):
            raise PermissionDenied(_("Sign in again to confirm it's you, then delete the account."))
        # Signed out first: the logout's audit event needs the user to still exist.
        logout(request._request)
        services.delete_user_account(user)
        return Response(status=status.HTTP_204_NO_CONTENT)
