"""
Views for journal app.
Provides both template views and REST API endpoints for journal entries and lines.
"""

from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Account, Payee
from apps.accounts.serializers import AccountSerializer, PayeeSerializer
from apps.teams.decorators import login_and_team_required
from apps.teams.permissions import TeamModelAccessPermissions

from .models import JournalEntry, JournalLine
from .serializers import JournalEntrySerializer, SimpleLineSerializer


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
    list=extend_schema(operation_id="simple_lines_list", tags=["journal"]),
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
    """

    serializer_class = SimpleLineSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        """
        Get journal lines for the current team.
        Optimized with select_related and prefetch_related for performance.
        """
        return JournalLine.for_team.select_related("account", "journal_entry", "journal_entry__payee").prefetch_related(
            "journal_entry__lines__account"
        )

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


# Template Views


@login_and_team_required
def journal_home(request, team_slug):
    """
    Main journal page view.
    Displays accounts with bank feeds and transactions table.
    """
    # Get accounts with bank feeds
    accounts_with_feeds = Account.for_team.filter(has_feed=True).select_related("account_group").order_by("name")

    # Serialize accounts for React
    accounts_data = AccountSerializer(accounts_with_feeds, many=True).data

    # Get all accounts and payees for dropdowns
    all_accounts = Account.for_team.all().order_by("account_number")
    all_payees = Payee.for_team.all().order_by("name")

    all_accounts_data = AccountSerializer(all_accounts, many=True).data
    all_payees_data = PayeeSerializer(all_payees, many=True).data

    # API URLs
    api_urls = {
        "transactions_list": f"/a/{team_slug}/journal/api/transactions/",
        "transactions_detail": f"/a/{team_slug}/journal/api/transactions/{{id}}/",
    }

    return render(
        request,
        "journal/journal_home.html",
        {
            "active_tab": "journal",
            "page_title": _("Journal | {team}").format(team=request.team),
            "accounts": accounts_data,
            "all_accounts": all_accounts_data,
            "all_payees": all_payees_data,
            "api_urls": api_urls,
            "team_slug": team_slug,
        },
    )


@login_and_team_required
def journal_lines(request, team_slug):
    """
    Journal lines page view.
    Displays accounts with bank feeds and lines table.
    """
    # Get accounts with bank feeds
    accounts_with_feeds = Account.for_team.filter(has_feed=True).select_related("account_group").order_by("name")

    # Serialize accounts for React
    accounts_data = AccountSerializer(accounts_with_feeds, many=True).data

    # Get all accounts and payees for dropdowns
    all_accounts = Account.for_team.all().order_by("account_number")
    all_payees = Payee.for_team.all().order_by("name")

    all_accounts_data = AccountSerializer(all_accounts, many=True).data
    all_payees_data = PayeeSerializer(all_payees, many=True).data

    # API URLs
    api_urls = {
        "lines_list": f"/a/{team_slug}/journal/api/lines/",
        "lines_detail": f"/a/{team_slug}/journal/api/lines/{{id}}/",
    }

    return render(
        request,
        "journal/journal_lines.html",
        {
            "active_tab": "journal",
            "page_title": _("Journal Lines | {team}").format(team=request.team),
            "accounts": accounts_data,
            "all_accounts": all_accounts_data,
            "all_payees": all_payees_data,
            "api_urls": api_urls,
            "team_slug": team_slug,
        },
    )
