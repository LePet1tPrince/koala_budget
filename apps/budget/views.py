from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Account
from apps.accounts.serializers import SimpleAccountSerializer
from apps.teams.decorators import login_and_team_required

from .forms import BudgetAmountForm, GoalAllocationForm, GoalForm
from .models import Budget, Goal, GoalAllocation
from .services import BudgetService, GoalService, NetWorthService


@login_and_team_required
def budget_month_view(request, team_slug):
    from collections import defaultdict
    from decimal import Decimal

    month_param = request.GET.get("month")
    if month_param:
        month = parse_date(month_param)
    else:
        month = date.today().replace(day=1)

    month = month.replace(day=1)

    if request.method == "POST":
        budget_id = request.POST.get("budget_id")
        budget = Budget.objects.get(id=budget_id, team=request.team)

        form = BudgetAmountForm(request.POST, instance=budget)
        if form.is_valid():
            form.save()
            return redirect(f"/a/{team_slug}/budget/?month={month.isoformat()}")

    service = BudgetService(request.team)

    categories = list(Account.for_team.filter(
        account_group__account_type__in=("expense", "income"),
    ).select_related("account_group").order_by("account_group__name", "account_number"))

    # Bulk fetch existing budgets for this month
    existing_budgets = {
        b.category_id: b
        for b in Budget.objects.filter(team=request.team, month=month)
    }

    # Bulk create missing budgets
    missing_budgets = []
    for category in categories:
        if category.pk not in existing_budgets:
            missing_budgets.append(Budget(
                team=request.team,
                category=category,
                month=month,
                budget_amount=0,
            ))

    if missing_budgets:
        Budget.objects.bulk_create(missing_budgets, ignore_conflicts=True)
        # Re-fetch to get all budgets including newly created ones
        existing_budgets = {
            b.category_id: b
            for b in Budget.objects.filter(team=request.team, month=month)
        }

    # Bulk fetch actuals and available amounts
    actuals_map = service.get_actuals_by_category(month)
    available_map = service.get_available_by_category(month, categories)

    # Group categories by account_group
    grouped_data = defaultdict(lambda: {"rows": [], "subtotals": {"budgeted": Decimal("0"), "actual": Decimal("0"), "available": Decimal("0")}})

    for category in categories:
        budget = existing_budgets.get(category.pk)
        budgeted = budget.budget_amount if budget else Decimal("0")
        actual = actuals_map.get(category.pk, Decimal("0"))
        available = available_map.get(category.pk, Decimal("0"))

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

    # Get net worth card data
    net_worth_service = NetWorthService(request.team)
    net_worth_card = net_worth_service.get_net_worth_card_data(month, categories)

    # Get all accounts for React recategorize dropdown
    all_accounts = Account.for_team.filter(
        account_group__account_type__in=("expense", "income"),
    ).select_related("account_group").order_by("account_number")
    all_accounts_data = SimpleAccountSerializer(all_accounts, many=True).data

    # API URLs for React
    api_urls = {
        "lines": f"/a/{team_slug}/journal/api/lines/",
    }

    return render(
        request,
        "budget/budget_home.html",
        {
            "active_tab": "budget",
            "page_title": f"Budget | {request.team}",
            "month": month,
            "end_date": month + relativedelta(months=1, days=-1),
            "groups": groups,
            "grand_totals": grand_totals,
            "net_worth_card": net_worth_card,
            "prev_month": month - relativedelta(months=1),
            "next_month": month + relativedelta(months=1),
            "all_accounts": all_accounts_data,
            "api_urls": api_urls,
            "team_slug": team_slug,
        },
    )


# =============================================================================
# Goal Views
# =============================================================================


@login_and_team_required
def goals_list_view(request, team_slug):
    """List all goals with progress for the selected month."""
    month_param = request.GET.get("month")
    if month_param:
        month = parse_date(month_param)
    else:
        month = date.today().replace(day=1)

    month = month.replace(day=1)
    service = GoalService(request.team)
    summary = service.get_goal_summary(month)

    # Build forms for inline allocation editing
    goals_with_forms = []
    for goal in summary["goals"]:
        allocation = GoalAllocation.objects.filter(
            team=request.team,
            goal=goal,
            month=month
        ).first()

        if allocation:
            form = GoalAllocationForm(instance=allocation)
        else:
            form = GoalAllocationForm(initial={"amount": Decimal("0")})

        goals_with_forms.append({
            "goal": goal,
            "form": form,
            "allocation": allocation,
        })

    # Get net worth card data
    net_worth_service = NetWorthService(request.team)
    net_worth_card = net_worth_service.get_net_worth_card_data(month)

    return render(
        request,
        "budget/goals_list.html",
        {
            "active_tab": "goals",
            "page_title": f"Goals | {request.team}",
            "month": month,
            "goals_with_forms": goals_with_forms,
            "summary": summary,
            "net_worth_card": net_worth_card,
            "prev_month": month - relativedelta(months=1),
            "next_month": month + relativedelta(months=1),
        },
    )


