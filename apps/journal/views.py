"""
Views for journal app.
Provides both template views and REST API endpoints for journal entries and lines.
"""

from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Account
from apps.teams.decorators import login_and_team_required
from apps.teams.permissions import TeamModelAccessPermissions

from .models import JournalEntry, JournalLine
from .serializers import JournalEntrySerializer, SimpleLineSerializer, TransactionRowSerializer


@extend_schema_view(
    create=extend_schema(operation_id="journal_entries_create", tags=["journal"]),
    list=extend_schema(operation_id="journal_entries_list", tags=["journal"]),
    retrieve=extend_schema(operation_id="journal_entries_retrieve", tags=["journal"]),
    update=extend_schema(operation_id="journal_entries_update", tags=["journal"]),
    partial_update=extend_schema(operation_id="journal_entries_partial_update", tags=["journal"]),
    destroy=extend_schema(operation_id="journal_entries_destroy", tags=["journal"]),
)
class JournalEntryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for JournalEntry model.
    Provides CRUD operations for journal entries with nested lines.
    """

    serializer_class = JournalEntrySerializer
    permission_classes = [TeamModelAccessPermissions]
    queryset = JournalEntry.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        """Get journal entries for the current team with optimized queries."""
        return JournalEntry.for_team.select_related("payee").prefetch_related("lines__account")

    def perform_create(self, serializer):
        """Create journal entry with team context."""
        serializer.save(team=self.request.team)

    @action(detail=True, methods=["post"])
    def post_entry(self, request, pk=None, team_slug=None):
        """
        Post a draft journal entry (change status to posted).
        Only draft entries can be posted.
        """
        journal_entry = self.get_object()

        if journal_entry.status != JournalEntry.STATUS_DRAFT:
            return Response(
                {"error": "Only draft entries can be posted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not journal_entry.is_balanced:
            return Response(
                {"error": "Cannot post an unbalanced journal entry."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        journal_entry.status = JournalEntry.STATUS_POSTED
        journal_entry.save()

        serializer = self.get_serializer(journal_entry)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def void_entry(self, request, pk=None, team_slug=None):
        """
        Void a posted journal entry.
        Only posted entries can be voided.
        """
        journal_entry = self.get_object()

        if journal_entry.status != JournalEntry.STATUS_POSTED:
            return Response(
                {"error": "Only posted entries can be voided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        journal_entry.status = JournalEntry.STATUS_VOID
        journal_entry.save()

        serializer = self.get_serializer(journal_entry)
        return Response(serializer.data)


@extend_schema_view(
    create=extend_schema(operation_id="simple_lines_create", tags=["journal"]),
    list=extend_schema(
        operation_id="simple_lines_list",
        tags=["journal"],
        parameters=[
            OpenApiParameter(
                name="account",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Filter by account ID (category)",
                required=False,
            ),
            OpenApiParameter(
                name="month",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter by month (YYYY-MM-DD format, uses first day of month)",
                required=False,
            ),
        ],
    ),
    retrieve=extend_schema(operation_id="simple_lines_retrieve", tags=["journal"]),
    update=extend_schema(operation_id="simple_lines_update", tags=["journal"]),
    partial_update=extend_schema(operation_id="simple_lines_partial_update", tags=["journal"]),
    destroy=extend_schema(operation_id="simple_lines_destroy", tags=["journal"]),
)
class SimpleLineViewSet(viewsets.ModelViewSet):
    """
    ViewSet for simplified line interface.
    Provides CRUD operations for journal lines using a simple format
    that presents data from the line, parent journal entry, and sibling line.

    This is designed for displaying transactions from the perspective of a single account,
    similar to a bank register view.

    For create/update operations:
    - Creates/updates a journal entry with exactly 2 lines
    - The main line uses the specified account with inflow/outflow amounts
    - The sibling line uses the category account with opposite amounts

    Query parameters for filtering:
    - account: Filter by account ID (useful for getting all transactions in a category)
    - month: Filter by month (YYYY-MM-DD format, uses first day of month)
    """

    serializer_class = SimpleLineSerializer
    permission_classes = [TeamModelAccessPermissions]
    queryset = JournalLine.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        """
        Get journal lines for the current team.
        Optimized with select_related and prefetch_related for performance.

        Supports filtering by:
        - account: Account ID to filter by
        - month: Month to filter by (YYYY-MM-DD format)
        """
        qs = JournalLine.objects.filter(
            team=self.request.team,
        ).select_related(
            "account",
            "account__account_group",
            "journal_entry",
            "journal_entry__payee",
        ).prefetch_related("journal_entry__lines__account")

        # Filter by account (category) if provided
        account_id = self.request.query_params.get("account")
        if account_id:
            qs = qs.filter(account_id=account_id)

        # Filter by month if provided
        month_param = self.request.query_params.get("month")
        if month_param:
            month = parse_date(month_param)
            if month:
                start = month.replace(day=1)
                if start.month == 12:
                    end = start.replace(year=start.year + 1, month=1)
                else:
                    end = start.replace(month=start.month + 1)
                qs = qs.filter(
                    journal_entry__entry_date__gte=start,
                    journal_entry__entry_date__lt=end,
                )

        return qs.order_by("-journal_entry__entry_date")

    def perform_create(self, serializer):
        """Create line with team context."""
        serializer.save()

    def perform_update(self, serializer):
        """Update line with team context."""
        serializer.save()

    def perform_destroy(self, instance):
        """Delete the entire journal entry when deleting a line."""
        journal_entry = instance.journal_entry
        journal_entry.delete()

    @extend_schema(
        operation_id="simple_lines_recategorize",
        tags=["journal"],
        request={"application/json": {"type": "object", "properties": {"new_category_id": {"type": "integer"}}}},
        responses={200: {"type": "object", "properties": {"status": {"type": "string"}, "line_id": {"type": "integer"}}}},
    )
    @action(detail=True, methods=["post"])
    def recategorize(self, request, pk=None, team_slug=None):
        """
        Recategorize a journal line to a different account/category.

        This changes the account on a single journal line, effectively moving
        the transaction to a different budget category.

        POST body:
        {
            "new_category_id": 456
        }
        """
        line = self.get_object()
        new_category_id = request.data.get("new_category_id")

        if not new_category_id:
            return Response(
                {"error": "new_category_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_category = get_object_or_404(
            Account.objects.filter(team=self.request.team),
            id=new_category_id
        )
        line.account = new_category
        line.save()

        return Response({"status": "success", "line_id": line.id})


@extend_schema_view(
    list=extend_schema(operation_id="transactions_list", tags=["journal"]),
)
class TransactionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Read-only list of journal entries flattened into transaction rows.
    Only entries with exactly 2 lines are returned (simple debit/credit pairs).
    """

    serializer_class = TransactionRowSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return (
            JournalEntry.for_team
            .select_related("payee")
            .prefetch_related("lines__account")
            .annotate(line_count=Count("lines"))
            .filter(line_count=2)
            .order_by("-entry_date", "-created_at")
        )


@login_and_team_required
def transactions_home(request, team_slug):
    """Transactions list page - renders the React-powered transactions table."""
    api_urls = {
        "transactions_list": f"/a/{team_slug}/journal/api/transactions/",
    }

    return render(
        request,
        "journal/transactions_home.html",
        {
            "active_tab": "transactions",
            "page_title": _("Transactions | {team}").format(team=request.team),
            "api_urls": api_urls,
            "team_slug": team_slug,
        },
    )
