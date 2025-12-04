"""
API views for budgeting app.
Keep views thin - delegate business logic to services and selectors.
"""

from datetime import date

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.teams.permissions import TeamModelAccessPermissions

from . import selectors, services
from .models import Account, Budget, Goal, Payee, Transaction
from .serializers import (
    AccountSerializer,
    BalanceSheetReportSerializer,
    BudgetPerformanceReportSerializer,
    BudgetSerializer,
    GoalSerializer,
    IncomeExpenseReportSerializer,
    PayeeSerializer,
    TransactionSerializer,
)


@extend_schema_view(
    create=extend_schema(operation_id="budgeting_accounts_create"),
    list=extend_schema(operation_id="budgeting_accounts_list"),
    retrieve=extend_schema(operation_id="budgeting_accounts_retrieve"),
    update=extend_schema(operation_id="budgeting_accounts_update"),
    partial_update=extend_schema(operation_id="budgeting_accounts_partial_update"),
    destroy=extend_schema(operation_id="budgeting_accounts_destroy"),
)
class AccountViewSet(viewsets.ModelViewSet):
    """ViewSet for Account model."""

    serializer_class = AccountSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return Account.for_team.all()

    def perform_create(self, serializer):
        serializer.save(team=self.request.team)

    @action(detail=False, methods=["get"])
    def by_type(self, request):
        """Get accounts filtered by type."""
        account_type = request.query_params.get("type")
        if not account_type:
            return Response({"error": "type parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        accounts = selectors.get_accounts_by_type(request.team, account_type)
        serializer = self.get_serializer(accounts, many=True)
        return Response(serializer.data)


@extend_schema_view(
    create=extend_schema(operation_id="budgeting_payees_create"),
    list=extend_schema(operation_id="budgeting_payees_list"),
    retrieve=extend_schema(operation_id="budgeting_payees_retrieve"),
    update=extend_schema(operation_id="budgeting_payees_update"),
    partial_update=extend_schema(operation_id="budgeting_payees_partial_update"),
    destroy=extend_schema(operation_id="budgeting_payees_destroy"),
)
class PayeeViewSet(viewsets.ModelViewSet):
    """ViewSet for Payee model."""

    serializer_class = PayeeSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return Payee.for_team.all()

    def perform_create(self, serializer):
        serializer.save(team=self.request.team)


@extend_schema_view(
    create=extend_schema(operation_id="budgeting_transactions_create"),
    list=extend_schema(operation_id="budgeting_transactions_list"),
    retrieve=extend_schema(operation_id="budgeting_transactions_retrieve"),
    update=extend_schema(operation_id="budgeting_transactions_update"),
    partial_update=extend_schema(operation_id="budgeting_transactions_partial_update"),
    destroy=extend_schema(operation_id="budgeting_transactions_destroy"),
)
class TransactionViewSet(viewsets.ModelViewSet):
    """ViewSet for Transaction model."""

    serializer_class = TransactionSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return Transaction.for_team.select_related("payee", "account", "category")

    def perform_create(self, serializer):
        # Use service for business logic
        data = serializer.validated_data
        transaction = services.create_transaction(self.request.team, data)
        serializer.instance = transaction

    def perform_update(self, serializer):
        # Use service for business logic
        data = serializer.validated_data
        transaction = services.update_transaction(serializer.instance.id, data)
        serializer.instance = transaction

    def perform_destroy(self, instance):
        # Use service for business logic
        services.delete_transaction(instance.id)

    @action(detail=False, methods=["get"])
    def for_month(self, request):
        """Get transactions for a specific month."""
        month_str = request.query_params.get("month")
        if not month_str:
            return Response({"error": "month parameter is required (YYYY-MM-DD)"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            month = date.fromisoformat(month_str)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)

        transactions = selectors.get_transactions_for_month(request.team, month)
        serializer = self.get_serializer(transactions, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    @extend_schema(responses={200: IncomeExpenseReportSerializer})
    def income_expense_report(self, request):
        """Generate income/expense report."""
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")

        if not start_date_str or not end_date_str:
            return Response(
                {"error": "start_date and end_date parameters are required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)

        report = selectors.get_income_expense_report(request.team, start_date, end_date)
        serializer = IncomeExpenseReportSerializer(report)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    @extend_schema(responses={200: BalanceSheetReportSerializer})
    def balance_sheet(self, request):
        """Generate balance sheet report."""
        report = selectors.get_balance_sheet(request.team)
        serializer = BalanceSheetReportSerializer(report)
        return Response(serializer.data)


@extend_schema_view(
    create=extend_schema(operation_id="budgeting_budgets_create"),
    list=extend_schema(operation_id="budgeting_budgets_list"),
    retrieve=extend_schema(operation_id="budgeting_budgets_retrieve"),
    update=extend_schema(operation_id="budgeting_budgets_update"),
    partial_update=extend_schema(operation_id="budgeting_budgets_partial_update"),
    destroy=extend_schema(operation_id="budgeting_budgets_destroy"),
)
class BudgetViewSet(viewsets.ModelViewSet):
    """ViewSet for Budget model."""

    serializer_class = BudgetSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return Budget.for_team.select_related("category")

    def perform_create(self, serializer):
        # Use service for business logic
        data = serializer.validated_data
        budget = services.create_budget(self.request.team, data)
        serializer.instance = budget

    def perform_update(self, serializer):
        # Use service for business logic
        data = serializer.validated_data
        budget = services.update_budget(serializer.instance.id, data)
        serializer.instance = budget

    @action(detail=False, methods=["get"])
    @extend_schema(responses={200: BudgetPerformanceReportSerializer})
    def performance(self, request):
        """Get budget performance for a specific month."""
        month_str = request.query_params.get("month")
        if not month_str:
            return Response({"error": "month parameter is required (YYYY-MM-DD)"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            month = date.fromisoformat(month_str)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)

        report = selectors.get_budget_performance(request.team, month)
        serializer = BudgetPerformanceReportSerializer(report)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def bulk_create(self, request):
        """Create multiple budgets for a month."""
        month_str = request.data.get("month")
        budget_data = request.data.get("budgets", [])

        if not month_str:
            return Response({"error": "month is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not budget_data:
            return Response({"error": "budgets array is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            month = date.fromisoformat(month_str)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)

        budgets = services.bulk_create_budgets(request.team, month, budget_data)
        serializer = self.get_serializer(budgets, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    create=extend_schema(operation_id="budgeting_goals_create"),
    list=extend_schema(operation_id="budgeting_goals_list"),
    retrieve=extend_schema(operation_id="budgeting_goals_retrieve"),
    update=extend_schema(operation_id="budgeting_goals_update"),
    partial_update=extend_schema(operation_id="budgeting_goals_partial_update"),
    destroy=extend_schema(operation_id="budgeting_goals_destroy"),
)
class GoalViewSet(viewsets.ModelViewSet):
    """ViewSet for Goal model."""

    serializer_class = GoalSerializer
    permission_classes = [TeamModelAccessPermissions]

    def get_queryset(self):
        return Goal.for_team.all()

    def perform_create(self, serializer):
        serializer.save(team=self.request.team)
