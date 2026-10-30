"""
Views for Plaid app.
Provides bank feed API, Plaid Link integration, and account management.
"""

import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.books.permissions import BookModelAccessPermissions

from . import item_status, webhook_verification
from .linking import add_accounts
from .models import PlaidAccount, PlaidItem, PlaidTransaction
from .serializers import (
    ExchangePublicTokenResponseSerializer,
    ItemRefreshResponseSerializer,
    LinkTokenResponseSerializer,
    PlaidAccountSerializer,
    PlaidItemSerializer,
    PlaidTransactionSerializer,
)
from .services import create_link_token, create_update_link_token, exchange_public_token, get_accounts, get_institution

logger = logging.getLogger(__name__)

# ViewSets for Plaid models


@extend_schema_view(
    list=extend_schema(operation_id="plaid_items_list", tags=["plaid"]),
    retrieve=extend_schema(operation_id="plaid_items_retrieve", tags=["plaid"]),
)
class PlaidItemViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for PlaidItem model (read-only)."""

    serializer_class = PlaidItemSerializer
    permission_classes = [BookModelAccessPermissions]
    queryset = PlaidItem.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        return PlaidItem.for_book.all()

    @extend_schema(
        operation_id="plaid_items_sync",
        tags=["plaid"],
        request=None,
        responses={
            200: {"type": "object", "properties": {"task_id": {"type": "string"}, "status": {"type": "string"}}}
        },  # noqa: E501
    )
    @action(detail=True, methods=["post"])
    def sync(self, request, pk=None, team_slug=None, book_slug=None):
        """
        Trigger transaction sync for this Plaid item.
        Starts a background Celery task to sync transactions from Plaid.

        Validates that all accounts are mapped before syncing.
        """
        from .tasks import sync_plaid_transactions

        plaid_item = self.get_object()

        # Check if all accounts are mapped to ledger accounts
        unmapped_accounts = plaid_item.accounts.filter(account__isnull=True)
        if unmapped_accounts.exists():
            return Response(
                {
                    "error": "Cannot sync transactions. Please map all bank accounts to ledger accounts first.",
                    "unmapped_accounts": PlaidAccountSerializer(unmapped_accounts, many=True).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Trigger Celery task
        task = sync_plaid_transactions.delay(plaid_item.id)

        return Response(
            {
                "task_id": task.id,
                "status": "syncing",
                "message": "Transaction sync started",
            }
        )

    @extend_schema(
        operation_id="plaid_items_link_token",
        tags=["plaid"],
        request=None,
        responses={200: LinkTokenResponseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="link-token")
    def link_token(self, request, pk=None, team_slug=None, book_slug=None):
        """
        A Link token in update mode for this item: the user signs in to the bank
        again, renews consent, or shares accounts Plaid found since linking.
        """
        plaid_item = self.get_object()
        try:
            token = create_update_link_token(plaid_item, user_id=request.user.id)
        except Exception:
            logger.exception("Failed to create a Plaid update-mode link token for item %s", plaid_item.pk)
            return Response(
                {"error": "Could not start reconnecting this bank. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"link_token": token})

    @extend_schema(
        operation_id="plaid_items_refresh",
        tags=["plaid"],
        request=None,
        responses={200: ItemRefreshResponseSerializer},
    )
    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None, team_slug=None, book_slug=None):
        """
        After Link's update mode succeeds: mark the connection healthy, add any
        accounts the user just shared (returned for mapping), and queue a sync.
        """
        from .tasks import sync_plaid_transactions

        plaid_item = self.get_object()
        try:
            new_accounts = add_accounts(plaid_item, get_accounts(plaid_item.access_token))
        except Exception:
            logger.exception("Failed to refresh Plaid accounts for item %s", plaid_item.pk)
            return Response(
                {"error": "Could not read this bank's accounts. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        item_status.record_reconnected(plaid_item)
        sync_plaid_transactions.delay(plaid_item.id)
        return Response(
            {
                "item": PlaidItemSerializer(plaid_item).data,
                "new_accounts": PlaidAccountSerializer(new_accounts, many=True, context={"request": request}).data,
            }
        )


@extend_schema_view(
    list=extend_schema(operation_id="plaid_accounts_list", tags=["plaid"]),
    retrieve=extend_schema(operation_id="plaid_accounts_retrieve", tags=["plaid"]),
    partial_update=extend_schema(operation_id="plaid_accounts_partial_update", tags=["plaid"]),
)
class PlaidAccountViewSet(viewsets.ModelViewSet):
    """
    ViewSet for PlaidAccount model.
    Allows updating the 'account' field to map Plaid accounts to ledger accounts.
    """

    serializer_class = PlaidAccountSerializer
    permission_classes = [BookModelAccessPermissions]
    http_method_names = ["get", "patch"]  # Only allow GET and PATCH
    queryset = PlaidAccount.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        return PlaidAccount.for_book.select_related("item", "account").all()


@extend_schema_view(
    list=extend_schema(operation_id="imported_transactions_list", tags=["plaid"]),
    retrieve=extend_schema(operation_id="imported_transactions_retrieve", tags=["plaid"]),
)
class PlaidTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for PlaidTransaction model (read-only)."""

    serializer_class = PlaidTransactionSerializer
    permission_classes = [BookModelAccessPermissions]
    queryset = PlaidTransaction.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        return PlaidTransaction.objects.filter(book=self.request.book).select_related(
            "plaid_account",
            "plaid_account__account",
            "bank_transaction",
        )


# Plaid Link API Endpoints


