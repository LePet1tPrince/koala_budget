import json
import math
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.db import transaction
from django.db.models import Case, IntegerField, Sum, Value, When
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

from .forms import BudgetAmountForm, GoalForm
from .models import Budget, Goal, GoalAllocation
from .services import BudgetService, GoalService, NetWorthService


def _parse_month(value):
    """Parse a month parameter (YYYY-MM-DD or YYYY-MM); fall back to the current month."""
    if value:
        month = parse_date(value) or parse_date(f"{value}-01")
        if month:
            return month.replace(day=1)
    return date.today().replace(day=1)


def _month_from_request(request):
    """Selected budget/goals month: an explicit ?month= wins (and is remembered for
    the session), otherwise the last month viewed, otherwise the current month.
    Keeps the month stable when switching between the Budget and Goals pages via
    the nav, which carries no query string."""
    value = request.GET.get("month")
    if value:
        month = _parse_month(value)
        request.session["budget_month"] = month.isoformat()
        return month
    stored = request.session.get("budget_month")
    if stored:
        return _parse_month(stored)
    return date.today().replace(day=1)


@login_and_team_required
def budget_month_view(request, team_slug):
    month = _month_from_request(request)

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

    categories = list(_budget_categories(request.team))

    # Fetch existing budgets for this month; categories without one are shown
    # with a zero amount and a row is only created when the user saves a value
    existing_budgets = {b.category_id: b for b in Budget.objects.filter(team=request.team, month=month)}

    # Bulk fetch actuals and available amounts
    actuals_map = service.get_actuals_by_category(month)
    available_map = service.get_available_by_category(month, categories)

    def zero_totals():
        return {"budgeted": Decimal("0"), "actual": Decimal("0"), "available": Decimal("0")}

    # Income section first, then expenses; groups within a section keep the
    # category ordering (alphabetical by group, then name)
    sections = {
        "income": {"key": "income", "label": _("Income"), "groups": [], "totals": zero_totals()},
        "expense": {"key": "expense", "label": _("Expenses"), "groups": [], "totals": zero_totals()},
    }

    for category in categories:
        budget = existing_budgets.get(category.pk)
        budgeted = budget.budget_amount if budget else Decimal("0")
        actual = actuals_map.get(category.pk, Decimal("0"))
        available = available_map.get(category.pk, Decimal("0"))

        section = sections["income" if category.account_group.account_type == "income" else "expense"]
        group_name = category.account_group.name
        if not section["groups"] or section["groups"][-1]["name"] != group_name:
            section["groups"].append({"name": group_name, "rows": [], "subtotals": zero_totals()})
        group = section["groups"][-1]

        group["rows"].append(
            {
                "category": category,
                "form": BudgetAmountForm(instance=budget),
                "budgeted": budgeted,
                "actual": actual,
                "available": available,
            }
        )

        for field, amount in (("budgeted", budgeted), ("actual", actual), ("available", available)):
            group["subtotals"][field] += amount
            section["totals"][field] += amount

    section_list = [sections["income"], sections["expense"]]

    # Grand totals across both sections (sidebar summary)
    grand_totals = {
        field: sections["income"]["totals"][field] + sections["expense"]["totals"][field]
        for field in ("budgeted", "actual", "available")
    }
    has_categories = bool(categories)

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
            "sections": section_list,
            "has_categories": has_categories,
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

    # The frontend lets the user pick which categories this action applies to
    # (checkboxes next to each budget row). "filtered" distinguishes an explicit
    # empty selection from the no-JS fallback, which still applies to everything.
    if request.POST.get("filtered"):
        selected_ids = {cid for cid in request.POST.getlist("category_ids") if cid}
        categories = [c for c in categories if str(c.pk) in selected_ids]

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
        category_pks = [cat.pk for cat in categories]
        Budget.objects.filter(team=request.team, month=month, category_id__in=category_pks).update(
            budget_amount=Decimal("0")
        )
        messages.success(request, _("Budgets set to zero."))

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
    """Income/expense category accounts for a team, in budget-table display order:
    income sections first, then expenses, each grouped alphabetically."""
    return (
        Account.objects.filter(team=team, account_group__account_type__in=("expense", "income"))
        .select_related("account_group")
        .annotate(
            type_order=Case(
                When(account_group__account_type="income", then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("type_order", "account_group__sort_order", "account_group__name", "sort_order", "name")
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

GOAL_STYLES = {
    "summit": _("Summit"),
    "koala": _("Koala Climb"),
    "arcade": _("Save-o-Tron"),
}

# Arcade style: 1 XP per dollar ever saved to goals; level N spans ARCADE_LEVEL_STEP * N XP
ARCADE_LEVEL_STEP = 500
ARCADE_LEVEL_NAMES = [
    "Piggy Bank Rookie",
    "Coin Collector",
    "Cash Cadet",
    "Budget Brawler",
    "Savings Samurai",
    "Bamboo Baron",
    "Vault Virtuoso",
    "Money Machine",
    "Fortune Fabler",
    "Koala Tycoon",
]


def _goals_style(request):
    """Which of the three goal-page designs to render; remembered per session."""
    style = request.GET.get("style")
    if style in GOAL_STYLES:
        request.session["goals_style"] = style
        return style
    stored = request.session.get("goals_style")
    return stored if stored in GOAL_STYLES else "summit"


def _goal_streak(saved_months, month):
    """Consecutive months with a positive allocation, counting backwards from the
    selected month (a not-yet-funded selected month doesn't break the streak)."""
    cursor = month
    if cursor not in saved_months:
        cursor -= relativedelta(months=1)
    streak = 0
    while cursor in saved_months:
        streak += 1
        cursor -= relativedelta(months=1)
    return streak


def _arcade_level(xp):
    """Level number/name and progress through the current level for a given XP total."""
    level = 1
    floor = 0
    while xp >= floor + ARCADE_LEVEL_STEP * level:
        floor += ARCADE_LEVEL_STEP * level
        level += 1
    span = ARCADE_LEVEL_STEP * level
    into = xp - floor
    return {
        "number": level,
        "name": ARCADE_LEVEL_NAMES[min(level - 1, len(ARCADE_LEVEL_NAMES) - 1)],
        "xp": xp,
        "into": into,
        "span": span,
        "pct": into / span * 100,
    }


@login_and_team_required
def goals_list_view(request, team_slug):
    """List all goals with progress for the selected month."""
    month = _month_from_request(request)
    style = _goals_style(request)
    service = GoalService(request.team)
    summary = service.get_goal_summary(month)
    goals = list(summary["goals"])

    # Every allocation for these goals in one query; used for streaks and pace
    amounts_by_goal = defaultdict(dict)
    for goal_id, alloc_month, amount in GoalAllocation.objects.filter(team=request.team, goal__in=goals).values_list(
        "goal_id", "month", "amount"
    ):
        amounts_by_goal[goal_id][alloc_month] = amount

    goal_items = []
    any_streak_3 = False
    any_half_way = False
    big_month = False
    for goal in goals:
        amounts = amounts_by_goal.get(goal.pk, {})
        saved = goal.total_saved or Decimal("0")
        remaining = max(goal.target_amount - saved, Decimal("0"))
        pct = goal.progress_percentage

        saved_months = {m for m, amt in amounts.items() if amt > 0}
        streak = _goal_streak(saved_months, month)

        # Pace to hit the target date, from the selected month
        months_left = None
        needed_per_month = None
        if goal.target_date and remaining > 0:
            target_month = goal.target_date.replace(day=1)
            if target_month >= month:
                months_left = max((target_month.year - month.year) * 12 + target_month.month - month.month, 1)
                needed_per_month = remaining / months_left

        # Projection from the recent saving rate (average of the last 3 months)
        recent = [amounts.get(month - relativedelta(months=i), Decimal("0")) for i in range(3)]
        recent_avg = sum(recent) / 3
        projected_date = None
        if remaining > 0 and recent_avg > 0:
            projected_date = month + relativedelta(months=math.ceil(remaining / recent_avg))
        behind_pace = bool(
            goal.target_date
            and remaining > 0
            and (projected_date is None or projected_date > goal.target_date.replace(day=1))
        )

        any_streak_3 = any_streak_3 or streak >= 3
        any_half_way = any_half_way or pct >= 50
        big_month = big_month or any(amt >= 500 for amt in amounts.values())

        goal_items.append(
            {
                "goal": goal,
                "saved": saved,
                "remaining": remaining,
                "pct": pct,
                "this_month": goal.saved_this_month or Decimal("0"),
                "streak": streak,
                "months_left": months_left,
                "needed_per_month": needed_per_month,
                "projected_date": projected_date,
                "behind_pace": behind_pace,
                "funded": goal.is_complete or (goal.target_amount > 0 and saved >= goal.target_amount),
                "milestones": [25, 50, 75, 100],
            }
        )

    # Get net worth card data
    net_worth_service = NetWorthService(request.team)
    net_worth_card = net_worth_service.get_net_worth_card_data(month)
    available = net_worth_card["available"]

    on_track_count = sum(1 for item in goal_items if item["funded"] or not item["behind_pace"])

    total_saved = summary["total_saved"]
    has_completed_goal = Goal.objects.filter(team=request.team, is_complete=True).exists()
    achievements = [
        {
            "key": "first_save",
            "icon": "🪙",
            "name": _("Opening Bid"),
            "desc": _("Save your first dollar"),
            "earned": total_saved > 0,
        },
        {
            "key": "first_1k",
            "icon": "🥇",
            "name": _("Grand Club"),
            "desc": _("Save $1,000 in total"),
            "earned": total_saved >= 1000,
        },
        {
            "key": "half_way",
            "icon": "🚀",
            "name": _("50% Club"),
            "desc": _("Get a goal halfway funded"),
            "earned": any_half_way,
        },
        {
            "key": "streak_3",
            "icon": "🔥",
            "name": _("Hot Streak"),
            "desc": _("Save 3 months in a row"),
            "earned": any_streak_3,
        },
        {
            "key": "big_month",
            "icon": "💪",
            "name": _("Heavy Lifter"),
            "desc": _("Save $500+ in one month"),
            "earned": big_month,
        },
        {
            "key": "finisher",
            "icon": "🔔",
            "name": _("Bell Ringer"),
            "desc": _("Complete a goal"),
            "earned": has_completed_goal,
        },
    ]

    goals_props = {
        "style": style,
        "month": month.isoformat(),
        "available": float(available),
        "totalSaved": float(total_saved),
        "xp": int(total_saved),
        "levelStep": ARCADE_LEVEL_STEP,
        "levelNames": ARCADE_LEVEL_NAMES,
    }

    return render(
        request,
        "budget/goals_list.html",
        {
            "active_tab": "goals",
            "page_title": f"Goals | {request.team}",
            "month": month,
            "style": style,
            "style_label": GOAL_STYLES[style],
            "goal_styles": GOAL_STYLES,
            "goal_items": goal_items,
            "summary": summary,
            "available": available,
            "on_track_count": on_track_count,
            "achievements": achievements,
            "arcade_level": _arcade_level(int(total_saved)),
            "net_worth_card": net_worth_card,
            "goals_props": goals_props,
            "prev_month": month - relativedelta(months=1),
            "next_month": month + relativedelta(months=1),
        },
    )


@login_and_team_required
@require_POST
def goal_assign_available(request, team_slug, pk):
    """Assign funds to a goal for a month (JSON endpoint for the goals page).

    Body: {"month": "YYYY-MM-DD", "amount": "123.45"}. Without "amount", assigns
    all currently-available funds, capped at what the goal still needs. Amounts
    are *added* to the month's existing allocation.
    """
    goal = get_object_or_404(Goal.objects.filter(team=request.team), pk=pk)

    try:
        payload = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    if goal.is_archived or goal.is_complete:
        return JsonResponse({"error": "This goal is no longer active."}, status=400)

    month = _parse_month(payload.get("month"))

    with transaction.atomic():
        allocation = (
            GoalAllocation.objects.select_for_update().filter(team=request.team, goal=goal, month=month).first()
        )
        month_amount = allocation.amount if allocation else Decimal("0")
        old_saved = goal.allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        remaining = goal.target_amount - old_saved
        available = NetWorthService(request.team).get_net_worth_card_data(month)["available"]

        raw_amount = payload.get("amount")
        if raw_amount is None:
            if remaining <= 0:
                return JsonResponse({"error": "This goal is already fully funded."}, status=400)
            amount = min(available, remaining)
            if amount <= 0:
                return JsonResponse({"error": "No available funds to assign right now."}, status=400)
        else:
            try:
                amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except (InvalidOperation, TypeError, ValueError):
                return JsonResponse({"error": "Invalid amount."}, status=400)
            if not amount.is_finite() or amount <= 0 or amount > GRID_MAX_AMOUNT:
                return JsonResponse({"error": "Invalid amount."}, status=400)

        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        GoalService(request.team).update_allocation(goal, month, month_amount + amount)

    new_saved = old_saved + amount
    if goal.target_amount > 0:
        old_pct = min(float(old_saved / goal.target_amount * 100), 100)
        new_pct = min(float(new_saved / goal.target_amount * 100), 100)
    else:
        old_pct = new_pct = 0

    log_event(
        AuditEvent.GOAL_FUNDS_ASSIGNED,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "month": month.isoformat(),
            "amount": str(amount),
            "quick_assign": raw_amount is None,
        },
    )

    return JsonResponse(
        {
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "assigned": float(amount),
            "old_saved": float(old_saved),
            "new_saved": float(new_saved),
            "old_pct": old_pct,
            "new_pct": new_pct,
            "remaining": float(max(goal.target_amount - new_saved, Decimal("0"))),
            "this_month": float(month_amount + amount),
            "new_available": float(available - amount),
            "completed": new_saved >= goal.target_amount and goal.target_amount > 0,
        }
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
