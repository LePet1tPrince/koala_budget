"""
API views for journal app.
Provides REST API endpoints for journal entries and lines.
"""

from django.db.models import Count
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.teams.permissions import TeamModelAccessPermissions

from .models import JournalEntry
from .serializers import JournalEntrySerializer, SimpleTransactionSerializer


@extend_schema_view(
    create=extend_schema(operation_id="journal_entries_create"),
    list=extend_schema(operation_id="journal_entries_list"),
    retrieve=extend_schema(operation_id="journal_entries_retrieve"),
    update=extend_schema(operation_id="journal_entries_update"),
    partial_update=extend_schema(operation_id="journal_entries_partial_update"),
    destroy=extend_schema(operation_id="journal_entries_destroy"),
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
    def post_entry(self, request, pk=None):
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
    def void_entry(self, request, pk=None):
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
    create=extend_schema(operation_id="simple_transactions_create"),
    list=extend_schema(operation_id="simple_transactions_list"),
    retrieve=extend_schema(operation_id="simple_transactions_retrieve"),
    update=extend_schema(operation_id="simple_transactions_update"),
    partial_update=extend_schema(operation_id="simple_transactions_partial_update"),
    destroy=extend_schema(operation_id="simple_transactions_destroy"),
)
class SimpleTransactionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for simplified transaction interface.
    Provides CRUD operations for transactions using a simple format
    that gets converted to journal entries behind the scenes.

    This is designed for client applications that want a simple
    transaction model without dealing with double-entry bookkeeping.
    """

    serializer_class = SimpleTransactionSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        """
        Get journal entries for the current team.
        Only returns entries with exactly 2 lines (simple transactions).
        """
        return (
            JournalEntry.for_team.select_related("payee")
            .prefetch_related("lines__account__account_group")
            .annotate(line_count=Count("lines"))
            .filter(line_count=2)
        )

    def perform_create(self, serializer):
        """Create transaction with team context."""
        serializer.save()

    def perform_update(self, serializer):
        """Update transaction with team context."""
        serializer.save()