def _institution_name(institution_id, fallback=None):
    """
    The institution's display name. A failed lookup must not fail the link --
    the bank is already connected at Plaid by then -- so Link's own metadata
    name stands in.
    """
    try:
        return get_institution(institution_id).get("name") or fallback or "Unknown Institution"
    except Exception:
        logger.warning("Plaid institution lookup failed for %s", institution_id, exc_info=True)
        return fallback or "Unknown Institution"


@extend_schema(
    operation_id="plaid_create_link_token",
    tags=["plaid"],
    request=None,
    responses={200: {"type": "object", "properties": {"link_token": {"type": "string"}}}},
)
@api_view(["POST"])
@permission_classes([BookModelAccessPermissions])
def create_link_token_view(request, team_slug=None, book_slug=None):
    """
    Create a Plaid Link token for initializing Plaid Link.
    Returns a link_token that can be used to initialize Plaid Link in the frontend.
    """
    try:
        link_token = create_link_token(user_id=request.user.id)
        return Response({"link_token": link_token})
    except Exception:
        logger.exception("Failed to create Plaid link token")
        return Response(
            {"error": "Failed to create link token. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@extend_schema(
    operation_id="plaid_exchange_public_token",
    tags=["plaid"],
    request=inline_serializer(
        name="ExchangePublicTokenRequest",
        fields={
            "public_token": drf_serializers.CharField(),
            "institution_id": drf_serializers.CharField(),
            "institution_name": drf_serializers.CharField(required=False),
            "accounts": drf_serializers.ListField(
                child=drf_serializers.DictField(),
                required=False,
            ),
        },
    ),
    responses={200: ExchangePublicTokenResponseSerializer},
)
@api_view(["POST"])
@permission_classes([BookModelAccessPermissions])
@transaction.atomic
def exchange_public_token_view(request, team_slug=None, book_slug=None):
    """
    Exchange a public token for an access token and create PlaidItem and PlaidAccount records.
    Body:
    - public_token: Public token from Plaid Link
    - institution_id: Institution ID from Plaid Link
    - accounts: List of account objects from Plaid Link metadata
    """
    public_token = request.data.get("public_token")
    institution_id = request.data.get("institution_id")

    if not public_token or not institution_id:
        return Response(
            {"error": "public_token and institution_id are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Exchange public token for access token
        exchange_result = exchange_public_token(public_token)
        access_token = exchange_result["access_token"]
        item_id = exchange_result["item_id"]

        institution_name = _institution_name(institution_id, request.data.get("institution_name"))

        # Create PlaidItem
        plaid_item = PlaidItem.objects.create(
            book=request.book,
            plaid_item_id=item_id,
            access_token=access_token,
            institution_name=institution_name,
        )

        # The new accounts start unmapped; the user maps them in the UI.
        created_accounts = add_accounts(plaid_item, get_accounts(access_token))

        return Response(
            {
                "success": True,
                "item_id": plaid_item.id,
                "accounts": PlaidAccountSerializer(created_accounts, many=True).data,
            }
        )

    except Exception:
        logger.exception("Failed to exchange Plaid public token")
        return Response(
            {"error": "Failed to link bank account. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# Plaid Webhooks

#: TRANSACTIONS webhooks that mean "there is something to sync". The last three
#: are the pre-/transactions/sync codes, still sent to older items.
SYNC_WEBHOOK_CODES = ("SYNC_UPDATES_AVAILABLE", "INITIAL_UPDATE", "HISTORICAL_UPDATE", "DEFAULT_UPDATE")


@csrf_exempt
@require_POST
def plaid_webhook_view(request):
    """
    Receive Plaid webhooks (global endpoint — Plaid can't know team slugs).

    TRANSACTIONS webhooks enqueue an incremental sync for the item. ITEM
    webhooks record what the connection needs from the user (sign in again,
    consent expiring, access revoked, new accounts to share) on the item's
    status -- see apps.plaid.item_status -- and LOGIN_REPAIRED queues a sync.

    The request must carry Plaid's signature (apps.plaid.webhook_verification,
    switched off only by PLAID_VERIFY_WEBHOOKS=False for local development);
    an unverified one is refused with 400 and does nothing.

    Otherwise always returns 200 so Plaid doesn't retry storms on payloads we ignore.
    """
    from .tasks import sync_plaid_transactions

    if settings.PLAID_VERIFY_WEBHOOKS:
        try:
            webhook_verification.verify(request.body, request.headers.get("Plaid-Verification"))
        except webhook_verification.WebhookVerificationError as exc:
            logger.warning("Refused an unverified Plaid webhook: %s", exc)
            return JsonResponse({"status": "unverified"}, status=400)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"status": "ignored"})

    webhook_type = payload.get("webhook_type")
    webhook_code = payload.get("webhook_code")
    item_id = payload.get("item_id")

    if not item_id or webhook_type not in ("TRANSACTIONS", "ITEM"):
        return JsonResponse({"status": "ignored"})
    if webhook_type == "TRANSACTIONS" and webhook_code not in SYNC_WEBHOOK_CODES:
        return JsonResponse({"status": "ignored"})

    plaid_item = PlaidItem.objects.select_related("book").filter(plaid_item_id=item_id).first()
    if plaid_item is None:
        logger.warning("Plaid webhook for unknown item %s", item_id)
        return JsonResponse({"status": "ignored"})

    if webhook_type == "TRANSACTIONS":
        sync_plaid_transactions.delay(plaid_item.id)
        return JsonResponse({"status": "sync_queued"})

    if item_status.handle_item_webhook(plaid_item, webhook_code, payload):
        sync_plaid_transactions.delay(plaid_item.id)
        return JsonResponse({"status": "sync_queued"})
    return JsonResponse({"status": "recorded"})
