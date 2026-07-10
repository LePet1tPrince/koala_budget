import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts.models import Account
from apps.accounts.serializers import SimpleAccountSerializer
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.teams.decorators import login_and_team_required

from .forms import BudgetAmountForm, GoalAllocationForm, GoalForm
from .models import Budget, Goal, GoalAllocation
from .services import BudgetService, GoalService, NetWorthService


def _parse_month(value):
    """Parse a month parameter (YYYY-MM-DD or YYYY-MM); fall back to the current month."""
    if value:
        month = parse_date(value) or parse_date(f"{value}-01")
        if month:
            return month.replace(day=1)
    return date.today().replace(day=1)


@login_and_team_required
def budget_month_view(request, team_slug):
    from collections import defaultdict
    from decimal import Decimal

    month = _parse_month(request.GET.get("month"))

    if request.method == "POST":
        # Budget rows are created lazily on first save (a GET must not write).
        # The form posts budget_id when a row already exists, category_id otherwise.
        budget_id = request.POST.get("budget_id")
        if budget_id:
            budget = get_object_or_404(Budget, id=budget_id, team=request.team)
        else:
            category = get_object_or_404(
                Account.objects.filter(team=request.team, account_group__account_type__in=("expense", "income")),
                id=request.POST.get("category_id"),
            )
            budget, _created = Budget.objects.get_or_create(
                team=request.team,
                category=category,
                month=_parse_month(request.POST.get("budget_month")) if request.POST.get("budget_month") else month,
                defaults={"budget_amount": 0},
            )

        form = BudgetAmountForm(request.POST, instance=budget)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _("%(category)s budget set to $%(amount)s.")
                % {"category": budget.category.name, "amount": form.cleaned_data["budget_amount"]},
            )
            return redirect(f"/a/{team_slug}/budget/?month={month.isoformat()}")
        messages.error(request, _("Could not save budget amount: %(errors)s") % {"errors": form.errors.as_text()})

    service = BudgetService(request.team)

    categories = list(
        Account.for_team.filter(
            account_group__account_type__in=("expense", "income"),
        )
        .select_related("account_group")
        .order_by("account_group__name", "name")
    )

    # Fetch existing budgets for this month; categories without one are shown
    # with a zero amount and a row is only created when the user saves a value
    existing_budgets = {b.category_id: b for b in Budget.objects.filter(team=request.team, month=month)}

    # Bulk fetch actuals and available amounts
    actuals_map = service.get_actuals_by_category(month)
    available_map = service.get_available_by_category(month, categories)

    # Group categories by account_group
    grouped_data = defaultdict(
        lambda: {"rows": [], "subtotals": {"budgeted": Decimal("0"), "actual": Decimal("0"), "available": Decimal("0")}}
    )  # noqa: E501

    for category in categories:
        budget = existing_budgets.get(category.pk)
        budgeted = budget.budget_amount if budget else Decimal("0")
        actual = actuals_map.get(category.pk, Decimal("0"))
        available = available_map.get(category.pk, Decimal("0"))

        group_name = category.account_group.name

        grouped_data[group_name]["rows"].append(
            {
                "category": category,
                "form": BudgetAmountForm(instance=budget),
                "budgeted": budgeted,
                "actual": actual,
                "available": available,
            }
        )

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

    # Get previous month available totals for sidebar summary
    prev_month = month - relativedelta(months=1)
    prev_available_map = service.get_available_by_category(prev_month, categories)
    leftover_last_month = sum(prev_available_map.values())

    # Sidebar summary data
    sidebar_summary = {
        "leftover_last_month": leftover_last_month,
        "assigned_this_month": grand_totals["budgeted"],
        "activity_this_month": grand_totals["actual"],
        "available": grand_totals["available"],
    }

    # Get net worth card data
    net_worth_service = NetWorthService(request.team)
    net_worth_card = net_worth_service.get_net_worth_card_data(month, categories)

    # Get all accounts for React recategorize dropdown
    all_accounts = (
        Account.for_team.filter(
            account_group__account_type__in=("expense", "income"),
        )
        .select_related("account_group")
        .order_by("name")
    )
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
            "sidebar_summary": sidebar_summary,
            "prev_month": month - relativedelta(months=1),
            "next_month": month + relativedelta(months=1),
            "all_accounts": all_accounts_data,
            "api_urls": api_urls,
            "team_slug": team_slug,
        },
    )


