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
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Account, Payee
from apps.accounts.serializers import AccountSerializer, PayeeSerializer, SimpleAccountSerializer
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.decorators import login_and_team_required
from apps.teams.permissions import TeamModelAccessPermissions

from .models import BankTransaction
from .serializers import (
    BankFeedRowSerializer,
    BatchEditRequestSerializer,
    BatchIdsSerializer,
    BatchReconcileRequestSerializer,
    CategorizeTransactionsRequestSerializer,
    UploadConfirmRequestSerializer,
    UploadConfirmResponseSerializer,
    UploadParseResponseSerializer,
    UploadPreviewResponseSerializer,
    bank_transaction_to_feed_row,
)
from .services.csv_upload import create_transactions, parse_file, preview_transactions


class ManualTransactionSerializer(serializers.Serializer):
    """Serializer for creating/updating manual transactions."""

    date = serializers.DateField(help_text="Transaction date")
    category = serializers.IntegerField(help_text="Category account ID")
    inflow = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        default=Decimal("0"),
        help_text="Money coming in",
    )
    outflow = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        default=Decimal("0"),
        help_text="Money going out",
    )
    payee = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Payee/merchant name",
    )
    description = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Transaction description",
    )
    account = serializers.IntegerField(help_text="Bank account ID")


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
    create=extend_schema(
        operation_id="bank_feed_feed_create",
        tags=["bank-feed"],
        request=ManualTransactionSerializer,
        responses={201: BankFeedRowSerializer},
    ),
    update=extend_schema(
        operation_id="bank_feed_feed_update",
        tags=["bank-feed"],
        request=ManualTransactionSerializer,
        responses={200: BankFeedRowSerializer},
    ),
)
class BankFeedViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Unified bank feed API.
    Uses BankTransaction as the base unit, combining uncategorized BankTransactions
    (extended with PlaidTransaction data when applicable) and categorized BankTransactions
    showing category from linked JournalEntry.

    - GET /a/{team_slug}/bankfeed/api/feed/ - Get all bank transactions (filtered by ?account=)
    """

    serializer_class = BankFeedRowSerializer
    permission_classes = [TeamModelAccessPermissions]
    queryset = BankTransaction.objects.none()  # for drf-spectacular schema generation

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
        return Response(
            {
                "count": len(rows),
                "next": None,
                "previous": None,
                "results": serializer.data,
            }
        )

    def create(self, request, team_slug=None):
        """
        Create a new manual bank transaction with associated journal entry.

        Request body:
        - date: Transaction date (YYYY-MM-DD)
        - category: Category account ID
        - inflow: Money coming in (default 0)
        - outflow: Money going out (default 0)
        - payee: Payee/merchant name (optional)
        - description: Transaction description (optional)
        - account: Bank account ID
        """
        serializer = ManualTransactionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # Verify accounts exist and belong to team
        try:
            bank_account = Account.for_team.get(id=data["account"])
        except Account.DoesNotExist:
            return Response(
                {"error": "Bank account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            category_account = Account.for_team.get(id=data["category"])
        except Account.DoesNotExist:
            return Response(
                {"error": "Category account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Calculate amount (Plaid convention: positive = outflow, negative = inflow)
        inflow = data.get("inflow", Decimal("0")) or Decimal("0")
        outflow = data.get("outflow", Decimal("0")) or Decimal("0")
        amount = outflow - inflow  # positive = outflow

        # Get or create payee if provided
        payee = None
        payee_name = data.get("payee", "")
        if payee_name:
            payee, _ = Payee.objects.get_or_create(
                team=request.team,
                name=payee_name,
            )

        with transaction.atomic():
            # Create journal entry
            journal_entry = JournalEntry.objects.create(
                team=request.team,
                entry_date=data["date"],
                description=data.get("description", ""),
                payee=payee,
                source="M",  # Manual
                status=JournalEntry.STATUS_POSTED,
            )

            # Create journal lines
            abs_amount = abs(amount)
            if inflow > 0:
                # Money coming in: debit bank account, credit category
                JournalLine.objects.create(
                    journal_entry=journal_entry,
                    team=request.team,
                    account=bank_account,
                    dr_amount=abs_amount,
                    cr_amount=Decimal("0"),
                )
                JournalLine.objects.create(
                    journal_entry=journal_entry,
                    team=request.team,
                    account=category_account,
                    dr_amount=Decimal("0"),
                    cr_amount=abs_amount,
                )
            else:
                # Money going out: credit bank account, debit category
                JournalLine.objects.create(
                    journal_entry=journal_entry,
                    team=request.team,
                    account=bank_account,
                    dr_amount=Decimal("0"),
                    cr_amount=abs_amount,
                )
                JournalLine.objects.create(
                    journal_entry=journal_entry,
                    team=request.team,
                    account=category_account,
                    dr_amount=abs_amount,
                    cr_amount=Decimal("0"),
                )

            # Create bank transaction
            bank_tx = BankTransaction.objects.create(
                team=request.team,
                account=bank_account,
                amount=amount,
                posted_date=data["date"],
                description=data.get("description", ""),
                merchant_name=payee_name,
                source="M",  # Manual
                journal_entry=journal_entry,
            )

        # Return the created transaction as a feed row
        row = bank_transaction_to_feed_row(bank_tx)
        response_serializer = BankFeedRowSerializer(row)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, team_slug=None, pk=None):
        """
        Update an existing bank transaction and its associated journal entry.

        Request body:
        - date: Transaction date (YYYY-MM-DD)
        - category: Category account ID
        - inflow: Money coming in (default 0)
        - outflow: Money going out (default 0)
        - payee: Payee/merchant name (optional)
        - description: Transaction description (optional)
        - account: Bank account ID
        """
        # Get the existing bank transaction
        try:
            bank_tx = BankTransaction.objects.select_related("account", "journal_entry").get(id=pk, team=request.team)
        except BankTransaction.DoesNotExist:
            return Response(
                {"error": "Transaction not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ManualTransactionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # Verify accounts exist and belong to team
        try:
            bank_account = Account.for_team.get(id=data["account"])
        except Account.DoesNotExist:
            return Response(
                {"error": "Bank account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            category_account = Account.for_team.get(id=data["category"])
        except Account.DoesNotExist:
            return Response(
                {"error": "Category account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Calculate amount (Plaid convention: positive = outflow, negative = inflow)
        inflow = data.get("inflow", Decimal("0")) or Decimal("0")
        outflow = data.get("outflow", Decimal("0")) or Decimal("0")
        amount = outflow - inflow  # positive = outflow

        # Get or create payee if provided
        payee = None
        payee_name = data.get("payee", "")
        if payee_name:
            payee, _ = Payee.objects.get_or_create(
                team=request.team,
                name=payee_name,
            )

        with transaction.atomic():
            # Update bank transaction
            bank_tx.account = bank_account
            bank_tx.amount = amount
            bank_tx.posted_date = data["date"]
            bank_tx.description = data.get("description", "")
            bank_tx.merchant_name = payee_name
            bank_tx.save()

            # Update or create journal entry
            journal_entry = bank_tx.journal_entry
            if journal_entry:
                # Update existing journal entry
                journal_entry.entry_date = data["date"]
                journal_entry.description = data.get("description", "")
                journal_entry.payee = payee
                journal_entry.save()

                # Update journal lines
                lines = list(journal_entry.lines.all())
                abs_amount = abs(amount)

                for line in lines:
                    if line.account == bank_tx.account or line.account == bank_account:
                        # Bank account line
                        line.account = bank_account
                        if inflow > 0:
                            line.dr_amount = abs_amount
                            line.cr_amount = Decimal("0")
                        else:
                            line.dr_amount = Decimal("0")
                            line.cr_amount = abs_amount
                        line.save()
                    else:
                        # Category line
                        line.account = category_account
                        if inflow > 0:
                            line.dr_amount = Decimal("0")
                            line.cr_amount = abs_amount
                        else:
                            line.dr_amount = abs_amount
                            line.cr_amount = Decimal("0")
                        line.save()
            else:
                # Create new journal entry if one doesn't exist
                journal_entry = JournalEntry.objects.create(
                    team=request.team,
                    entry_date=data["date"],
                    description=data.get("description", ""),
                    payee=payee,
                    source="M",
                    status=JournalEntry.STATUS_POSTED,
                )

                abs_amount = abs(amount)
                if inflow > 0:
                    JournalLine.objects.create(
                        journal_entry=journal_entry,
                        team=request.team,
                        account=bank_account,
                        dr_amount=abs_amount,
                        cr_amount=Decimal("0"),
                    )
                    JournalLine.objects.create(
                        journal_entry=journal_entry,
                        team=request.team,
                        account=category_account,
                        dr_amount=Decimal("0"),
                        cr_amount=abs_amount,
                    )
                else:
                    JournalLine.objects.create(
                        journal_entry=journal_entry,
                        team=request.team,
                        account=bank_account,
                        dr_amount=Decimal("0"),
                        cr_amount=abs_amount,
                    )
                    JournalLine.objects.create(
                        journal_entry=journal_entry,
                        team=request.team,
                        account=category_account,
                        dr_amount=abs_amount,
                        cr_amount=Decimal("0"),
                    )

                bank_tx.journal_entry = journal_entry
                bank_tx.save()

        # Reload to get updated data
        bank_tx.refresh_from_db()

        # Return the updated transaction as a feed row
        row = bank_transaction_to_feed_row(bank_tx)
        response_serializer = BankFeedRowSerializer(row)
        return Response(response_serializer.data)

    @extend_schema(
        operation_id="bank_feed_upload_parse",
        tags=["bank-feed"],
        request={
            "multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}
        },  # noqa: E501
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
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "account_id": {"type": "integer"},
                    "column_mapping": {"type": "string"},
                    "category_mappings": {"type": "string"},
                },
            }
        },
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
            category_mappings = {item["category_name"]: item["account_id"] for item in category_mappings_list}
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

    # Batch Operations

    @extend_schema(
        operation_id="bank_feed_batch_edit",
        tags=["bank-feed"],
        request=BatchEditRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["patch"], url_path="batch_edit")
    def batch_edit(self, request, team_slug=None):
        """
        Bulk edit multiple bank transactions.
        Only fields that are provided (non-null) are updated.
        Supports: category_id, account_id (move), payee, description, date.
        """
        serializer = BatchEditRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        ids = data["ids"]
        category_id = data.get("category_id")
        account_id = data.get("account_id")
        payee_name = data.get("payee")
        description = data.get("description")
        new_date = data.get("date")

        # Validate referenced objects up front
        category_account = None
        if category_id is not None:
            try:
                category_account = Account.for_team.get(id=category_id)
            except Account.DoesNotExist:
                return Response(
                    {"error": "Category account not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        target_account = None
        if account_id is not None:
            try:
                target_account = Account.for_team.get(id=account_id)
                if not target_account.has_feed:
                    return Response(
                        {"error": "Target account must have bank feed enabled"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except Account.DoesNotExist:
                return Response(
                    {"error": "Target account not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        payee_obj = None
        if payee_name is not None:
            payee_obj, _ = Payee.objects.get_or_create(
                team=request.team,
                name=payee_name,
            )

        # Get transactions
        transactions = BankTransaction.objects.filter(
            id__in=ids,
            team=request.team,
        ).select_related("account", "journal_entry")

        with transaction.atomic():
            for tx in transactions:
                # --- Category ---
                if category_account is not None:
                    if tx.journal_entry:
                        self._update_journal_category(tx, category_account)
                    else:
                        self._create_journal_from_bank_transaction(
                            transaction_id=tx.id,
                            category_account=category_account,
                            team=request.team,
                        )
                        tx.refresh_from_db()

                # --- Move account ---
                if target_account is not None:
                    old_account = tx.account
                    tx.account = target_account
                    if tx.journal_entry:
                        for line in tx.journal_entry.lines.all():
                            if line.account == old_account:
                                line.account = target_account
                                line.save()
                                break

                # --- Payee ---
                if payee_name is not None:
                    tx.merchant_name = payee_name
                    if tx.journal_entry:
                        tx.journal_entry.payee = payee_obj
                        tx.journal_entry.save()

                # --- Description ---
                if description is not None:
                    tx.description = description
                    if tx.journal_entry:
                        tx.journal_entry.description = description
                        tx.journal_entry.save()

                # --- Date ---
                if new_date is not None:
                    tx.posted_date = new_date
                    if tx.journal_entry:
                        tx.journal_entry.entry_date = new_date
                        tx.journal_entry.save()

                tx.save()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def _update_journal_category(self, bank_tx, new_category_account):
        """Update the category line of an existing journal entry."""
        journal_entry = bank_tx.journal_entry
        # Find the category line (the one that's not the bank account)
        for line in journal_entry.lines.all():
            if line.account != bank_tx.account:
                line.account = new_category_account
                line.save()
                break

    @extend_schema(
        operation_id="bank_feed_batch_archive",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="batch_archive")
    def batch_archive(self, request, team_slug=None):
        """
        Batch archive multiple bank transactions.
        Sets is_archived=True on BankTransaction.
        """
        serializer = BatchIdsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ids = serializer.validated_data["ids"]

        # Update transactions that belong to this team
        BankTransaction.objects.filter(
            id__in=ids,
            team=request.team,
        ).update(is_archived=True)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="bank_feed_batch_unarchive",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="batch_unarchive")
    def batch_unarchive(self, request, team_slug=None):
        """
        Batch unarchive multiple bank transactions.
        Sets is_archived=False on BankTransaction.
        """
        serializer = BatchIdsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ids = serializer.validated_data["ids"]

        # Update transactions that belong to this team
        BankTransaction.objects.filter(
            id__in=ids,
            team=request.team,
        ).update(is_archived=False)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="bank_feed_batch_duplicate",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={200: BankFeedRowSerializer(many=True)},
    )
    @action(detail=False, methods=["post"], url_path="batch_duplicate")
    def batch_duplicate(self, request, team_slug=None):
        """
        Batch duplicate multiple bank transactions.
        Creates new BankTransaction copies without journal entries.
        """
        serializer = BatchIdsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ids = serializer.validated_data["ids"]

        # Get transactions that belong to this team
        transactions = BankTransaction.objects.filter(
            id__in=ids,
            team=request.team,
        ).select_related("account")

        created_transactions = []
        for tx in transactions:
            # Create a duplicate with no journal entry
            new_tx = BankTransaction.objects.create(
                team=request.team,
                account=tx.account,
                amount=tx.amount,
                posted_date=tx.posted_date,
                description=tx.description,
                merchant_name=tx.merchant_name,
                source=tx.source,
                raw={"duplicated_from": tx.id},
                journal_entry=None,
            )
            created_transactions.append(new_tx)

        # Return the created transactions as feed rows
        rows = [bank_transaction_to_feed_row(tx) for tx in created_transactions]
        response_serializer = BankFeedRowSerializer(rows, many=True)
        return Response(response_serializer.data)

    @extend_schema(
        operation_id="bank_feed_batch_reconcile",
        tags=["bank-feed"],
        request=BatchReconcileRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="batch_reconcile")
    def batch_reconcile(self, request, team_slug=None):
        """
        Batch reconcile multiple bank transactions.
        Sets is_reconciled=True on the JournalLine for the bank account side.
        Optionally creates an adjustment if adjustment_amount is non-zero.
        """
        serializer = BatchReconcileRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ids = serializer.validated_data["ids"]
        adjustment_amount = serializer.validated_data.get("adjustment_amount", Decimal("0"))

        # Get transactions that belong to this team
        transactions = BankTransaction.objects.filter(
            id__in=ids,
            team=request.team,
        ).select_related("account", "journal_entry")

        # Validate: All transactions must be categorized (have journal_entry)
        uncategorized = [tx for tx in transactions if not tx.journal_entry]
        if uncategorized:
            return Response(
                {
                    "error": f"Cannot reconcile uncategorized transactions. {len(uncategorized)} transaction(s) need to be categorized first."  # noqa: E501
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the account (assuming all transactions are for the same account)
        if not transactions:
            return Response(status=status.HTTP_204_NO_CONTENT)

        bank_account = transactions[0].account

        with transaction.atomic():
            # Mark each transaction's bank account journal line as reconciled
            for tx in transactions:
                for line in tx.journal_entry.lines.all():
                    if line.account == tx.account:
                        line.is_reconciled = True
                        line.save()
                        break

            # Create adjustment if needed
            if adjustment_amount and adjustment_amount != Decimal("0"):
                self._create_reconciliation_adjustment(
                    team=request.team,
                    bank_account=bank_account,
                    amount=adjustment_amount,
                )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def _create_reconciliation_adjustment(self, team, bank_account, amount):
        """
        Create a reconciliation adjustment transaction.
        Creates a BankTransaction with source='S' and a JournalEntry linking to an 'Adjustments' account.
        The adjustment is marked as reconciled immediately.
        """
        from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, AccountGroup

        # First, find or create an expense group for adjustments
        expense_group = AccountGroup.objects.filter(
            team=team,
            account_type=ACCOUNT_TYPE_EXPENSE,
        ).first()

        if not expense_group:
            # Create a default expense group if none exists
            expense_group = AccountGroup.objects.create(
                team=team,
                name="Expenses",
                account_type=ACCOUNT_TYPE_EXPENSE,
            )

        # Find or create the Adjustments account (account_group is required)
        adjustments_account, created = Account.objects.get_or_create(
            team=team,
            name="Reconciliation Adjustments",
            defaults={
                "account_number": "9999",
                "has_feed": False,
                "account_group": expense_group,
            },
        )

        # Create the journal entry
        journal_entry = JournalEntry.objects.create(
            team=team,
            entry_date=datetime.now().date(),
            description="Reconciliation Adjustment",
            source="S",  # System
            status=JournalEntry.STATUS_POSTED,
        )

        # Determine dr/cr based on sign (positive = increase bank balance)
        abs_amount = abs(amount)
        if amount > 0:
            # Positive adjustment: debit bank account, credit adjustments
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=bank_account,
                dr_amount=abs_amount,
                cr_amount=Decimal("0"),
                is_reconciled=True,  # Mark as reconciled immediately
            )
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=adjustments_account,
                dr_amount=Decimal("0"),
                cr_amount=abs_amount,
            )
        else:
            # Negative adjustment: credit bank account, debit adjustments
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=bank_account,
                dr_amount=Decimal("0"),
                cr_amount=abs_amount,
                is_reconciled=True,  # Mark as reconciled immediately
            )
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=team,
                account=adjustments_account,
                dr_amount=abs_amount,
                cr_amount=Decimal("0"),
            )

        # Create the BankTransaction
        BankTransaction.objects.create(
            team=team,
            account=bank_account,
            amount=-amount if amount > 0 else abs_amount,  # Plaid convention: positive = outflow
            posted_date=datetime.now().date(),
            description="Reconciliation Adjustment",
            source="S",  # System
            journal_entry=journal_entry,
        )

        return journal_entry

    @extend_schema(
        operation_id="bank_feed_batch_unreconcile",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="batch_unreconcile")
    def batch_unreconcile(self, request, team_slug=None):
        """
        Batch unreconcile multiple bank transactions.
        Sets is_reconciled=False on the JournalLine for the bank account side.
        """
        serializer = BatchIdsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ids = serializer.validated_data["ids"]

        # Get transactions that belong to this team
        transactions = BankTransaction.objects.filter(
            id__in=ids,
            team=request.team,
        ).select_related("account", "journal_entry")

        # Mark each transaction's bank account journal line as unreconciled
        for tx in transactions:
            if tx.journal_entry:
                for line in tx.journal_entry.lines.all():
                    if line.account == tx.account:
                        line.is_reconciled = False
                        line.save()
                        break

        return Response(status=status.HTTP_204_NO_CONTENT)


# # Template Views


@login_and_team_required
def bank_feed_home(request, team_slug):
    """
    Main bank feed page view.
    Displays accounts with bank feeds and bank transactions table.
    """
    # Get accounts with bank feeds (with_balance() and with_reconciled_balance() avoid N+1 queries)
    accounts_with_feeds = (
        Account.for_team.filter(has_feed=True)
        .with_balance()
        .with_reconciled_balance()
        .select_related("account_group")
        .order_by("name")
    )  # noqa: E501

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
