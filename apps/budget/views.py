from datetime import date

from django.shortcuts import render
from rest_framework import viewsets
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.teams.decorators import login_and_team_required
from apps.teams.permissions import TeamModelAccessPermissions

from .services import BudgetService
from .serializers import BudgetSerializer
from .models import Budget
# from .serializers import BudgetListSerializer

# @extend_schema_view(
#     create=extend_schema(operation_id="budgets_create", tags=["budget"]),
#     list=extend_schema(operation_id="budgets_list", tags=["budget"]),
#     retrieve=extend_schema(operation_id="budgets_retrieve", tags=["budget"]),
#     update=extend_schema(operation_id="budgets_update", tags=["budget"]),
#     partial_update=extend_schema(operation_id="budgets_partial_update", tags=["budget"]),
#     destroy=extend_schema(operation_id="budgets_destroy", tags=["budget"]),
# )
# class BudgetViewSet(viewsets.ModelViewSet):
#     """
#     ViewSet for Budget model.
#     Provides CRUD operations for budgets with nested lines.
#     """

#     serializer_class = BudgetListSerializer
#     permission_classes = [TeamModelAccessPermissions]


#     def get_queryset(self):
#         """Get budgets for the current team with optimized queries."""
#         qs = (
#             Budget.objects.filter(team=self.request.user.team)
#             .with_actual_amount()
#             .prefetch_related(
#                 "journal_lines",
#                 "journal_lines__journal_entry",
#                 )
#         )

#         month = self.request.query_params.get("month")
#         if month:
#             qs = qs.filter(month=month)
#         return qs

#     def perform_create(self, serializer):
#         """Create Budget with team context."""
#         serializer.save(team=self.request.team)


# apps/budget/api/views.py



@extend_schema_view(
    create=extend_schema(operation_id="budgets_create", tags=["budget"]),
    list=extend_schema(operation_id="budgets_list", tags=["budget"],
            parameters=[
            OpenApiParameter(
                name="month",
                description="Budget month (first day of month, YYYY-MM-01)",
                required=True,
                type=str,
                location=OpenApiParameter.QUERY,
            )
            ],
            ),
    # retrieve=extend_schema(operation_id="budgets_retrieve", tags=["budget"]),
    # update=extend_schema(operation_id="budgets_update", tags=["budget"]),
    # partial_update=extend_schema(operation_id="budgets_partial_update", tags=["budget"]),
    # destroy=extend_schema(operation_id="budgets_destroy", tags=["budget"]),
)
class BudgetViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request, **kwargs):
        month_str = request.query_params.get("month")
        if not month_str:
            return Response(
                {"detail": "month query param required (YYYY-MM-01)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        month = date.fromisoformat(month_str)

        service = BudgetService(team=request.team)
        rows = service.build_budget_rows(month)

        return Response(rows)

    def create(self, request):
        serializer = BudgetSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        budget = serializer.save()

        return Response(
            BudgetSerializer(budget).data,
            status=status.HTTP_201_CREATED,
        )



@login_and_team_required
def budget_home(request, team_slug):
    """
    Main journal page view.
    Displays accounts with bank feeds and transactions table.
    """
    # Get accounts with bank feeds
    # accounts_with_feeds = Account.for_team.filter(has_feed=True).select_related("account_group").order_by("name")

    # # Serialize accounts for React
    # accounts_data = AccountSerializer(accounts_with_feeds, many=True).data

    # # Get all accounts and payees for dropdowns
    # all_accounts = Account.for_team.all().order_by("account_number")
    # all_payees = Payee.for_team.all().order_by("name")

    # all_accounts_data = AccountSerializer(all_accounts, many=True).data
    # all_payees_data = PayeeSerializer(all_payees, many=True).data

    # API URLs
    api_urls = {
        "budget_list": f"/a/{team_slug}/budget/api/budget/",
        # "transactions_detail": f"/a/{team_slug}/journal/api/transactions/{{id}}/",
    }

    return render(
        request,
        "budget/budget_home.html",
        {
            "active_tab": "budget",
            "page_title": _("Budget | {team}").format(team=request.team),
            # "accounts": accounts_data,
            # "all_accounts": all_accounts_data,
            # "all_payees": all_payees_data,
            "api_urls": api_urls,
            # "team_slug": team_slug,
        },
    )
