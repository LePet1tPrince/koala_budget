"""
Views for bank_feed app.
Provides API endpoints for imported transactions and unified bank feed.
"""

from decimal import Decimal

from django.http import HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.models import (
    Account,
    Payee,
)
from apps.accounts.serializers import (
    AccountGroupSerializer,
    PayeeSerializer,
    SimpleAccountSerializer,
)
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name
from apps.books.permissions import BookModelAccessPermissions
from apps.budget.services import picker_accounts_data
from apps.journal.services import voiding

from .models import BankTransaction, TransferMatchDismissal
from .serializers import (
    BankFeedRowSerializer,
    BatchEditRequestSerializer,
    BatchIdsSerializer,
    CategorizeTransactionsRequestSerializer,
    CategorySuggestionSerializer,
    FeedAccountSerializer,
    SimilarCategorySuggestionSerializer,
    TransferDismissRequestSerializer,
    TransferMatchRequestSerializer,
    TransferMatchResponseSerializer,
    TransferSuggestionSerializer,
    UploadConfirmRequestSerializer,
    UploadConfirmResponseSerializer,
    UploadParseResponseSerializer,
    UploadPreviewResponseSerializer,
    UploadValidateDatesResponseSerializer,
    bank_transaction_to_feed_row,
)
from .services import batch, feed_query, manual
from .services.csv_upload import create_transactions, parse_file, preview_transactions, validate_date_column
from .services.errors import FeedError, RowsRefused
from .services.feed_accounts import category_groups, create_category_account, feed_accounts
from .services.sample_csv import build_sample_csv
from .services.similar_transactions import suggest_categories
from .services.transfer_detection import find_transfer_candidates
from .services.transfer_match import MatchError, ProposalChanged, match_transfer, propose_pairs

# Upper bound on how many transactions one similar-category request may ask about.
# The categorize view only ever needs the handful of cards it is about to show.
MAX_SIMILAR_CATEGORY_IDS = 50


class ManualTransactionSerializer(serializers.Serializer):
    """Serializer for creating/updating manual transactions."""

    date = serializers.DateField(help_text="Transaction date")
    category = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Category account ID (optional; leave blank to keep the transaction uncategorized)",
    )
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
    splits = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Split this transaction across categories. Each item is "
            '{"category": <account id>, "amount": "<signed decimal>"}, positive for an '
            "outflow. The amounts must add up to outflow - inflow. Mutually exclusive "
            "with `category`."
        ),
    )
    remove_split = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Collapse an existing split back onto the single `category` given. "
            "Required because dropping a split is destructive, so it must be asked "
            "for rather than implied by a request that simply omits `splits`."
        ),
    )

    def validate(self, data):
        inflow = data.get("inflow") or Decimal("0")
        outflow = data.get("outflow") or Decimal("0")
        if inflow < 0 or outflow < 0:
            raise serializers.ValidationError("Inflow and outflow must not be negative.")
        if inflow > 0 and outflow > 0:
            raise serializers.ValidationError("Specify either inflow or outflow, not both.")
        if inflow == 0 and outflow == 0:
            raise serializers.ValidationError("Either inflow or outflow must be greater than zero.")
        # The leg contents are validated by `parse_legs`, so the rules and their
        # wording live in one place; only the either/or belongs here.
        if data.get("splits") is not None and data.get("category") is not None:
            raise serializers.ValidationError("Send either a single category or splits, not both.")
        return data


FEED_QUERY_PARAMETERS = [
    OpenApiParameter(
        name="account",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Comma-separated ledger account ids; absent = every account on a feed",
        required=False,
    ),
    OpenApiParameter(name="view", type=str, enum=["active", "voided"], required=False, description="Void or not"),
    OpenApiParameter(name="to_review", type=bool, required=False, description="Only rows not reconciled"),
    OpenApiParameter(name="reconciled", type=bool, required=False, description="Only reconciled rows"),
    OpenApiParameter(name="uncategorized", type=bool, required=False, description="Only rows with no entry"),
    OpenApiParameter(name="transfers", type=bool, required=False, description="Only possible duplicate transfers"),
    OpenApiParameter(name="start_date", type=OpenApiTypes.DATE, required=False),
    OpenApiParameter(name="end_date", type=OpenApiTypes.DATE, required=False),
    OpenApiParameter(name="sort", type=str, enum=list(feed_query.SORT_KEYS), required=False),
    OpenApiParameter(name="dir", type=str, enum=["asc", "desc"], required=False),
    OpenApiParameter(name="ids", type=str, required=False, description="Comma-separated row ids (at most 1000)"),
    OpenApiParameter(name="page_size", type=int, enum=list(feed_query.PAGE_SIZES), required=False),
    OpenApiParameter(name="counts", type=bool, required=False, description="Add the quick-filter badge counts"),
]


