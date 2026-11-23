"""The signed-in person's email preferences as an API (`/emails/api/preferences/`), for the phone app."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import EmailPreferences


class EmailPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailPreferences
        fields = ("bank_connection_alerts", "budget_alerts")


class EmailPreferencesView(APIView):
    # The person themselves, as for the profile: an API key is for books, not for
    # changing what mail the account gets.
    permission_classes = (IsAuthenticated,)

    @extend_schema(tags=["users"], operation_id="email_preferences_retrieve", responses=EmailPreferencesSerializer)
    def get(self, request):
        return Response(EmailPreferencesSerializer(EmailPreferences.for_user(request.user)).data)

    @extend_schema(
        tags=["users"],
        operation_id="email_preferences_partial_update",
        request=EmailPreferencesSerializer,
        responses=EmailPreferencesSerializer,
        description=(
            "Turn optional emails on or off; fields left out keep their value. Billing notices "
            "(trial ending, failed payment, annual renewal) go to team admins regardless."
        ),
    )
    def patch(self, request):
        serializer = EmailPreferencesSerializer(
            EmailPreferences.for_user(request.user), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
