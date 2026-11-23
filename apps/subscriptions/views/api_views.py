from django.utils.translation import gettext as _
from djstripe.models import Price
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.permissions import IsAuthenticatedOrHasUserAPIKey
from apps.teams.permissions import TeamAdminPermissions

from ..exceptions import SubscriptionConfigError
from ..helpers import create_stripe_checkout_session, create_stripe_portal_session
from ..metadata import ProductWithMetadata, get_active_products_with_metadata


@extend_schema(tags=["subscriptions"])
class ProductWithMetadataAPI(APIView):
    """The plans on offer, with their prices: what a client shows before `create_checkout_session`."""

    permission_classes = (IsAuthenticatedOrHasUserAPIKey,)

    @extend_schema(
        operation_id="active_products_list",
        responses={200: serializers.ListSerializer(child=ProductWithMetadata.serializer())},
    )
    def get(self, request, *args, **kw):
        products_with_metadata = get_active_products_with_metadata()
        return Response(data=[p.to_dict() for p in products_with_metadata])


class CheckoutSessionRequestSerializer(serializers.Serializer):
    price_id = serializers.CharField(help_text="The Stripe price to subscribe to.")

    def validate_price_id(self, value):
        if not Price.objects.filter(id=value).exists():
            raise serializers.ValidationError(_("That isn't one of the plans on offer."))
        return value


class StripeSessionSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="The Stripe page to send the user to.")


# Billing is the team admins': the subscription page shows anyone else a "no access" page.
_PERMISSIONS = (IsAuthenticatedOrHasUserAPIKey, TeamAdminPermissions)


class CreateCheckoutSession(APIView):
    """
    A Stripe Checkout session for the team to subscribe to `price_id`: the URL to
    send the user to. The API form of the upgrade page's form, whose view
    (`create_checkout_session`) redirects to the same URL; Stripe returns to
    `subscriptions:subscription_confirm`.
    """

    permission_classes = _PERMISSIONS

    @extend_schema(
        tags=["subscriptions"],
        operation_id="create_checkout_session",
        request=CheckoutSessionRequestSerializer,
        responses={200: StripeSessionSerializer},
    )
    def post(self, request, team_slug):
        serializer = CheckoutSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        checkout_session = create_stripe_checkout_session(
            request.team, serializer.validated_data["price_id"], request.user
        )
        return Response(StripeSessionSerializer({"url": checkout_session.url}).data)


class CreatePortalSession(APIView):
    """A Stripe Customer Portal session for the team's subscription: the URL to send the user to."""

    permission_classes = _PERMISSIONS

    @extend_schema(
        tags=["subscriptions"],
        operation_id="create_portal_session",
        request=None,
        responses={200: StripeSessionSerializer},
    )
    def post(self, request, team_slug):
        try:
            portal_session = create_stripe_portal_session(request.team)
        except SubscriptionConfigError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from None
        return Response(StripeSessionSerializer({"url": portal_session.url}).data)
