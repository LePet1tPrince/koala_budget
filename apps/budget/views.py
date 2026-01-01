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
from apps.accounts.models import Account

from .services import BudgetService
from .serializers import BudgetSerializer
from .models import Budget
# from .serializers import BudgetListSerializer



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


from django.utils.dateparse import parse_date
from .forms import BudgetAmountForm
from .services import BudgetService
from django.shortcuts import render, redirect
from dateutil.relativedelta import relativedelta



@login_and_team_required
def budget_month_view(request, team_slug):
    month_param = request.GET.get("month")
    if month_param:
        month = parse_date(month_param)
    else:
        month = date.today().replace(day=1)

    month = month.replace(day=1)

    service = BudgetService(request.team)
    rows = []

    categories = Account.for_team.filter(
        account_group__account_type__in=("expense", "income"),
    ).select_related("account_group").order_by("account_group__name", "account_number")

    for category in categories:
        budget, _ = Budget.objects.get_or_create(
            team=request.team,
            category=category,
            month=month,
            defaults={"budget_amount": 0},
        )

        rows.append({
            "category": category,
            "form": BudgetAmountForm(instance=budget),
            "budgeted": service.budgeted(category, month),
            "actual": service.actual(category, month),
            "available": service.available(category, month),
        })

    if request.method == "POST":
        budget_id = request.POST.get("budget_id")
        budget = Budget.objects.get(id=budget_id, team=request.team)

        form = BudgetAmountForm(request.POST, instance=budget)
        if form.is_valid():
            form.save()
            return redirect(f"/a/{team_slug}/budget/?month={month.isoformat()}")

    return render(
        request,
        "budget/budget_home.html",
        {
            "active_tab": "budget",
            "page_title": f"Budget | {request.team}",
            "month": month,
            "rows": rows,
            "prev_month": month - relativedelta(months=1),
            "next_month": month + relativedelta(months=1),
        },
    )
