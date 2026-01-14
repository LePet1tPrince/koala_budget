from datetime import date

from dateutil.relativedelta import relativedelta
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date

from apps.accounts.models import Account
from apps.teams.decorators import login_and_team_required

from .forms import BudgetAmountForm
from .models import Budget
from .services import BudgetService


@login_and_team_required
def budget_month_view(request, team_slug):
    month_param = request.GET.get("month")
    if month_param:
        month = parse_date(month_param)
    else:
        month = date.today().replace(day=1)

    month = month.replace(day=1)

    service = BudgetService(request.team)

    categories = Account.for_team.filter(
        account_group__account_type__in=("expense", "income"),
    ).select_related("account_group").order_by("account_group__name", "account_number")

    # Group categories by account_group
    from collections import defaultdict
    from decimal import Decimal

    grouped_data = defaultdict(lambda: {"rows": [], "subtotals": {"budgeted": Decimal("0"), "actual": Decimal("0"), "available": Decimal("0")}})

    for category in categories:
        budget, _ = Budget.objects.get_or_create(
            team=request.team,
            category=category,
            month=month,
            defaults={"budget_amount": 0},
        )

        budgeted = service.budgeted(category, month)
        actual = service.actual(category, month)
        available = service.available(category, month)

        group_name = category.account_group.name

        grouped_data[group_name]["rows"].append({
            "category": category,
            "form": BudgetAmountForm(instance=budget),
            "budgeted": budgeted,
            "actual": actual,
            "available": available,
        })

        # Add to subtotals
        grouped_data[group_name]["subtotals"]["budgeted"] += budgeted
        grouped_data[group_name]["subtotals"]["actual"] += actual
        grouped_data[group_name]["subtotals"]["available"] += available

    # Convert to list of tuples for template
    groups = [(name, data) for name, data in grouped_data.items()]

    # Calculate grand totals across all groups
    grand_totals = {
        "budgeted": sum(data["subtotals"]["budgeted"] for _, data in groups),
        "actual": sum(data["subtotals"]["actual"] for _, data in groups),
        "available": sum(data["subtotals"]["available"] for _, data in groups),
    }

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
            "groups": groups,
            "grand_totals": grand_totals,
            "prev_month": month - relativedelta(months=1),
            "next_month": month + relativedelta(months=1),
        },
    )
