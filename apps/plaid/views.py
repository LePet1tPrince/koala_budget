"""
Views for Plaid app.
Provides bank feed API, Plaid Link integration, and account management.
"""

from decimal import Decimal

from django.db import transaction
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.models import Account
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.permissions import TeamModelAccessPermissions

from .models import ImportedTransaction, PlaidAccount, PlaidItem
from .serializers import (
    BankFeedRowSerializer,
    ImportedTransactionSerializer,
    PlaidAccountSerializer,
    PlaidItemSerializer,
    imported_tx_to_feed_row,
    journal_line_to_feed_row,
)
from .services import create_link_token, exchange_public_token, get_accounts, get_institution


@extend_schema_view(
    list=extend_schema(operation_id="bank_feed_list", tags=["plaid"]),
)
class BankFeedViewSet(viewsets.ViewSet):
    """
    Unified bank feed API.
    Combines ledger transactions (JournalLine) and uncategorized Plaid transactions
    into a single feed for a given account.
    """

    permission_classes = [TeamModelAccessPermissions]

    def list(self, request, team_slug=None):
        """
        Get unified bank feed for an account.
        Query params:
        - account: Account ID to filter by (required)
        """
        account_id = request.query_params.get("account")

        if not account_id:
            return Response(
                {"error": "account parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get ledger lines for this account
        ledger_lines = (
            JournalLine.for_team.filter(account_id=account_id)
            .select_related("account", "journal_entry", "journal_entry__payee")
            .prefetch_related("journal_entry__lines__account")
        )

        # Get uncategorized imported transactions for this account
        imported = ImportedTransaction.objects.filter(
            team=request.team,
            plaid_account__account_id=account_id,
            journal_entry__isnull=True,  # Only uncategorized
        ).select_related("plaid_account", "plaid_account__account")

        # Convert to feed rows
        rows = []

        for line in ledger_lines:
            rows.append(journal_line_to_feed_row(line))

        for tx in imported:
            rows.append(imported_tx_to_feed_row(tx))

        # Sort by date (most recent first)
        rows.sort(key=lambda r: r["date"], reverse=True)

        serializer = BankFeedRowSerializer(rows, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def categorize(self, request, team_slug=None):
        """
        Categorize one or more bank feed rows.
        Body:
        - rows: List of row objects with 'source' and 'id' fields
        - category_account_id: ID of the category account
        """
        rows = request.data.get("rows", [])
        category_account_id = request.data.get("category_account_id")

        if not rows or not category_account_id:
            return Response(
                {"error": "rows and category_account_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify category account exists and belongs to team
        try:
            category_account = Account.for_team.get(account_id=category_account_id)
        except Account.DoesNotExist:
            return Response(
                {"error": "Category account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Process each row
        for row in rows:
            if row["source"] == "plaid":
                create_journal_from_import(
                    imported_tx_id=row["imported_transaction_id"],
                    category_account=category_account,
                    team=request.team,
                )
            elif row["source"] == "ledger":
                update_simple_line_category(
                    journal_line_id=row["journal_line_id"],
                    category_account=category_account,
                    team=request.team,
                )

        return Response(status=status.HTTP_204_NO_CONTENT)


# Helper Functions


@transaction.atomic
def create_journal_from_import(imported_tx_id: int, category_account: Account, team):
    """
    Create a JournalEntry from an ImportedTransaction.
    Links the transaction to the journal entry.
    """
    # Get the imported transaction
    imported_tx = ImportedTransaction.objects.select_related("plaid_account", "plaid_account__account").get(
        id=imported_tx_id,
        team=team,
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


@extend_schema_view(
    list=extend_schema(operation_id="plaid_accounts_list", tags=["plaid"]),
    retrieve=extend_schema(operation_id="plaid_accounts_retrieve", tags=["plaid"]),
)
class PlaidAccountViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for PlaidAccount model (read-only)."""

    serializer_class = PlaidAccountSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return PlaidAccount.for_team.select_related("item", "account").all()


@extend_schema_view(
    list=extend_schema(operation_id="imported_transactions_list", tags=["plaid"]),
    retrieve=extend_schema(operation_id="imported_transactions_retrieve", tags=["plaid"]),
)
class ImportedTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for ImportedTransaction model (read-only)."""

    serializer_class = ImportedTransactionSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return ImportedTransaction.objects.filter(team=self.request.team).select_related(
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
    request={
        "type": "object",
        "properties": {
            "public_token": {"type": "string"},
            "institution_id": {"type": "string"},
            "accounts": {"type": "array", "items": {"type": "object"}},
        },
    },
    responses={200: {"type": "object", "properties": {"success": {"type": "boolean"}}}},
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
