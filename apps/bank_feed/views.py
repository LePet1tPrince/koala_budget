"""
Views for bank_feed app.
Provides API endpoints for imported transactions.
"""

from datetime import datetime

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets

from apps.teams.permissions import TeamModelAccessPermissions

from .models import BankTransaction
from .serializers import BankTransactionSerializer


@extend_schema_view(
    list=extend_schema(
        operation_id="bank_feed_transactions_list",
        tags=["bank-feed"],
        parameters=[
            OpenApiParameter(
                name="source",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter by source (plaid, csv, manual)",
                required=False,
            ),
            OpenApiParameter(
                name="account",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Filter by ledger account ID",
                required=False,
            ),
            OpenApiParameter(
                name="date_from",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter by date (from), format: YYYY-MM-DD",
                required=False,
            ),
            OpenApiParameter(
                name="date_to",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter by date (to), format: YYYY-MM-DD",
                required=False,
            ),
            OpenApiParameter(
                name="is_categorized",
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Filter by categorization status",
                required=False,
            ),
            OpenApiParameter(
                name="pending",
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Filter by pending status",
                required=False,
            ),
        ],
    ),
    retrieve=extend_schema(
        operation_id="bank_feed_transactions_retrieve",
        tags=["bank-feed"],
    ),
)
class BankTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for BankTransaction model.
    Provides read-only access to imported transactions from all sources (Plaid, CSV, manual).
    """

    serializer_class = BankTransactionSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        queryset = BankTransaction.objects.filter(team=self.request.team).select_related(
            "plaid_account",
            "plaid_account__account",
            "journal_entry",
        )

        # Apply filters from query params
        params = self.request.query_params

        # Filter by source
        source = params.get("source")
        if source:
            queryset = queryset.filter(source=source)

        # Filter by account (plaid_account__account_id)
        account = params.get("account")
        if account:
            queryset = queryset.filter(plaid_account__account_id=account)

        # Filter by date range
        date_from = params.get("date_from")
        if date_from:
            try:
                date_from = datetime.strptime(date_from, "%Y-%m-%d").date()
                queryset = queryset.filter(date__gte=date_from)
            except ValueError:
                pass  # Ignore invalid date format

        date_to = params.get("date_to")
        if date_to:
            try:
                date_to = datetime.strptime(date_to, "%Y-%m-%d").date()
                queryset = queryset.filter(date__lte=date_to)
            except ValueError:
                pass  # Ignore invalid date format

        # Filter by categorization status
        is_categorized = params.get("is_categorized")
        if is_categorized is not None:
            if is_categorized.lower() == "true":
                queryset = queryset.filter(journal_entry__isnull=False)
            elif is_categorized.lower() == "false":
                queryset = queryset.filter(journal_entry__isnull=True)

        # Filter by pending status
        pending = params.get("pending")
        if pending is not None:
            if pending.lower() == "true":
                queryset = queryset.filter(pending=True)
            elif pending.lower() == "false":
                queryset = queryset.filter(pending=False)

        return queryset
