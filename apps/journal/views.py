"""
Views for journal app.
Provides both template views and REST API endpoints for journal entries and lines.
"""

from django.db.models import CharField, Q
from django.db.models.functions import Cast
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.models import Account
from apps.audit.models import AuditLog
from apps.audit.serializers import AuditLogSerializer
from apps.reconciliation.services.guards import ReconciledLineError, assert_entry_voidable, assert_line_mutable
from apps.teams.decorators import login_and_team_required
from apps.teams.permissions import TeamModelAccessPermissions

from .filters import (
    COLUMNS,
    annotations_for,
    apply_column_filters,
    apply_ordering,
    facet_values,
)
from .models import JournalEntry, JournalLine, counted_entries
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

        # Voiding drops every line out of every balance, reconciled ones included.
        try:
            assert_entry_voidable(journal_entry)
        except ReconciledLineError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        journal_entry.status = JournalEntry.STATUS_VOID
        journal_entry.save()

        serializer = self.get_serializer(journal_entry)
        return Response(serializer.data)

    @extend_schema(operation_id="journal_entries_audit", tags=["journal"], responses=AuditLogSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="audit")
    def audit(self, request, team_slug=None, pk=None):
        """Return the row-level audit history for this journal entry and its lines."""
        entry = self.get_object()
        logs = AuditLog.objects.filter(journal_entry_id=entry.pk).select_related("user", "event").order_by("-timestamp")
        serializer = AuditLogSerializer(logs, many=True)
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
        qs = (
            JournalLine.objects.filter(
                team=self.request.team,
            )
            .select_related(
                "account",
                "account__account_group",
                "journal_entry",
                "journal_entry__payee",
            )
            .prefetch_related("journal_entry__lines__account")
        )
        if self.action == "list":
            # A listing mirrors the balances it explains: voided and archived entries count nowhere.
            qs = qs.filter(counted_entries("journal_entry__"))

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
        responses={
            200: {"type": "object", "properties": {"status": {"type": "string"}, "line_id": {"type": "integer"}}}
        },  # noqa: E501
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

        new_category = get_object_or_404(Account.objects.filter(team=self.request.team), id=new_category_id)

        # A line moved onto an account the entry already posts to on the *other*
        # side (e.g. the bank account the money came through) cancels itself out.
        other_side = {"cr_amount__gt": 0} if line.dr_amount > 0 else {"dr_amount__gt": 0}
        if line.journal_entry.lines.exclude(pk=line.pk).filter(account=new_category, **other_side).exists():
            return Response(
                {"error": _("The transaction already uses that account on its other side.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            assert_line_mutable(line, new_account=new_category)
        except ReconciledLineError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        line.account = new_category
        line.save()

        # Moving the category side onto another feed account turns the entry into a
        # transfer, which the bank feed shows in both accounts via a mirror leg.
        from apps.bank_feed.models import BankTransaction
        from apps.bank_feed.services.transfer_mirror import sync_transfer

        primary = BankTransaction.objects.filter(journal_entry=line.journal_entry, is_transfer_mirror=False).first()
        if primary is not None:
            sync_transfer(primary)

        return Response({"status": "success", "line_id": line.id})


TRANSACTION_QUERY_PARAMS = [
    OpenApiParameter(
        name="search",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Case-insensitive search across payee, description, account name, and amount",
        required=False,
    ),
    OpenApiParameter(
        name="start_date",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Only include entries on or after this date (YYYY-MM-DD)",
        required=False,
    ),
    OpenApiParameter(
        name="end_date",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Only include entries on or before this date (YYYY-MM-DD)",
        required=False,
    ),
    OpenApiParameter(
        name="f_{column}",
        type=str,
        location=OpenApiParameter.QUERY,
        description=(
            "Per-column value filter, repeated once per selected value, e.g. `f_payee=Amazon&f_payee=Costco`. "
            f"Columns: {', '.join(COLUMNS)}. An empty value selects rows with no value in that column. "
            "Hierarchical columns take a branch as one value: `f_date=2025` (year), `f_date=2025-03` (month), "
            "`f_debit_account=t:income` (type), `g:12` (group), `a:34` (account)."
        ),
        required=False,
    ),
    OpenApiParameter(
        name="sort",
        type=str,
        location=OpenApiParameter.QUERY,
        description=f"Column to sort by: {', '.join(COLUMNS)}. Defaults to newest first.",
        required=False,
    ),
    OpenApiParameter(
        name="dir",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Sort direction, `asc` (default) or `desc`. Ignored without `sort`.",
        required=False,
    ),
]


@extend_schema_view(
    list=extend_schema(
        operation_id="transactions_list",
        tags=["journal"],
        parameters=TRANSACTION_QUERY_PARAMS,
    ),
)
class TransactionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Read-only list of journal entries flattened into transaction rows.

    Voided entries and entries behind an archived bank transaction are left out:
    they count toward no balance, so they are not on the ledger either.

    Every other entry is returned, including splits -- an entry apportioned across
    several categories, which has one line on one side and several on the other.
    This list used to filter to ``line_count=2``, which silently hid every split
    from the page that presents itself as the ledger, and from its filters,
    facet counts and CSV export.  A split row reports ``Split (N)`` on its
    many-line side and carries its ``legs`` for the table's disclosure.

    Search, date range, per-column value filters and sorting all run as query
    params so that they apply to the whole ledger, not just whatever page the
    client has fetched so far.  `facets/` lists a column's distinct values so
    the table's column menus can offer them.
    """

    class Pagination(PageNumberPagination):
        page_size = 200

    serializer_class = TransactionRowSerializer
    permission_classes = [TeamModelAccessPermissions]
    pagination_class = Pagination

    def base_queryset(self, *, facet_column=None):
        """
        Team transactions, annotated for whichever columns this request reads.

        The derived columns are correlated subqueries, so they are applied only
        when something actually sorts, filters or faceting reads them -- an
        unfiltered list pays for none of them.
        """
        return (
            JournalEntry.for_team.filter(counted_entries())
            .select_related("payee")
            .prefetch_related("lines__account")
            .annotate(**annotations_for(self.request.query_params, facet_column=facet_column))
        )

    def filtered_queryset(self, *, exclude_column=None, facet_column=None):
        """
        Apply search, date range and column filters.

        `exclude_column` leaves one column's own filter off, which is what a
        facet list needs: it has to keep offering the values the user has not
        ticked, or unticking one would be impossible.
        """
        queryset = self.base_queryset(facet_column=facet_column)
        params = self.request.query_params

        start_date = parse_date(params.get("start_date") or "")
        end_date = parse_date(params.get("end_date") or "")
        if start_date:
            queryset = queryset.filter(entry_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(entry_date__lte=end_date)

        search = (params.get("search") or "").strip()
        if search:
            matching_line_entries = (
                JournalLine.for_team.annotate(
                    dr_str=Cast("dr_amount", CharField()),
                    cr_str=Cast("cr_amount", CharField()),
                )
                .filter(Q(account__name__icontains=search) | Q(dr_str__icontains=search) | Q(cr_str__icontains=search))
                .values_list("journal_entry_id", flat=True)
            )
            queryset = queryset.filter(
                Q(payee__name__icontains=search) | Q(description__icontains=search) | Q(id__in=matching_line_entries)
            )

        return apply_column_filters(queryset, params, self.request.team, exclude=exclude_column)

    def get_queryset(self):
        return apply_ordering(self.filtered_queryset(), self.request.query_params)

    @extend_schema(
        operation_id="transactions_facets",
        tags=["journal"],
        parameters=[
            *TRANSACTION_QUERY_PARAMS,
            OpenApiParameter(
                name="column",
                type=str,
                location=OpenApiParameter.QUERY,
                description=f"Column whose distinct values to list: {', '.join(COLUMNS)}.",
                required=True,
            ),
            OpenApiParameter(
                name="q",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Narrow the returned values to those containing this text.",
                required=False,
            ),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "hierarchical": {"type": "boolean"},
                    "truncated": {"type": "boolean"},
                    "values": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "value": {"type": "string"},
                                "label": {"type": "string"},
                                "count": {"type": "integer"},
                            },
                        },
                    },
                },
            }
        },
    )
    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request, team_slug=None):
        """
        List the values one column offers, with the row count behind each.

        The counts reflect the search, date range and *other* columns' filters
        that are currently applied, so they say what ticking a value would
        actually show.  A hierarchical column (dates, the two account columns)
        nests them under `children`, and a branch is selectable in its own
        right -- ticking a year means every date in it.
        """
        column = COLUMNS.get((request.query_params.get("column") or "").strip())
        if column is None:
            return Response(
                {"error": f"Unknown column. Expected one of: {', '.join(COLUMNS)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.filtered_queryset(exclude_column=column.key, facet_column=column.key)
        query = (request.query_params.get("q") or "").strip()
        return Response(facet_values(queryset, column, request.team, query=query))


@login_and_team_required
def transactions_home(request, team_slug):
    """Transactions list page - renders the React-powered transactions table."""
    api_urls = {
        "transactions_list": f"/a/{team_slug}/journal/api/transactions/",
        "transactions_facets": f"/a/{team_slug}/journal/api/transactions/facets/",
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