@login_and_team_required
def goal_create_view(request, team_slug):
    """Create a new goal."""
    if request.method == "POST":
        form = GoalForm(request.POST)
        if form.is_valid():
            goal = form.save(commit=False)
            goal.team = request.team
            goal.save()
            messages.success(request, _("Goal created successfully."))
            return redirect("budget:goals_list", team_slug=team_slug)
    else:
        form = GoalForm()

    return render(
        request,
        "budget/goal_form.html",
        {
            "active_tab": "goals",
            "page_title": f"New Goal | {request.team}",
            "form": form,
            "is_new": True,
        },
    )


@login_and_team_required
def goal_detail_view(request, team_slug, pk):
    """View a single goal with full details and allocation history."""
    goal = get_object_or_404(
        Goal.objects.filter(team=request.team).with_progress(),
        pk=pk
    )

    allocations = goal.allocations.all()[:12]  # Last 12 months

    return render(
        request,
        "budget/goal_detail.html",
        {
            "active_tab": "goals",
            "page_title": f"{goal.name} | {request.team}",
            "goal": goal,
            "allocations": allocations,
        },
    )


@login_and_team_required
def goal_update_view(request, team_slug, pk):
    """Update an existing goal."""
    goal = get_object_or_404(Goal.objects.filter(team=request.team), pk=pk)

    if request.method == "POST":
        form = GoalForm(request.POST, instance=goal)
        if form.is_valid():
            form.save()
            messages.success(request, _("Goal updated successfully."))
            return redirect("budget:goal_detail", team_slug=team_slug, pk=pk)
    else:
        form = GoalForm(instance=goal)

    return render(
        request,
        "budget/goal_form.html",
        {
            "active_tab": "goals",
            "page_title": f"Edit {goal.name} | {request.team}",
            "form": form,
            "goal": goal,
            "is_new": False,
        },
    )


@login_and_team_required
def goal_delete_view(request, team_slug, pk):
    """Delete a goal (or archive it)."""
    goal = get_object_or_404(Goal.objects.filter(team=request.team), pk=pk)

    if request.method == "POST":
        # Soft delete by archiving
        goal.is_archived = True
        goal.save()
        messages.success(request, _("Goal archived successfully."))
        return redirect("budget:goals_list", team_slug=team_slug)

    return render(
        request,
        "budget/goal_confirm_delete.html",
        {
            "active_tab": "goals",
            "page_title": f"Archive {goal.name} | {request.team}",
            "goal": goal,
        },
    )


@login_and_team_required
def goal_allocation_update_view(request, team_slug, pk):
    """Update a goal allocation for a specific month."""
    goal = get_object_or_404(Goal.objects.filter(team=request.team), pk=pk)

    if request.method == "POST":
        month_param = request.POST.get("month")
        amount = request.POST.get("amount", "0")

        if month_param:
            month = parse_date(month_param).replace(day=1)
        else:
            month = date.today().replace(day=1)

        try:
            amount = Decimal(amount)
        except (ValueError, TypeError):
            amount = Decimal("0")

        service = GoalService(request.team)
        service.update_allocation(goal, month, amount)

        # Return to goals list at the same month
        return redirect(f"/a/{team_slug}/budget/goals/?month={month.isoformat()}")

    return redirect("budget:goals_list", team_slug=team_slug)


@login_and_team_required
def goal_complete_view(request, team_slug, pk):
    """Mark a goal as complete."""
    goal = get_object_or_404(Goal.objects.filter(team=request.team), pk=pk)

    if request.method == "POST":
        goal.is_complete = True
        goal.save()
        messages.success(request, _("Congratulations! Goal marked as complete."))

    return redirect("budget:goal_detail", team_slug=team_slug, pk=pk)