@login_and_team_required
def budget_autofill_view(request, team_slug):
    """Handle auto-fill budget actions from the sidebar."""
    if request.method != "POST":
        return redirect("budget:budget_home", team_slug=team_slug)

    action = request.POST.get("action")
    month = _parse_month(request.POST.get("month"))

    prev_month = month - relativedelta(months=1)
    service = BudgetService(request.team)

    categories = list(
        Account.for_team.filter(
            account_group__account_type__in=("expense", "income"),
        )
        .select_related("account_group")
        .order_by("account_group__name", "name")
    )

    # Ensure budgets exist for this month
    existing_budgets = {b.category_id: b for b in Budget.objects.filter(team=request.team, month=month)}
    missing_budgets = []
    for category in categories:
        if category.pk not in existing_budgets:
            missing_budgets.append(
                Budget(
                    team=request.team,
                    category=category,
                    month=month,
                    budget_amount=0,
                )
            )
    if missing_budgets:
        Budget.objects.bulk_create(missing_budgets, ignore_conflicts=True)
        existing_budgets = {b.category_id: b for b in Budget.objects.filter(team=request.team, month=month)}

    if action == "assigned_last_month":
        prev_budgets = {
            b.category_id: b.budget_amount for b in Budget.objects.filter(team=request.team, month=prev_month)
        }
        updates = []
        for cat in categories:
            budget = existing_budgets.get(cat.pk)
            if budget:
                budget.budget_amount = prev_budgets.get(cat.pk, Decimal("0"))
                updates.append(budget)
        Budget.objects.bulk_update(updates, ["budget_amount"])
        messages.success(request, _("Budgets set to last month's assigned amounts."))

    elif action == "spent_last_month":
        prev_actuals = service.get_actuals_by_category(prev_month)
        updates = []
        for cat in categories:
            budget = existing_budgets.get(cat.pk)
            if budget:
                actual = prev_actuals.get(cat.pk, Decimal("0"))
                budget.budget_amount = max(actual, Decimal("0"))
                updates.append(budget)
        Budget.objects.bulk_update(updates, ["budget_amount"])
        messages.success(request, _("Budgets set to last month's spending."))

    elif action == "assign_zero":
        Budget.objects.filter(team=request.team, month=month).update(budget_amount=Decimal("0"))
        messages.success(request, _("All budgets set to zero."))

    elif action == "reset_available_zero":
        prev_available = service.get_available_by_category(prev_month, categories)
        current_actuals = service.get_actuals_by_category(month)
        updates = []
        for cat in categories:
            budget = existing_budgets.get(cat.pk)
            if budget:
                actual = current_actuals.get(cat.pk, Decimal("0"))
                prev_avail = prev_available.get(cat.pk, Decimal("0"))
                if cat.account_group.account_type == "income":
                    # Available = Actual - Budget + prev_avail = 0
                    # Budget = Actual + prev_avail
                    budget.budget_amount = actual + prev_avail
                else:
                    # Available = Budget - Actual + prev_avail = 0
                    # Budget = Actual - prev_avail
                    budget.budget_amount = actual - prev_avail
                updates.append(budget)
        Budget.objects.bulk_update(updates, ["budget_amount"])
        messages.success(request, _("Budgets adjusted so all available amounts are zero."))

    return redirect(f"/a/{team_slug}/budget/?month={month.isoformat()}")


# =============================================================================
# Multi-month grid editor
# =============================================================================

GRID_MAX_MONTHS = 24
GRID_DEFAULT_MONTHS = 12
# budget_amount is max_digits=15 / decimal_places=2, so 13 integer digits
GRID_MAX_AMOUNT = Decimal("9999999999999.99")


def _budget_categories(team):
    """Income/expense category accounts for a team, in budget-table display order."""
    return (
        Account.objects.filter(team=team, account_group__account_type__in=("expense", "income"))
        .select_related("account_group")
        .order_by("account_group__name", "name")
    )


@login_and_team_required
def budget_grid_view(request, team_slug):
    """Multi-month budget editor: one row per category, one column per month."""
    start_param = request.GET.get("start")
    # Default to January of the current year so the grid lines up with a typical Jan–Dec spreadsheet
    start = _parse_month(start_param) if start_param else date.today().replace(month=1, day=1)

    try:
        num_months = int(request.GET.get("months", GRID_DEFAULT_MONTHS))
    except (TypeError, ValueError):
        num_months = GRID_DEFAULT_MONTHS
    num_months = max(1, min(num_months, GRID_MAX_MONTHS))

    months = [start + relativedelta(months=i) for i in range(num_months)]

    categories = list(_budget_categories(request.team))

    amounts = {}
    for budget in Budget.objects.filter(team=request.team, month__gte=months[0], month__lte=months[-1]):
        amounts.setdefault(budget.category_id, {})[budget.month.isoformat()] = str(budget.budget_amount)

    groups = []
    for category in categories:
        group_name = category.account_group.name
        if not groups or groups[-1]["name"] != group_name:
            groups.append({"name": group_name, "type": category.account_group.account_type, "rows": []})
        groups[-1]["rows"].append(
            {
                "id": category.pk,
                "name": category.name,
                "amounts": amounts.get(category.pk, {}),
            }
        )

    grid_props = {
        "months": [{"key": m.isoformat(), "label": m.strftime("%b %Y")} for m in months],
        "groups": groups,
        "start": start.isoformat(),
        "numMonths": num_months,
        "prevStart": (start - relativedelta(months=num_months)).isoformat(),
        "nextStart": (start + relativedelta(months=num_months)).isoformat(),
        "saveUrl": f"/a/{team_slug}/budget/grid/save/",
        "budgetUrl": f"/a/{team_slug}/budget/",
    }

    return render(
        request,
        "budget/budget_grid.html",
        {
            "active_tab": "budget",
            "page_title": f"Edit Budgets | {request.team}",
            "grid_props": grid_props,
            "start": start,
            "end": months[-1],
        },
    )


