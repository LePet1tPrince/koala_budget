"""
Views for bank_feed app.
Provides API endpoints for imported transactions and unified bank feed.
"""

from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Account, Payee
from apps.accounts.serializers import AccountSerializer, SimpleAccountSerializer, PayeeSerializer
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.decorators import login_and_team_required
from apps.teams.permissions import TeamModelAccessPermissions

from .models import BankTransaction
from .serializers import (
    BankTransactionSerializer,
    CategorizeTransactionsRequestSerializer,
    BankFeedRowSerializer,
    bank_transaction_to_feed_row,
    journal_line_to_feed_row,
    UploadParseResponseSerializer,
    UploadPreviewRequestSerializer,
    UploadPreviewResponseSerializer,
    UploadConfirmRequestSerializer,
    UploadConfirmResponseSerializer,
)
from .services.csv_upload import parse_file, preview_transactions, create_transactions

@extend_schema_view(
    list=extend_schema(
        operation_id="bank_feed_feed_list",
        tags=["bank-feed"],
        parameters=[
            OpenApiParameter(
                name="account",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Ledger account ID to filter bank feed by",
                required=False,
            ),
        ],
    ),
    retrieve=extend_schema(
        operation_id="bank_feed_feed_retrieve",
        tags=["bank-feed"],
    ),
)
class BankFeedViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Unified bank feed API.
    Uses BankTransaction as the base unit, combining uncategorized BankTransactions
    (extended with PlaidTransaction data when applicable) and categorized BankTransactions
    showing category from linked JournalEntry.

    - GET /a/{team_slug}/bankfeed/api/feed/ - Get all bank transactions
    - GET /a/{team_slug}/bankfeed/api/feed/{id}/ - Get transactions for specific account
    """

    serializer_class = BankFeedRowSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        """Get all BankTransactions, optionally filtered by account."""
        queryset = BankTransaction.objects.filter(
            team=self.request.team,
        ).select_related(
            "account",
            "journal_entry",
            "plaid_transaction",
            "plaid_transaction__plaid_account",
            "plaid_transaction__plaid_account__account",
        )

        # Filter by account if provided in query params
        account_id = self.request.query_params.get("account")
        if account_id:
            queryset = queryset.filter(account_id=account_id)

        return queryset

    @extend_schema(
        operation_id="bank_feed_transactions_categorize",
        tags=["bank-feed"],
        request=CategorizeTransactionsRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"])
    def categorize(self, request, team_slug=None):
        """
        Categorize one or more bank transactions.
        Creates journal entries linking the bank account to the category account.

        Body:
        - rows: List of transaction objects with 'id' field
        - category_id: ID of the category account
        """
        rows = request.data.get("rows", [])
        category_id = request.data.get("category_id")

        if not rows or not category_id:
            return Response(
                {"error": "rows and category_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify category account exists and belongs to team
        try:
            category_account = Account.for_team.get(id=category_id)
        except Account.DoesNotExist:
            return Response(
                {"error": "Category account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Process each row
        try:
            for row in rows:
                tx_id = row.get("id")
                if tx_id:
                    self._create_journal_from_bank_transaction(
                        transaction_id=tx_id,
                        category_account=category_account,
                        team=request.team,
                    )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def _create_journal_from_bank_transaction(self, transaction_id: int, category_account: Account, team):
        """
        Create a JournalEntry from a BankTransaction.
        Links the transaction to the journal entry.

        Raises:
            ValueError: If the transaction doesn't have a linked account
        """
        # Get the bank transaction
        bank_tx = BankTransaction.objects.select_related(
            "account",
            "plaid_transaction",
            "plaid_transaction__plaid_account",
            "plaid_transaction__plaid_account__account",
        ).get(id=transaction_id, team=team)

        # Get the bank account - BankTransaction always has a direct account FK
        if not bank_tx.account:
            raise ValueError("Cannot categorize transaction: No bank account linked.")
        bank_account = bank_tx.account

        # Create journal entry
        journal_entry = JournalEntry.objects.create(
            team=team,
            entry_date=bank_tx.posted_date,
            description=bank_tx.description,
            source=bank_tx.source,
            status=JournalEntry.STATUS_POSTED,
        )

        # Calculate amounts (Plaid convention: positive = outflow, negative = inflow)
        amount = abs(bank_tx.amount)
        is_inflow = bank_tx.amount < 0

        # Create journal lines
        if is_inflow:
            # Money coming in: debit bank account, credit category
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=bank_account,
                dr_amount=amount,
                cr_amount=Decimal("0"),
            )
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=category_account,
                dr_amount=Decimal("0"),
                cr_amount=amount,
            )
        else:
            # Money going out: credit bank account, debit category
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=bank_account,
                dr_amount=Decimal("0"),
                cr_amount=amount,
            )
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=category_account,
                dr_amount=amount,
                cr_amount=Decimal("0"),
            )

        # Link the bank transaction to the journal entry
        bank_tx.journal_entry = journal_entry
        bank_tx.save()

        return journal_entry



    def list(self, request, team_slug=None):
        """
        Get unified bank feed, optionally filtered by account.
        Query params:
        - account: Account ID to filter by (optional)
        """
        bank_transactions = self.get_queryset()

        # Convert queryset to feed row dicts
        rows = [bank_transaction_to_feed_row(tx) for tx in bank_transactions]

        # Sort by date (most recent first)
        rows.sort(key=lambda r: r["posted_date"], reverse=True)

        serializer = BankFeedRowSerializer(rows, many=True)
        # Return paginated format expected by generated API client
        return Response({
            "count": len(rows),
            "next": None,
            "previous": None,
            "results": serializer.data,
        })

    @extend_schema(
        operation_id="bank_feed_upload_parse",
        tags=["bank-feed"],
        request={"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}},
        responses={200: UploadParseResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="upload_parse")
    def upload_parse(self, request, team_slug=None):
        """
        Parse an uploaded CSV/Excel file and return headers + sample rows.
        Used in step 1 of the upload wizard.

        Request: multipart/form-data with 'file' field
        Response: headers, sample_rows, total_rows
        """
        if "file" not in request.FILES:
            return Response(
                {"error": "No file provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = request.FILES["file"]
        result = parse_file(uploaded_file, uploaded_file.name)

        serializer = UploadParseResponseSerializer(result.__dict__)
        return Response(serializer.data)

    @extend_schema(
        operation_id="bank_feed_upload_preview",
        tags=["bank-feed"],
        request={"multipart/form-data": {"type": "object", "properties": {
            "file": {"type": "string", "format": "binary"},
            "account_id": {"type": "integer"},
            "column_mapping": {"type": "string"},
            "category_mappings": {"type": "string"},
        }}},
        responses={200: UploadPreviewResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="upload_preview")
    def upload_preview(self, request, team_slug=None):
        """
        Apply column mapping to uploaded file and return parsed transactions.
        Used in step 2-3 of the upload wizard.

        Request: multipart/form-data with file and mapping data
        Response: parsed transactions, unmapped categories, error count, duplicate count
        """
        import json

        if "file" not in request.FILES:
            return Response(
                {"error": "No file provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = request.FILES["file"]

        # Parse JSON fields from form data
        try:
            account_id = int(request.data.get("account_id"))
        except (TypeError, ValueError):
            return Response(
                {"error": "Invalid account_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            column_mapping = json.loads(request.data.get("column_mapping", "{}"))
        except json.JSONDecodeError:
            return Response(
                {"error": "Invalid column_mapping JSON"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            category_mappings_list = json.loads(request.data.get("category_mappings", "[]"))
            # Convert list of {category_name, account_id} to dict
            category_mappings = {
                item["category_name"]: item["account_id"]
                for item in category_mappings_list
            }
        except (json.JSONDecodeError, KeyError):
            category_mappings = {}

        # Verify account belongs to team
        try:
            Account.for_team.get(id=account_id)
        except Account.DoesNotExist:
            return Response(
                {"error": "Account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = preview_transactions(
            file=uploaded_file,
            filename=uploaded_file.name,
            column_mapping=column_mapping,
            category_mappings=category_mappings,
            team=request.team,
            account_id=account_id,
        )

        # Convert dataclass objects to dicts for serializer
        transactions_data = [
            {
                "row_number": tx.row_number,
                "date": tx.date,
                "description": tx.description,
                "payee": tx.payee,
                "category": tx.category,
                "amount": tx.amount,
                "error": tx.error,
                "matched_category_id": tx.matched_category_id,
                "is_potential_duplicate": tx.is_potential_duplicate,
            }
            for tx in result.transactions
        ]

        response_data = {
            "transactions": transactions_data,
            "unmapped_categories": result.unmapped_categories,
            "error_count": result.error_count,
            "duplicate_count": result.duplicate_count,
        }

        serializer = UploadPreviewResponseSerializer(response_data)
        return Response(serializer.data)

    @extend_schema(
        operation_id="bank_feed_upload_confirm",
        tags=["bank-feed"],
        request=UploadConfirmRequestSerializer,
        responses={200: UploadConfirmResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="upload_confirm")
    def upload_confirm(self, request, team_slug=None):
        """
        Create BankTransaction records from confirmed transactions.
        Used in step 4 of the upload wizard.

        Request: account_id, transactions list, skip_duplicates flag
        Response: created_count, skipped_count, error_count
        """
        serializer = UploadConfirmRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        account_id = data["account_id"]
        transactions = data["transactions"]
        skip_duplicates = data.get("skip_duplicates", True)

        # Verify account belongs to team
        try:
            Account.for_team.get(id=account_id)
        except Account.DoesNotExist:
            return Response(
                {"error": "Account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = create_transactions(
            transactions=transactions,
            team=request.team,
            account_id=account_id,
            skip_duplicates=skip_duplicates,
        )

        response_serializer = UploadConfirmResponseSerializer(result)
        return Response(response_serializer.data)


# # Template Views


@login_and_team_required
def bank_feed_home(request, team_slug):
    """
    Main bank feed page view.
    Displays accounts with bank feeds and bank transactions table.
    """
    # Get accounts with bank feeds (with_balance() avoids N+1 queries)
    accounts_with_feeds = Account.for_team.filter(has_feed=True).with_balance().select_related("account_group").order_by("name")

    # Serialize accounts for React
    accounts_data = AccountSerializer(accounts_with_feeds, many=True).data

    # Get all accounts and payees for dropdowns
    all_accounts = Account.for_team.select_related("account_group").order_by("account_number")
    all_payees = Payee.for_team.all().order_by("name")

    all_accounts_data = SimpleAccountSerializer(all_accounts, many=True).data
    all_payees_data = PayeeSerializer(all_payees, many=True).data

    # API URLs
    api_urls = {
        "transactions_list": f"/a/{team_slug}/bankfeed/api/transactions/",
        "transactions_detail": f"/a/{team_slug}/bankfeed/api/transactions/{{id}}/",
        "feed_list": f"/a/{team_slug}/bankfeed/api/feed/",
    }

    return render(
        request,
        "bank_feed/bank_feed_home.html",
        {
            "active_tab": "bank-feed",
            "page_title": _("Bank Feed | {team}").format(team=request.team),
            "accounts": accounts_data,
            "all_accounts": all_accounts_data,
            "all_payees": all_payees_data,
            "api_urls": api_urls,
            "team_slug": team_slug,
        },
    )
