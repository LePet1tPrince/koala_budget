from django.shortcuts import render
from rest_framework import viewsets
from drf_spectacular.utils import extend_schema, extend_schema_view
from .models import Budget
from .serializers import BudgetSerializer
from apps.core.permissions import TeamModelAccessPermissions

@extend_schema_view(
    create=extend_schema(operation_id="budgets_create", tags=["budget"]),
    list=extend_schema(operation_id="budgets_list", tags=["budget"]),
    retrieve=extend_schema(operation_id="budgets_retrieve", tags=["budget"]),
    update=extend_schema(operation_id="budgets_update", tags=["budget"]),
    partial_update=extend_schema(operation_id="budgets_partial_update", tags=["budget"]),
    destroy=extend_schema(operation_id="budgets_destroy", tags=["budget"]),
)
class BudgetViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Budget model.
    Provides CRUD operations for budgets with nested lines.
    """

    serializer_class = BudgetSerializer
    permission_classes = [TeamModelAccessPermissions]


    def get_queryset(self):
        """Get budgets for the current team with optimized queries."""
        qs = (
            Budget.objects.filter(team=self.request.user.team)
            .with_actual_amount()
            .prefetch_related(
                "journal_lines",
                "journal_lines__journal_entry",
                )
        )

        month = self.request.query_params.get("month")
        if month:
            qs = qs.filter(month=month)
        return qs

    def perform_create(self, serializer):
        """Create Budget with team context."""
        serializer.save(team=self.request.team)