class FeedPagination(PageNumberPagination):
    """Pages of the Inbox table; `page_size` is one of `feed_query.PAGE_SIZES` (checked when parsed)."""

    page_size = feed_query.DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = max(feed_query.PAGE_SIZES)


def _manual_fields(data):
    """`ManualTransactionSerializer`'s validated data as `services/manual.py`'s arguments."""
    return {
        "account_id": data["account"],
        "date": data["date"],
        "category_id": data.get("category"),
        "inflow": data.get("inflow"),
        "outflow": data.get("outflow"),
        "payee": data.get("payee", ""),
        "description": data.get("description", ""),
        "splits": data.get("splits"),
    }


def error_response(error):
    """A refusal a feed service raised (`FeedError`), as the feed's endpoints answer one."""
    return Response({"error": error.message}, status=error.status)


def refused_response(refused):
    """
    A refused batch: nothing was written. `refused` names every row that blocked
    it, so the page can offer to deselect them rather than only report the first.
    """
    return Response({"error": refused[0]["error"], "refused": refused}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema_view(
    list=extend_schema(
        operation_id="bank_feed_feed_list",
        tags=["bank-feed"],
        parameters=FEED_QUERY_PARAMETERS,
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

    - GET /a/{team_slug}/{book_slug}/bankfeed/api/feed/ - Get all bank transactions (filtered by ?account=)
    """

    serializer_class = BankFeedRowSerializer
    permission_classes = [BookModelAccessPermissions]
    pagination_class = FeedPagination
    queryset = BankTransaction.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        """
        The rows the request's params describe, in the requested order, loaded
        for serializing. See `services/feed_query.py` for what each param means.
        """
        if self.action != "list":
            return BankTransaction.objects.filter(book=self.request.book)
        params = self.feed_params
        rows = feed_query.filtered(
            self.request.book,
            params,
            transfer_ids=feed_query.transfer_candidate_ids(self.request.book) if params.transfers else None,
        )
        return self._for_rows(feed_query.ordered(rows, params))

    @staticmethod
    def _for_rows(queryset):
        # Every account a row serializes (its own, its category, a mirror's
        # primary) reads `account_group` for its name and type: load it here,
        # or each row costs a query of its own.
        return queryset.select_related(
            "account__account_group",
            "account__institution",
            "journal_entry",
            "plaid_transaction",
            "plaid_transaction__plaid_account",
            "plaid_transaction__plaid_account__account",
        ).prefetch_related(
            "journal_entry__lines__account__account_group",
            "journal_entry__lines__account__institution",
            "journal_entry__lines__reconciliation",
            "journal_entry__bank_feed_transactions__account__account_group",
            "journal_entry__bank_feed_transactions__account__institution",
        )

    @property
    def feed_params(self):
        if not hasattr(self, "_feed_params"):
            self._feed_params = feed_query.FeedParams.parse(self.request.query_params)
        return self._feed_params

    @extend_schema(
        operation_id="bank_feed_feed_accounts",
        tags=["bank-feed"],
        responses={200: FeedAccountSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def feed_accounts(self, request, team_slug=None, book_slug=None):
        """Return feed accounts with up-to-date balances and review counts."""
        return Response(FeedAccountSerializer(feed_accounts(request.book), many=True).data)

    @extend_schema(
        operation_id="bank_feed_transactions_categorize",
        tags=["bank-feed"],
        request=CategorizeTransactionsRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"])
    def categorize(self, request, team_slug=None, book_slug=None):
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

        try:
            count = batch.categorize(request.book, {row.get("id") for row in rows if row.get("id")}, category_id)
        except FeedError as e:
            return error_response(e)

        log_event(AuditEvent.BULK_CATEGORIZE, request=request, metadata={"count": count})
        return Response(status=status.HTTP_204_NO_CONTENT)

    def list(self, request, team_slug=None, book_slug=None):
        """
        Get unified bank feed, optionally filtered by account.
        One page of the Inbox table: filtered, sorted and paged on the server
        (`services/feed_query.py`). With `counts=1` the response also carries
        the quick-filter badge counts for the request's accounts.
        """
        page = self.paginate_queryset(self.get_queryset())
        rows = [bank_transaction_to_feed_row(tx) for tx in page]
        response = self.get_paginated_response(BankFeedRowSerializer(rows, many=True).data)
        if request.query_params.get("counts") in ("1", "true"):
            response.data["counts"] = feed_query.counts(request.book, self.feed_params)
        return response

    @extend_schema(
        operation_id="bank_feed_selection",
        tags=["bank-feed"],
        parameters=FEED_QUERY_PARAMETERS,
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"], url_path="selection", pagination_class=None)
    def selection(self, request, team_slug=None, book_slug=None):
        """
        Every row matching the filters, as the batch bar reads it: "select all N matching".

        Refused above `MAX_IDS` matches -- a batch write that large is one this
        app does not attempt -- with the count, so the page can say so.
        """
        params = self.feed_params
        rows = feed_query.filtered(
            request.book,
            params,
            transfer_ids=feed_query.transfer_candidate_ids(request.book) if params.transfers else None,
        )
        total = rows.count()
        if total > feed_query.MAX_IDS:
            return Response(
                {
                    "error": f"Narrow the filters to select more than {feed_query.MAX_IDS} transactions.",
                    "count": total,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"count": total, "results": feed_query.selection_rows(feed_query.ordered(rows, params))})

    @extend_schema(
        operation_id="bank_feed_locate",
        tags=["bank-feed"],
        parameters=[
            *FEED_QUERY_PARAMETERS,
            OpenApiParameter(name="row", type=int, required=False, description="The row to find"),
            OpenApiParameter(name="journal_entry", type=int, required=False, description="Find this entry's row..."),
            OpenApiParameter(name="in_account", type=int, required=False, description="...in this account"),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"], url_path="locate", pagination_class=None)
    def locate(self, request, team_slug=None, book_slug=None):
        """
        Which page of the current list a row is on, or `page: null` when the
        filters hide it.

        Name the row by `row`, or by `journal_entry` + `in_account` (the other leg
        of a transfer: the same entry's row in the other account). Answers
        `{id, page, is_void}` -- `id` null when no such row exists at all.
        """
        params = self.feed_params
        target = BankTransaction.objects.filter(book=request.book)
        try:
            if request.query_params.get("row"):
                target = target.filter(pk=int(request.query_params["row"]))
            else:
                target = target.filter(
                    journal_entry_id=int(request.query_params["journal_entry"]),
                    account_id=int(request.query_params["in_account"]),
                )
        except (KeyError, ValueError):
            return Response({"error": "Pass row, or journal_entry and in_account."}, status=status.HTTP_400_BAD_REQUEST)
        found = target.order_by("is_transfer_mirror", "pk").values("pk", "is_void").first()
        if found is None:
            return Response({"id": None, "page": None, "is_void": None})

        rows = feed_query.filtered(
            request.book,
            params,
            transfer_ids=feed_query.transfer_candidate_ids(request.book) if params.transfers else None,
        )
        position = feed_query.position_of(rows, params, found["pk"])
        page = None if position is None else (position - 1) // params.page_size + 1
        return Response({"id": found["pk"], "page": page, "is_void": found["is_void"]})

    def create(self, request, team_slug=None, book_slug=None):
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
        try:
            bank_tx = manual.create_transaction(request.book, **_manual_fields(serializer.validated_data))
        except FeedError as e:
            return error_response(e)
        return Response(
            BankFeedRowSerializer(bank_transaction_to_feed_row(bank_tx)).data, status=status.HTTP_201_CREATED
        )

    def update(self, request, team_slug=None, book_slug=None, pk=None):
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
        - splits / remove_split: see `ManualTransactionSerializer`
        """
        try:
            bank_tx = manual.editable_transaction(request.book, pk)
        except FeedError as e:
            return error_response(e)

        serializer = ManualTransactionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        try:
            bank_tx = manual.update_transaction(
                request.book, bank_tx, **_manual_fields(data), remove_split=data.get("remove_split", False)
            )
        except FeedError as e:
            return error_response(e)
        return Response(BankFeedRowSerializer(bank_transaction_to_feed_row(bank_tx)).data)

    @extend_schema(
        operation_id="bank_feed_sample_csv",
        tags=["bank-feed"],
        responses={(200, "text/csv"): OpenApiTypes.STR},
    )
    @action(detail=False, methods=["get"], url_path="sample_csv")
    def sample_csv(self, request, team_slug=None, book_slug=None):
        """
        Download a sample bank statement CSV.

        For users who want to try the import before they have a statement of
        their own. Nothing is created here -- the file is downloaded and then
        uploaded through the ordinary wizard, so the rows that land in the book's
        books are ones the user knowingly imported.
        """
        response = HttpResponse(build_sample_csv(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="koala-sample-statement.csv"'
        return response

    @extend_schema(
        operation_id="bank_feed_upload_parse",
        tags=["bank-feed"],
        request={
            "multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}
        },  # noqa: E501
        responses={200: UploadParseResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="upload_parse")
    def upload_parse(self, request, team_slug=None, book_slug=None):
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
        operation_id="bank_feed_upload_validate_dates",
        tags=["bank-feed"],
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "date_column": {"type": "integer"},
                    "date_format": {"type": "string"},
                    "has_headers": {"type": "boolean"},
                },
            }
        },
        responses={200: UploadValidateDatesResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="upload_validate_dates")
    def upload_validate_dates(self, request, team_slug=None, book_slug=None):
        """
        Check every row's date cell against the chosen date format.

        Used by the column-mapping step of the upload wizard to warn about rows
        that would be rejected, before the user walks the rest of the wizard.

        Request: multipart/form-data with file, date_column, date_format, has_headers
        Response: total_rows, invalid_count, invalid_samples, suggested_format
        """
        if "file" not in request.FILES:
            return Response(
                {"error": "No file provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            date_column = int(request.data.get("date_column"))
        except (TypeError, ValueError):
            return Response(
                {"error": "Invalid date_column"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if date_column < 0:
            return Response(
                {"error": "Invalid date_column"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        date_format = request.data.get("date_format") or ""
        if not date_format:
            return Response(
                {"error": "No date_format provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        has_headers = str(request.data.get("has_headers", "true")).lower() not in ("false", "0")

        uploaded_file = request.FILES["file"]
        result = validate_date_column(
            file=uploaded_file,
            filename=uploaded_file.name,
            date_col=date_column,
            date_format=date_format,
            has_headers=has_headers,
        )

        serializer = UploadValidateDatesResponseSerializer(
            {
                "total_rows": result.total_rows,
                "invalid_count": result.invalid_count,
                "invalid_samples": [sample.__dict__ for sample in result.invalid_samples],
                "suggested_format": result.suggested_format,
                "error": result.error,
            }
        )
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
    def upload_preview(self, request, team_slug=None, book_slug=None):
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

        # Verify account belongs to book
        try:
            Account.for_book.get(id=account_id)
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
            book=request.book,
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
                "error_field": tx.error_field,
                "raw_date": tx.raw_date,
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
    def upload_confirm(self, request, team_slug=None, book_slug=None):
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

        # Verify account belongs to book
        try:
            Account.for_book.get(id=account_id)
        except Account.DoesNotExist:
            return Response(
                {"error": "Account not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = create_transactions(
            transactions=transactions,
            book=request.book,
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
    def create_account(self, request, team_slug=None, book_slug=None):
        """
        Create a new account for use in the CSV upload category mapping step.
        Body: name (str), account_group_id (int)
        """
        try:
            account = create_category_account(
                request.book, request.data.get("name", "").strip(), request.data.get("account_group_id")
            )
        except FeedError as e:
            return error_response(e)

        serializer = SimpleAccountSerializer(account)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="bank_feed_account_groups",
        tags=["bank-feed"],
        responses={200: AccountGroupSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="account_groups")
    def account_groups(self, request, team_slug=None, book_slug=None):
        """Return all account groups for the book, for use in account creation."""
        serializer = AccountGroupSerializer(category_groups(request.book), many=True)
        return Response(serializer.data)

    @extend_schema(
        operation_id="bank_feed_category_suggestions",
        tags=["bank-feed"],
        responses={200: CategorySuggestionSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="category_suggestions", pagination_class=None)
    def category_suggestions(self, request, team_slug=None, book_slug=None):
        """
        Suggest a category per merchant based on the most recent categorization.
        Used to pre-fill the category when editing an uncategorized transaction.
        """
        transactions = (
            BankTransaction.objects.filter(book=request.book, journal_entry__isnull=False)
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

    @extend_schema(
        operation_id="bank_feed_similar_categories",
        tags=["bank-feed"],
        parameters=[
            OpenApiParameter(
                name="ids",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description=(
                    f"Comma-separated bank transaction ids to suggest categories for "
                    f"(at most {MAX_SIMILAR_CATEGORY_IDS} per request)"
                ),
            )
        ],
        responses={200: SimilarCategorySuggestionSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="similar_categories", pagination_class=None)
    def similar_categories(self, request, team_slug=None, book_slug=None):
        """
        Suggest categories for uncategorized transactions from how similar ones
        were categorized before — matching on payee, on description, or on
        descriptions that share most of their wording.

        Returns a flat list ranked per transaction (strongest match first), each
        item carrying the count behind it so the UI can show why it is suggested.
        """
        raw_ids = (request.query_params.get("ids") or "").split(",")
        ids = []
        for raw_id in raw_ids:
            raw_id = raw_id.strip()
            if not raw_id:
                continue
            if not raw_id.isdigit():
                return Response(
                    {"error": "ids must be a comma-separated list of transaction ids"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            ids.append(int(raw_id))

        if not ids:
            return Response([])
        if len(ids) > MAX_SIMILAR_CATEGORY_IDS:
            return Response(
                {"error": f"At most {MAX_SIMILAR_CATEGORY_IDS} ids may be requested at once"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transactions = BankTransaction.objects.filter(book=request.book, id__in=ids)
        suggestions_by_transaction = suggest_categories(request.book, transactions)

        # Preserve the order the client asked in, so it can pair responses up
        # without re-sorting.
        rows = []
        for transaction_id in ids:
            for suggestion in suggestions_by_transaction.get(transaction_id, ()):
                rows.append({"transaction_id": transaction_id, **suggestion})

        serializer = SimilarCategorySuggestionSerializer(rows, many=True)
        return Response(serializer.data)

    # Batch Operations

    @extend_schema(
        operation_id="bank_feed_batch_edit",
        tags=["bank-feed"],
        request=BatchEditRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["patch"], url_path="batch_edit")
    def batch_edit(self, request, team_slug=None, book_slug=None):
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
        try:
            batch.edit(
                request.book,
                ids,
                category_id=data.get("category_id"),
                account_id=data.get("account_id"),
                payee=data.get("payee"),
                description=data.get("description"),
                date=data.get("date"),
            )
        except RowsRefused as e:
            return refused_response(e.refused)
        except FeedError as e:
            return error_response(e)

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

    @extend_schema(
        operation_id="bank_feed_batch_void",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="batch_void")
    def batch_void(self, request, team_slug=None, book_slug=None):
        """
        Void bank transactions: they and their journal entries count toward nothing.

        A categorized row voids its entry and every row on it (a transfer's other
        leg too); an uncategorized row is voided on its own. All or nothing: a row
        whose entry holds a reconciled line refuses the batch, naming it.
        """
        return self._set_void(request, AuditEvent.BULK_VOID)

    @extend_schema(
        operation_id="bank_feed_batch_restore",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="batch_restore")
    def batch_restore(self, request, team_slug=None, book_slug=None):
        """Restore voided bank transactions, with their entries and their transfers' other legs."""
        return self._set_void(request, AuditEvent.BULK_RESTORE, restore=True)

    def _set_void(self, request, event, restore=False):
        serializer = BatchIdsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            changed_rows = batch.set_void(request.book, serializer.validated_data["ids"], restore=restore)
        except voiding.VoidRefused as exc:
            return refused_response(exc.refused)

        log_event(event, request=request, metadata={"count": len(changed_rows)})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="bank_feed_batch_delete",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="batch_delete")
    def batch_delete(self, request, team_slug=None, book_slug=None):
        """
        Permanently delete voided bank transactions.
        Also deletes any linked journal entries.
        """
        serializer = BatchIdsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ids = serializer.validated_data["ids"]
        batch.delete_void(request.book, ids)

        log_event(AuditEvent.BULK_DELETE, request=request, metadata={"count": len(ids)})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="bank_feed_batch_duplicate",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={200: BankFeedRowSerializer(many=True)},
    )
    @action(detail=False, methods=["post"], url_path="batch_duplicate")
    def batch_duplicate(self, request, team_slug=None, book_slug=None):
        """
        Batch duplicate multiple bank transactions.
        Creates new BankTransaction copies without journal entries, and answers
        with the copies made: reconciled rows are not copied, and a transfer with
        both legs selected is copied once.
        """
        serializer = BatchIdsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        created_transactions = batch.duplicate(request.book, serializer.validated_data["ids"])

        log_event(AuditEvent.BULK_DUPLICATE, request=request, metadata={"count": len(created_transactions)})

        # Return the created transactions as feed rows
        rows = [bank_transaction_to_feed_row(tx) for tx in created_transactions]
        response_serializer = BankFeedRowSerializer(rows, many=True)
        return Response(response_serializer.data)

    @extend_schema(
        operation_id="bank_feed_batch_unreconcile",
        tags=["bank-feed"],
        request=BatchIdsSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="batch_unreconcile")
    def batch_unreconcile(self, request, team_slug=None, book_slug=None):
        """
        Batch unreconcile multiple bank transactions.
        Sets is_reconciled=False on the JournalLine for the bank account side.
        """
        serializer = BatchIdsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ids = serializer.validated_data["ids"]
        batch.unreconcile(request.book, ids)

        log_event(AuditEvent.BULK_UNRECONCILE, request=request, metadata={"count": len(ids)})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="bank_feed_transfer_suggestions",
        tags=["bank-feed"],
        parameters=[
            OpenApiParameter(
                "account",
                OpenApiTypes.INT,
                required=False,
                description="Only pairs with a leg in this account",
            )
        ],
        responses={200: TransferSuggestionSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="transfers", pagination_class=None)
    def transfer_suggestions(self, request, team_slug=None, book_slug=None):
        """
        List likely-duplicate transfer pairs (a transfer reported by both banks).

        Each pair carries both legs and a `proposal`: which leg Match would keep
        and archive, or why Match is unavailable. Read-only; nothing is changed.
        """
        candidates = find_transfer_candidates(request.book)
        # Filter after the book-wide pass: pairing is greedy, so filtering first
        # could pair a leg with a different counterpart than the other feed shows.
        account_id = request.query_params.get("account")
        if account_id:
            try:
                account_id = int(account_id)
            except ValueError:
                return Response({"error": "account must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
            candidates = [p for p in candidates if account_id in (p["outflow"].account_id, p["inflow"].account_id)]
        serializer = TransferSuggestionSerializer(propose_pairs(candidates), many=True)
        return Response(serializer.data)

    @extend_schema(
        operation_id="bank_feed_transfer_match",
        tags=["bank-feed"],
        request=TransferMatchRequestSerializer,
        responses={200: TransferMatchResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="transfers/match")
    def transfer_match(self, request, team_slug=None, book_slug=None):
        """
        Match a duplicate transfer: keep one leg, archive the other.

        The server picks the leg to archive (see `transfer_match.propose`); the
        client sends the one it was shown, and a mismatch is a 409 carrying the
        current proposal. The archived leg's entry is voided and the kept leg is
        categorized as a transfer to the archived leg's account, so one entry
        books both accounts.
        """
        serializer = TransferMatchRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        try:
            result = match_transfer(
                request.book,
                data["transaction_a"],
                data["transaction_b"],
                expected_archive_id=data["expected_archive_id"],
            )
        except BankTransaction.DoesNotExist:
            return Response({"error": "One or both transactions not found."}, status=status.HTTP_404_NOT_FOUND)
        except ProposalChanged as e:
            return Response({"error": str(e), "proposal": e.proposal.as_dict()}, status=status.HTTP_409_CONFLICT)
        except (MatchError, ValueError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        log_event(
            AuditEvent.TRANSFER_DUP_RESOLVED,
            request=request,
            metadata={"mode": "match", **result},
        )
        return Response(TransferMatchResponseSerializer(result).data)

    @extend_schema(
        operation_id="bank_feed_transfer_dismiss",
        tags=["bank-feed"],
        request=TransferDismissRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"], url_path="transfers/dismiss")
    def transfer_dismiss(self, request, team_slug=None, book_slug=None):
        """
        Dismiss a suggested pair as 'not a duplicate' so it stops being suggested.
        """
        serializer = TransferDismissRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        tx_a = serializer.validated_data["transaction_a"]
        tx_b = serializer.validated_data["transaction_b"]

        # Both transactions must belong to this book before recording a dismissal.
        found = set(BankTransaction.objects.filter(id__in=[tx_a, tx_b], book=request.book).values_list("id", flat=True))
        if found != {tx_a, tx_b}:
            return Response(
                {"error": "One or both transactions not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        TransferMatchDismissal.record(request.book, tx_a, tx_b)
        log_event(
            AuditEvent.TRANSFER_DUP_DISMISSED,
            request=request,
            metadata={"transaction_a": tx_a, "transaction_b": tx_b},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# # Template Views


@login_and_book_required
def bank_feed_home(request, team_slug, book_slug):
    """
    Main bank feed page view.
    Displays accounts with bank feeds and bank transactions table.
    """
    # Serialize accounts for React
    accounts_data = FeedAccountSerializer(feed_accounts(request.book), many=True).data

    # Get all accounts, payees, and account groups for dropdowns
    all_payees = Payee.for_book.all().order_by("name")
    all_account_groups = category_groups(request.book).order_by("account_type", "name")

    all_accounts_data = picker_accounts_data(request.book)
    all_payees_data = PayeeSerializer(all_payees, many=True).data
    all_account_groups_data = AccountGroupSerializer(all_account_groups, many=True).data

    # API URLs
    api_urls = {
        "transactions_list": f"/a/{team_slug}/{book_slug}/bankfeed/api/transactions/",
        "transactions_detail": f"/a/{team_slug}/{book_slug}/bankfeed/api/transactions/{{id}}/",
        "feed_list": f"/a/{team_slug}/{book_slug}/bankfeed/api/feed/",
    }

    return render(
        request,
        "bank_feed/bank_feed_home.html",
        {
            "active_tab": "bank-feed",
            "page_title": _("Bank Feed | {name}").format(name=book_display_name(request.book)),
            "accounts": accounts_data,
            "all_accounts": all_accounts_data,
            "all_payees": all_payees_data,
            "all_account_groups": all_account_groups_data,
            "api_urls": api_urls,
        },
    )


@login_and_book_required
def categorize_mode(request, team_slug, book_slug):
    """Categorize mode — gamified single-transaction categorization view."""
    from django.urls import reverse

    all_account_groups = category_groups(request.book).order_by("account_type", "name")
    all_payees = Payee.for_book.all().order_by("name")

    all_accounts_data = picker_accounts_data(request.book)
    all_account_groups_data = AccountGroupSerializer(all_account_groups, many=True).data
    all_payees_data = PayeeSerializer(all_payees, many=True).data

    back_url = reverse("bank_feed:bank_feed_home", kwargs={"team_slug": team_slug, "book_slug": book_slug})

    return render(
        request,
        "bank_feed/categorize_mode.html",
        {
            "page_title": _("Categorize Mode | {name}").format(name=book_display_name(request.book)),
            "all_accounts": all_accounts_data,
            "all_account_groups": all_account_groups_data,
            "all_payees": all_payees_data,
            "back_url": back_url,
        },
    )