@login_and_team_required
@require_POST
def budget_grid_save(request, team_slug):
    """Bulk upsert budget amounts from the grid editor.

    Body: {"changes": [{"category_id": int, "month": "YYYY-MM-DD", "amount": "123.45"}, ...]}
    All-or-nothing: any invalid change rejects the whole batch.
    """
    try:
        payload = json.loads(request.body)
        changes = payload["changes"]
    except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)
    if not isinstance(changes, list):
        return JsonResponse({"error": "Invalid request body."}, status=400)
    if len(changes) > 10000:
        return JsonResponse({"error": "Too many changes in one request."}, status=400)

    category_ids = {c.get("category_id") for c in changes if isinstance(c, dict)}
    valid_category_ids = set(_budget_categories(request.team).filter(pk__in=category_ids).values_list("pk", flat=True))

    # Last write wins if the same cell appears twice
    merged = {}
    for change in changes:
        if not isinstance(change, dict):
            return JsonResponse({"error": "Invalid request body."}, status=400)

        category_id = change.get("category_id")
        if category_id not in valid_category_ids:
            return JsonResponse({"error": "Unknown budget category."}, status=400)

        month = parse_date(str(change.get("month") or ""))
        if month is None:
            return JsonResponse({"error": "Invalid month."}, status=400)
        month = month.replace(day=1)

        try:
            amount = Decimal(str(change.get("amount"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError):
            return JsonResponse({"error": "Invalid amount."}, status=400)
        if not amount.is_finite() or abs(amount) > GRID_MAX_AMOUNT:
            return JsonResponse({"error": "Invalid amount."}, status=400)

        merged[(category_id, month)] = amount

    if not merged:
        return JsonResponse({"saved": 0})

    with transaction.atomic():
        existing = {
            (b.category_id, b.month): b
            for b in Budget.objects.select_for_update().filter(
                team=request.team,
                category_id__in={cid for cid, _month in merged},
                month__in={month for _cid, month in merged},
            )
            if (b.category_id, b.month) in merged
        }
        updates = []
        creates = []
        for (category_id, month), amount in merged.items():
            budget = existing.get((category_id, month))
            if budget:
                if budget.budget_amount != amount:
                    budget.budget_amount = amount
                    updates.append(budget)
            else:
                creates.append(Budget(team=request.team, category_id=category_id, month=month, budget_amount=amount))
        if updates:
            Budget.objects.bulk_update(updates, ["budget_amount"])
        if creates:
            Budget.objects.bulk_create(creates)

    log_event(
        AuditEvent.BULK_EDIT,
        request=request,
        metadata={
            "scope": "budget_grid",
            "saved": len(merged),
            "months": sorted({month.isoformat() for _cid, month in merged}),
        },
    )
    return JsonResponse({"saved": len(merged)})


# =============================================================================
# Goal Views
# =============================================================================


@login_and_team_required
def goals_list_view(request, team_slug):
    """List all goals with progress for the selected month."""
    month = _parse_month(request.GET.get("month"))
    service = GoalService(request.team)
    summary = service.get_goal_summary(month)

    # Build forms for inline allocation editing
    goals_with_forms = []
    for goal in summary["goals"]:
        allocation = GoalAllocation.objects.filter(team=request.team, goal=goal, month=month).first()

        if allocation:
            form = GoalAllocationForm(instance=allocation)
        else:
            form = GoalAllocationForm(initial={"amount": Decimal("0")})

        goals_with_forms.append(
            {
                "goal": goal,
                "form": form,
                "allocation": allocation,
            }
        )

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
    goal = get_object_or_404(Goal.objects.filter(team=request.team).with_progress(), pk=pk)

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
        amount = request.POST.get("amount", "0")
        month = _parse_month(request.POST.get("month"))

        try:
            amount = Decimal(amount)
        except (InvalidOperation, ValueError, TypeError):
            amount = Decimal("0")
        if amount < 0:
            messages.error(request, _("Allocation amount cannot be negative."))
            return redirect(f"/a/{team_slug}/budget/goals/?month={month.isoformat()}")

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
