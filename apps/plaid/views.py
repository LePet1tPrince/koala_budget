"""
Views for Plaid app.
Provides bank feed API, Plaid Link integration, and account management.
"""

from decimal import Decimal

from django.db import transaction
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.models import Account
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.permissions import TeamModelAccessPermissions

from .models import PlaidTransaction, PlaidAccount, PlaidItem
from .serializers import (
    PlaidTransactionSerializer,
    PlaidAccountSerializer,
    PlaidItemSerializer,
)
from .services import create_link_token, exchange_public_token, get_accounts, get_institution


# Helper Functions


@transaction.atomic
def create_journal_from_import(imported_tx_id: int, category_account: Account, team):
    """
    Create a JournalEntry from an PlaidTransaction.
    Links the transaction to the journal entry.

    Raises:
        ValueError: If the PlaidAccount is not mapped to a ledger account
    """
    # Get the imported transaction
    imported_tx = PlaidTransaction.objects.select_related("plaid_account", "plaid_account__account").get(
        id=imported_tx_id,
        team=team,
    )

    # Validate that the Plaid account is mapped to a ledger account
    if not imported_tx.plaid_account.is_mapped:
        raise ValueError(
            f"Cannot categorize transaction: Plaid account '{imported_tx.plaid_account.name}' "
            f"is not mapped to a ledger account. Please map the account first."
        )

    # Create journal entry
    journal_entry = JournalEntry.objects.create(
        team=team,
        entry_date=imported_tx.date,
        description=imported_tx.name,
        source=JournalEntry.SOURCE_IMPORT,
        status=JournalEntry.STATUS_DRAFT,
    )

    # Calculate amounts (Plaid: positive = outflow, negative = inflow)
    amount = abs(imported_tx.amount)
    is_inflow = imported_tx.amount < 0

    # Create main line (bank account)
    if is_inflow:
        # Money coming in: debit bank account
        JournalLine.objects.create(
            journal_entry=journal_entry,
            team=team,
            account=imported_tx.plaid_account.account,
            dr_amount=amount,
            cr_amount=Decimal("0"),
        )
        # Credit category account
        JournalLine.objects.create(
            journal_entry=journal_entry,
            team=team,
            account=category_account,
            dr_amount=Decimal("0"),
            cr_amount=amount,
        )
    else:
        # Money going out: credit bank account
        JournalLine.objects.create(
            journal_entry=journal_entry,
            team=team,
            account=imported_tx.plaid_account.account,
            dr_amount=Decimal("0"),
            cr_amount=amount,
        )
        # Debit category account
        JournalLine.objects.create(
            journal_entry=journal_entry,
            team=team,
            account=category_account,
            dr_amount=amount,
            cr_amount=Decimal("0"),
        )

    # Link the imported transaction to the journal entry
    imported_tx.journal_entry = journal_entry
    imported_tx.save()

    return journal_entry


@transaction.atomic
def update_simple_line_category(journal_line_id: int, category_account: Account, team):
    """
    Update the category of an existing simple journal entry.
    Updates the sibling line's account.
    """
    # Get the journal line
    line = JournalLine.for_team.select_related("journal_entry").prefetch_related("journal_entry__lines").get(
        id=journal_line_id,
        team=team,
    )

    # Get all lines for this journal entry
    all_lines = list(line.journal_entry.lines.all())

    # Only update if there are exactly 2 lines
    if len(all_lines) == 2:
        # Find the sibling line
        sibling = all_lines[0] if all_lines[1].id == line.id else all_lines[1]

        # Update the sibling's account to the new category
        sibling.account = category_account
        sibling.save()


# ViewSets for Plaid models


@extend_schema_view(
    list=extend_schema(operation_id="plaid_items_list", tags=["plaid"]),
    retrieve=extend_schema(operation_id="plaid_items_retrieve", tags=["plaid"]),
)
class PlaidItemViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for PlaidItem model (read-only)."""

    serializer_class = PlaidItemSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return PlaidItem.for_team.all()

    @extend_schema(
        operation_id="plaid_items_sync",
        tags=["plaid"],
        request=None,
        responses={200: {"type": "object", "properties": {"task_id": {"type": "string"}, "status": {"type": "string"}}}},
    )
    @action(detail=True, methods=["post"])
    def sync(self, request, pk=None, team_slug=None):
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
    permission_classes = [TeamModelAccessPermissions]
    http_method_names = ["get", "patch"]  # Only allow GET and PATCH

    def get_queryset(self):
        return PlaidAccount.for_team.select_related("item", "account").all()


@extend_schema_view(
    list=extend_schema(operation_id="imported_transactions_list", tags=["plaid"]),
    retrieve=extend_schema(operation_id="imported_transactions_retrieve", tags=["plaid"]),
)
class PlaidTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for PlaidTransaction model (read-only)."""

    serializer_class = PlaidTransactionSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return PlaidTransaction.objects.filter(team=self.request.team).select_related(
            "plaid_account",
            "plaid_account__account",
            "journal_entry",
        )


# Plaid Link API Endpoints


@extend_schema(
    operation_id="plaid_create_link_token",
    tags=["plaid"],
    request=None,
    responses={200: {"type": "object", "properties": {"link_token": {"type": "string"}}}},
)
@api_view(["POST"])
@permission_classes([TeamModelAccessPermissions])
def create_link_token_view(request, team_slug=None):
    """
    Create a Plaid Link token for initializing Plaid Link.
    Returns a link_token that can be used to initialize Plaid Link in the frontend.
    """
    try:
        link_token = create_link_token(user_id=request.user.id)
        return Response({"link_token": link_token})
    except Exception as e:
        return Response(
            {"error": str(e)},
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
            "accounts": drf_serializers.ListField(
                child=drf_serializers.DictField(),
                required=False,
            ),
        },
    ),
    responses={
        200: inline_serializer(
            name="ExchangePublicTokenResponse",
            fields={
                "success": drf_serializers.BooleanField(),
            },
        ),
    },
)
@api_view(["POST"])
@permission_classes([TeamModelAccessPermissions])
@transaction.atomic
def exchange_public_token_view(request, team_slug=None):
    """
    Exchange a public token for an access token and create PlaidItem and PlaidAccount records.
    Body:
    - public_token: Public token from Plaid Link
    - institution_id: Institution ID from Plaid Link
    - accounts: List of account objects from Plaid Link metadata
    """
    public_token = request.data.get("public_token")
    institution_id = request.data.get("institution_id")
    accounts_metadata = request.data.get("accounts", [])

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

        # Get institution details
        institution = get_institution(institution_id)
        institution_name = institution.get("name", "Unknown Institution")

        # Create PlaidItem
        plaid_item = PlaidItem.objects.create(
            team=request.team,
            plaid_item_id=item_id,
            access_token=access_token,
            institution_name=institution_name,
        )

        # Get full account details from Plaid
        accounts = get_accounts(access_token)

        # Create PlaidAccount records (will need manual mapping to ledger accounts)
        created_accounts = []
        for account in accounts:
            # For now, we'll create the PlaidAccount without linking to a ledger account
            # The user will need to map these manually in the UI
            plaid_account = PlaidAccount.objects.create(
                team=request.team,
                plaid_account_id=account["account_id"],
                item=plaid_item,
                account=None,  # Will be set by user later
                name=account.get("name", ""),
                mask=account.get("mask", ""),
                subtype=account.get("subtype", ""),
                type=account.get("type", ""),
            )
            created_accounts.append(plaid_account)

        return Response(
            {
                "success": True,
                "item_id": plaid_item.id,
                "accounts": PlaidAccountSerializer(created_accounts, many=True).data,
            }
        )

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
