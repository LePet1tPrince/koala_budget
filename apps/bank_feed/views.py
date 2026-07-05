"""
Views for bank_feed app.
Provides API endpoints for imported transactions and unified bank feed.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY, Account, AccountGroup, Payee
from apps.accounts.serializers import (
    AccountGroupSerializer,
    PayeeSerializer,
    SimpleAccountSerializer,
)
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.decorators import login_and_team_required
from apps.teams.permissions import TeamModelAccessPermissions

from .models import BankTransaction, TransferMatchDismissal
from .serializers import (
    BankFeedRowSerializer,
    BatchEditRequestSerializer,
    BatchIdsSerializer,
    BatchReconcileRequestSerializer,
    CategorizeTransactionsRequestSerializer,
    CategorySuggestionSerializer,
    FeedAccountSerializer,
    TransferDismissRequestSerializer,
    TransferResolveRequestSerializer,
    TransferSuggestionSerializer,
    UploadConfirmRequestSerializer,
    UploadConfirmResponseSerializer,
    UploadParseResponseSerializer,
    UploadPreviewResponseSerializer,
    bank_transaction_to_feed_row,
)
from .services.csv_upload import create_transactions, parse_file, preview_transactions
from .services.transfer_detection import find_transfer_candidates
from .services.transfer_mirror import sync_transfer, would_orphan_primary


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

    def validate(self, data):
        inflow = data.get("inflow") or Decimal("0")
        outflow = data.get("outflow") or Decimal("0")
        if inflow < 0 or outflow < 0:
            raise serializers.ValidationError("Inflow and outflow must not be negative.")
        if inflow > 0 and outflow > 0:
            raise serializers.ValidationError("Specify either inflow or outflow, not both.")
        if inflow == 0 and outflow == 0:
            raise serializers.ValidationError("Either inflow or outflow must be greater than zero.")
        return data


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

    class Pagination(PageNumberPagination):
        page_size = 200

    serializer_class = BankFeedRowSerializer
    permission_classes = [TeamModelAccessPermissions]
    pagination_class = Pagination
    queryset = BankTransaction.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        """Get all BankTransactions, optionally filtered by account."""
        queryset = (
            BankTransaction.objects.filter(
                team=self.request.team,
            )
            .select_related(
                "account",
                "account__institution",
                "journal_entry",
                "plaid_transaction",
                "plaid_transaction__plaid_account",
                "plaid_transaction__plaid_account__account",
            )
            .prefetch_related("journal_entry__lines__account__institution")
        )

        # Filter by account if provided in query params
        account_id = self.request.query_params.get("account")
        if account_id:
            queryset = queryset.filter(account_id=account_id)

        return queryset

    @extend_schema(
        operation_id="bank_feed_feed_accounts",
        tags=["bank-feed"],
        responses={200: FeedAccountSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def feed_accounts(self, request, team_slug=None):
        """Return feed accounts with up-to-date balances and review counts."""
        accounts = list(
            Account.for_team.filter(has_feed=True)
            .with_balance()
            .with_categorized_balance()
            .with_reconciled_balance()
            .select_related("account_group", "institution")
            .order_by("name")
        )

        # Computed as a separate query (not chained onto the balance annotations above) to
        # avoid the join fan-out that would inflate the Sum() balances: bank_transactions and
        # journal_lines are different reverse relations, so annotating both in one query would
        # cross-multiply their rows per account.
        uncategorized_counts = dict(
            BankTransaction.objects.filter(
                team=request.team,
                account__has_feed=True,
                journal_entry__isnull=True,
                is_archived=False,
            )
            .values("account_id")
            .annotate(count=Count("id"))
            .values_list("account_id", "count")
        )
        for account in accounts:
            account.uncategorized_count = uncategorized_counts.get(account.id, 0)

        return Response(FeedAccountSerializer(accounts, many=True).data)

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

        # Resolve all transactions up front so a bad id can't partially apply the batch
        tx_ids = {row.get("id") for row in rows if row.get("id")}
        transactions = list(
            BankTransaction.objects.select_related("account", "journal_entry").filter(id__in=tx_ids, team=request.team)
        )
        if len(transactions) != len(tx_ids):
            return Response(
                {"error": "One or more transactions not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            with transaction.atomic():
                for bank_tx in transactions:
                    if bank_tx.journal_entry:
                        # Already categorized: move the category line instead of
                        # creating a duplicate journal entry
                        self._update_journal_category(bank_tx, category_account)
                    else:
                        self._create_journal_from_bank_transaction(
                            transaction_id=bank_tx.id,
                            category_account=category_account,
                            team=request.team,
                        )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        log_event(AuditEvent.BULK_CATEGORIZE, request=request, metadata={"count": len(transactions)})
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
            source=bank_tx.journal_source,
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

        # If this is a transfer to another feed account, surface the counterpart
        # leg in that account's feed (linked to this same entry).
        sync_transfer(bank_tx)

        return journal_entry

    def list(self, request, team_slug=None):
        """
        Get unified bank feed, optionally filtered by account.
        Query params:
        - account: Account ID to filter by (optional)
        - page: Page number (optional)
        """
        # Model Meta ordering (-posted_date, -created_at) gives most-recent-first
        bank_transactions = self.get_queryset()

        page = self.paginate_queryset(bank_transactions)
        rows = [bank_transaction_to_feed_row(tx) for tx in page]
        serializer = BankFeedRowSerializer(rows, many=True)
        return self.get_paginated_response(serializer.data)

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
                source=JournalEntry.SOURCE_MANUAL,
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
                source=BankTransaction.SOURCE_MANUAL,
                journal_entry=journal_entry,
            )

            # Mirror the leg into the counterpart account's feed if it's a transfer.
            sync_transfer(bank_tx)

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

        # Re-pointing the mirror leg to a non-feed category would orphan the real
        # primary transaction; reject it (edit the original transaction instead).
        if would_orphan_primary(bank_tx, category_account):
            return Response(
                {
                    "error": "This is the mirror side of a transfer. Edit the original transaction to change its category."  # noqa: E501
                },
                status=status.HTTP_400_BAD_REQUEST,
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
            # Remember the original bank account so we can still identify the bank-side
            # journal line after the account is reassigned
            old_account = bank_tx.account

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
                    if line.account == old_account or line.account == bank_account:
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
                    source=JournalEntry.SOURCE_MANUAL,
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

            # Keep the transfer's two legs in lockstep — moves/creates/removes the
            # counterpart leg and syncs its display fields, in either direction.
            sync_transfer(bank_tx)

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

        date_format = request.data.get("date_format") or None

        result = preview_transactions(
            file=uploaded_file,
            filename=uploaded_file.name,
            column_mapping=column_mapping,
            category_mappings=category_mappings,
            team=request.team,
            account_id=account_id,
            date_format=date_format,
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
            "unmapped_categories": [uc.__dict__ for uc in result.unmapped_categories],
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

    @extend_schema(
        operation_id="bank_feed_create_account",
        tags=["bank-feed"],
        responses={201: SimpleAccountSerializer},
    )
    @action(detail=False, methods=["post"], url_path="create_account")
    def create_account(self, request, team_slug=None):
        """
        Create a new account for use in the CSV upload category mapping step.
        Body: name (str), account_group_id (int)
        """
        name = request.data.get("name", "").strip()
        account_group_id = request.data.get("account_group_id")

        if not name:
            return Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not account_group_id:
            return Response({"error": "account_group_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            account_group = AccountGroup.for_team.get(id=account_group_id)
        except AccountGroup.DoesNotExist:
            return Response({"error": "Account group not found"}, status=status.HTTP_404_NOT_FOUND)

        if Account.for_team.filter(name__iexact=name).exists():
            return Response({"error": f'An account named "{name}" already exists'}, status=status.HTTP_400_BAD_REQUEST)

        account = Account.objects.create(
            name=name,
            account_group=account_group,
            team=request.team,
            has_feed=account_group.account_type in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY),
        )

        serializer = SimpleAccountSerializer(account)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="bank_feed_account_groups",
        tags=["bank-feed"],
        responses={200: AccountGroupSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="account_groups")
    def account_groups(self, request, team_slug=None):
        """Return all account groups for the team, for use in account creation."""
        groups = AccountGroup.for_team.all()
        serializer = AccountGroupSerializer(groups, many=True)
        return Response(serializer.data)

    @extend_schema(
        operation_id="bank_feed_category_suggestions",
        tags=["bank-feed"],
        responses={200: CategorySuggestionSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="category_suggestions", pagination_class=None)
    def category_suggestions(self, request, team_slug=None):
        """
        Suggest a category per merchant based on the most recent categorization.
        Used to pre-fill the category when editing an uncategorized transaction.
        """
        transactions = (
            BankTransaction.objects.filter(team=request.team, journal_entry__isnull=False)
            .exclude(merchant_name__isnull=True)
            .exclude(merchant_name="")
            .select_related("account")
            .prefetch_related("journal_entry__lines__account")
            .order_by("-posted_date", "-created_at")[:1000]
        )

        suggestions = {}
        for tx in transactions:
            if tx.merchant_name in suggestions:
                continue  # already have a more recent categorization
            category_line = next(
                (line for line in tx.journal_entry.lines.all() if line.account_id != tx.account_id),
                None,
            )
            if category_line:
                suggestions[tx.merchant_name] = {
                    "merchant_name": tx.merchant_name,
                    "category_id": category_line.account_id,
                    "category_name": category_line.account.name,
                }

        serializer = CategorySuggestionSerializer(list(suggestions.values()), many=True)
        return Response(serializer.data)

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

        # Reject up front: re-pointing a mirror leg to a non-feed category would
        # orphan the real primary transaction.
        if category_account is not None:
            for tx in transactions:
                if would_orphan_primary(tx, category_account):
                    return Response(
                        {
                            "error": "This is the mirror side of a transfer. Edit the original transaction to change its category."  # noqa: E501
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

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
                    # Reconciled transactions cannot be moved to another account
                    is_reconciled = (
                        tx.journal_entry
                        and tx.journal_entry.lines.filter(account=tx.account, is_reconciled=True).exists()
                    )
                    if not is_reconciled:
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
                        # Re-save lines so their auto-linked budget follows the new month
                        for line in tx.journal_entry.lines.all():
                            line.save()

                tx.save()

                # Keep a transfer's counterpart leg aligned with any date/payee/desc edit.
                sync_transfer(tx)

        log_event(
            AuditEvent.BULK_EDIT,
            request=request,
            metadata={
                "count": len(ids),
                "fields": [
                    k for k in ["category_id", "account_id", "payee", "description", "date"] if data.get(k) is not None
                ],
            },
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def _update_journal_category(self, bank_tx, new_category_account):
        """Update the category line of an existing journal entry."""
        # Re-pointing the mirror leg to a non-feed category would orphan the real
        # primary transaction; reject it (the user must edit the original instead).
        if would_orphan_primary(bank_tx, new_category_account):
            raise ValueError(
                "This is the mirror side of a transfer. Edit the original transaction to change its category."
            )

        journal_entry = bank_tx.journal_entry
        # Find the category line (the one that's not the bank account)
        for line in journal_entry.lines.all():
            if line.account != bank_tx.account:
                line.account = new_category_account
                line.save()
                break

        # The category drives whether this is a transfer: add/move/remove the
        # counterpart leg (and move the primary if the mirror was re-pointed).
        sync_transfer(bank_tx)

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

        # Per-instance saves (not QuerySet.update) so signals/audit fire and updated_at bumps
        archived_count = 0
        for tx in BankTransaction.objects.filter(id__in=ids, team=request.team).prefetch_related(
            "journal_entry__lines"
        ):
            # Reconciled transactions cannot be archived — skip them silently
            if tx.journal_entry and tx.journal_entry.lines.filter(account=tx.account, is_reconciled=True).exists():
                continue
            tx.is_archived = True
            tx.save(update_fields=["is_archived", "updated_at"])
            archived_count += 1

        log_event(AuditEvent.BULK_ARCHIVE, request=request, metadata={"count": archived_count})
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

        # Per-instance saves (not QuerySet.update) so signals/audit fire and updated_at bumps
        for tx in BankTransaction.objects.filter(id__in=ids, team=request.team):
            tx.is_archived = False
            tx.save(update_fields=["is_archived", "updated_at"])

        log_event(AuditEvent.BULK_UNARCHIVE, request=request, metadata={"count": len(ids)})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="bank_feed_batch_delete",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="batch_delete")
    def batch_delete(self, request, team_slug=None):
        """
        Permanently delete multiple archived bank transactions.
        Also deletes any linked journal entries.
        """
        serializer = BatchIdsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ids = serializer.validated_data["ids"]

        transactions = BankTransaction.objects.filter(
            id__in=ids,
            team=request.team,
            is_archived=True,
        ).select_related("journal_entry")

        selected = list(transactions)
        journal_entry_ids = [tx.journal_entry_id for tx in selected if tx.journal_entry_id]

        # Delete both legs of any transfer being removed (the mirror leg may not be
        # selected or archived), then any selected rows without an entry.
        if journal_entry_ids:
            BankTransaction.objects.filter(journal_entry_id__in=journal_entry_ids).delete()
        BankTransaction.objects.filter(id__in=[tx.id for tx in selected]).delete()

        if journal_entry_ids:
            JournalEntry.objects.filter(id__in=journal_entry_ids).delete()

        log_event(AuditEvent.BULK_DELETE, request=request, metadata={"count": len(ids)})
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

        # Get transactions that belong to this team, excluding reconciled ones
        transactions = (
            BankTransaction.objects.filter(
                id__in=ids,
                team=request.team,
            )
            .select_related("account")
            .prefetch_related("journal_entry__lines")
        )

        transactions = [
            tx
            for tx in transactions
            if not (tx.journal_entry and tx.journal_entry.lines.filter(account=tx.account, is_reconciled=True).exists())
        ]

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
                source=BankTransaction.SOURCE_MANUAL,
                raw={"duplicated_from": tx.id},
                journal_entry=None,
            )
            created_transactions.append(new_tx)

        log_event(AuditEvent.BULK_DUPLICATE, request=request, metadata={"count": len(ids)})

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
        reconciliation_date = serializer.validated_data.get("reconciliation_date") or timezone.localdate()

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

        if not transactions:
            return Response(status=status.HTTP_204_NO_CONTENT)

        # Reconciliation (and any adjustment) only makes sense against a single account
        account_ids = {tx.account_id for tx in transactions}
        if len(account_ids) > 1:
            return Response(
                {"error": "All transactions must belong to the same account to reconcile."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
                    date=reconciliation_date,
                )

        log_event(AuditEvent.BULK_RECONCILE, request=request, metadata={"count": len(ids)})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def _create_reconciliation_adjustment(self, team, bank_account, amount, date=None):
        """
        Create a reconciliation adjustment transaction.
        Creates a BankTransaction and JournalEntry against the system equity
        "Reconciliation Adjustments" account. The adjustment is marked as reconciled immediately.
        """
        from apps.accounts.models import ACCOUNT_TYPE_EQUITY, AccountGroup

        if date is None:
            date = timezone.localdate()

        # Find or create the system equity group for reconciliation adjustments
        equity_group, _ = AccountGroup.objects.get_or_create(
            team=team,
            name="Equity Adjustments",
            defaults={
                "account_type": ACCOUNT_TYPE_EQUITY,
                "is_system": True,
            },
        )
        # Ensure existing group is marked system (in case it was created before this field existed)
        if not equity_group.is_system:
            equity_group.is_system = True
            equity_group.save(update_fields=["is_system"])

        # Find or create the system reconciliation adjustments account
        adjustments_account, _ = Account.objects.get_or_create(
            team=team,
            name="Reconciliation Adjustments",
            defaults={
                "has_feed": False,
                "account_group": equity_group,
                "is_system": True,
            },
        )
        if not adjustments_account.is_system:
            adjustments_account.is_system = True
            adjustments_account.save(update_fields=["is_system"])

        # Create the journal entry
        journal_entry = JournalEntry.objects.create(
            team=team,
            entry_date=date,
            description="Reconciliation Adjustment",
            source=JournalEntry.SOURCE_BANK_MATCH,
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
                is_reconciled=True,
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
                is_reconciled=True,
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
            posted_date=date,
            description="Reconciliation Adjustment",
            source=BankTransaction.SOURCE_SYSTEM,
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

        log_event(AuditEvent.BULK_UNRECONCILE, request=request, metadata={"count": len(ids)})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="bank_feed_transfer_suggestions",
        tags=["bank-feed"],
        responses={200: TransferSuggestionSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="transfers", pagination_class=None)
    def transfer_suggestions(self, request, team_slug=None):
        """
        List likely-duplicate transfer pairs (a transfer reported by both banks).

        Each pair shows both legs so the user can archive the duplicate, archive
        the other side, or dismiss the suggestion. Read-only; nothing is changed.
        """
        candidates = find_transfer_candidates(request.team)
        serializer = TransferSuggestionSerializer(candidates, many=True)
        return Response(serializer.data)

    @extend_schema(
        operation_id="bank_feed_transfer_resolve",
        tags=["bank-feed"],
        request=TransferResolveRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="transfers/resolve")
    def transfer_resolve(self, request, team_slug=None):
        """
        Resolve a duplicate transfer: archive one leg, keep the other.

        Archiving the duplicate leg also voids its journal entry (if categorized)
        so the movement stops double-counting. The kept leg is left untouched for
        the user to categorize as a transfer. Reconciled legs are refused.
        """
        serializer = TransferResolveRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        archive_id = serializer.validated_data["archive_id"]
        keep_id = serializer.validated_data["keep_id"]

        # Both legs must belong to the team (the kept leg is validated but not mutated).
        if not BankTransaction.objects.filter(id=keep_id, team=request.team).exists():
            return Response(
                {"error": "One or both transactions not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            archive_tx = BankTransaction.objects.select_related("journal_entry").get(id=archive_id, team=request.team)
        except BankTransaction.DoesNotExist:
            return Response(
                {"error": "One or both transactions not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # A reconciled leg has been confirmed against a statement; refuse rather
        # than silently voiding reconciled history.
        if (
            archive_tx.journal_entry
            and archive_tx.journal_entry.lines.filter(account=archive_tx.account, is_reconciled=True).exists()
        ):
            return Response(
                {"error": "This transaction is reconciled. Unreconcile it before archiving."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            # Void the duplicate leg's journal entry so it no longer affects any
            # balance (voided entries are excluded everywhere via NOT_VOID).
            entry = archive_tx.journal_entry
            if entry and entry.status != JournalEntry.STATUS_VOID:
                entry.status = JournalEntry.STATUS_VOID
                entry.save(update_fields=["status", "updated_at"])

            archive_tx.archive()

            # If the voided leg had a mirror counterpart on the same entry, archive
            # it too so the voided transfer disappears from both feeds.
            if entry:
                for leg in BankTransaction.objects.filter(journal_entry=entry).exclude(id=archive_tx.id):
                    if not leg.is_archived:
                        leg.archive()

        log_event(
            AuditEvent.TRANSFER_DUP_RESOLVED,
            request=request,
            metadata={"archived_id": archive_id, "kept_id": keep_id},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="bank_feed_transfer_dismiss",
        tags=["bank-feed"],
        request=TransferDismissRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="transfers/dismiss")
    def transfer_dismiss(self, request, team_slug=None):
        """
        Dismiss a suggested pair as 'not a duplicate' so it stops being suggested.
        """
        serializer = TransferDismissRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        tx_a = serializer.validated_data["transaction_a"]
        tx_b = serializer.validated_data["transaction_b"]

        # Both transactions must belong to the team before recording a dismissal.
        found = set(BankTransaction.objects.filter(id__in=[tx_a, tx_b], team=request.team).values_list("id", flat=True))
        if found != {tx_a, tx_b}:
            return Response(
                {"error": "One or both transactions not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        TransferMatchDismissal.record(request.team, tx_a, tx_b)
        log_event(
            AuditEvent.TRANSFER_DUP_DISMISSED,
            request=request,
            metadata={"transaction_a": tx_a, "transaction_b": tx_b},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# # Template Views


@login_and_team_required
def bank_feed_home(request, team_slug):
    """
    Main bank feed page view.
    Displays accounts with bank feeds and bank transactions table.
    """
    # Get accounts with bank feeds (with_balance() and with_reconciled_balance() avoid N+1 queries)
    accounts_with_feeds = list(
        Account.for_team.filter(has_feed=True)
        .with_balance()
        .with_categorized_balance()
        .with_reconciled_balance()
        .select_related("account_group", "institution")
        .order_by("name")
    )  # noqa: E501

    # See feed_accounts() below for why this is a separate query rather than a chained annotation.
    uncategorized_counts = dict(
        BankTransaction.objects.filter(
            team=request.team,
            account__has_feed=True,
            journal_entry__isnull=True,
            is_archived=False,
        )
        .values("account_id")
        .annotate(count=Count("id"))
        .values_list("account_id", "count")
    )
    for account in accounts_with_feeds:
        account.uncategorized_count = uncategorized_counts.get(account.id, 0)

    # Serialize accounts for React
    accounts_data = FeedAccountSerializer(accounts_with_feeds, many=True).data

    # Get all accounts, payees, and account groups for dropdowns
    all_accounts = Account.for_team.select_related("account_group", "institution").order_by("name")
    all_payees = Payee.for_team.all().order_by("name")
    all_account_groups = AccountGroup.for_team.all().order_by("account_type", "name")

    all_accounts_data = SimpleAccountSerializer(all_accounts, many=True).data
    all_payees_data = PayeeSerializer(all_payees, many=True).data
    all_account_groups_data = AccountGroupSerializer(all_account_groups, many=True).data

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
            "all_account_groups": all_account_groups_data,
            "api_urls": api_urls,
            "team_slug": team_slug,
        },
    )


@login_and_team_required
def categorize_mode(request, team_slug):
    """Categorize mode — gamified single-transaction categorization view."""
    from django.urls import reverse

    all_accounts = Account.for_team.select_related("account_group", "institution").order_by("name")
    all_account_groups = AccountGroup.for_team.all().order_by("account_type", "name")

    all_accounts_data = SimpleAccountSerializer(all_accounts, many=True).data
    all_account_groups_data = AccountGroupSerializer(all_account_groups, many=True).data

    back_url = reverse("bank_feed:bank_feed_home", kwargs={"team_slug": team_slug})

    return render(
        request,
        "bank_feed/categorize_mode.html",
        {
            "page_title": _("Categorize Mode | {team}").format(team=request.team),
            "all_accounts": all_accounts_data,
            "all_account_groups": all_account_groups_data,
            "team_slug": team_slug,
            "back_url": back_url,
        },
    )
