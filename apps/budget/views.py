import json
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateformat import format as date_format
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name
from apps.utils.amounts import evaluate_amount
from apps.web.templatetags.currency_tags import currency

from . import goal_links
from . import ledger as budget_ledger
from .autofill import apply_autofill
from .figures import budget_tab_keys, budgeted_categories, month_figures
from .forms import BudgetAmountForm, GoalForm
from .grid import GRID_MAX_AMOUNT
from .models import Goal, GoalAccountLink
from .services import (
    GoalAllocationError,
    GoalCloseError,
    GoalDeleteError,
    GoalService,
    NetWorthService,
    goal_plan,
    picker_accounts_data,
)
from .unassigned import OVER_ASSIGNED_LABEL, UNASSIGNED_LABEL


def _parse_month(value):
    """Parse a month parameter (YYYY-MM-DD or YYYY-MM); fall back to the current month."""
    if value:
        month = parse_date(value) or parse_date(f"{value}-01")
        if month:
            return month.replace(day=1)
    return date.today().replace(day=1)


# The budget page changes month in place (through the budget API, which never
# touches the session) and writes the month to this cookie, as `YYYY-MM-DD.<nonce>`.
BUDGET_MONTH_COOKIE = "budget_month"


def _month_from_request(request):
    """Selected budget/goals month: an explicit ?month= wins (and is remembered for
    the session), otherwise the last month viewed, otherwise the current month.
    Keeps the month stable when switching between the Budget and Goals pages via
    the nav, which carries no query string.

    "The last month viewed" is the newer of two records: the session (a page loaded
    with ?month=) and the cookie the budget page writes when it changes month in
    place. Every cookie value is new, so a cookie the session hasn't seen yet is
    the newer one; one it has seen was overtaken by a ?month= since."""
    cookie = request.COOKIES.get(BUDGET_MONTH_COOKIE, "")
    value = request.GET.get("month")
    if value:
        month = _parse_month(value)
        request.session["budget_month"] = month.isoformat()
        request.session["budget_month_cookie"] = cookie
        return month
    if cookie and cookie != request.session.get("budget_month_cookie"):
        month = _parse_month(cookie.split(".")[0])
        request.session["budget_month"] = month.isoformat()
        request.session["budget_month_cookie"] = cookie
        return month
    stored = request.session.get("budget_month")
    if stored:
        return _parse_month(stored)
    return date.today().replace(day=1)


# The budget page shows one section at a time. `?tab=` picks it, else the last tab
# used (a cookie the page's script writes), else expenses -- the section edited most.
BUDGET_TAB_COOKIE = "budget_tab"
DEFAULT_BUDGET_TAB = "expense"


def _budget_tab(request, book):
    keys = budget_tab_keys(book)
    for value in (request.GET.get("tab"), request.COOKIES.get(BUDGET_TAB_COOKIE)):
        if value in keys:
            return value
    return DEFAULT_BUDGET_TAB


def _budget_home_url(book, month, tab=None):
    query = f"?month={month.isoformat()}" + (f"&tab={tab}" if tab else "")
    return reverse("budget:budget_home", args=book.url_args) + query


@login_and_book_required
def budget_month_view(request, team_slug, book_slug):
    month = _month_from_request(request)

    if request.method == "POST":
        # The <noscript> fallback: a full form post per row. With JS the page
        # saves through the budget API (`api_amount`) instead and never navigates.
        # Only the categories this book budgets: with future income off, an income
        # row is refused here exactly as the API refuses it.
        category = get_object_or_404(budgeted_categories(request.book), id=request.POST.get("category_id"))
        budget_month = _parse_month(request.POST.get("budget_month")) if request.POST.get("budget_month") else month
        form = BudgetAmountForm(request.POST)
        if form.is_valid():
            budget_ledger.set_budget(request.book, category, budget_month, form.cleaned_data["budget_amount"])
            messages.success(
                request,
                _("%(category)s budget set to $%(amount)s.")
                % {"category": category.name, "amount": form.cleaned_data["budget_amount"]},
            )
            # Back to the tab the row is on: without script, nothing else remembers it.
            return redirect(_budget_home_url(request.book, month, category.account_group.account_type))
        messages.error(request, _("Could not save budget amount: %(errors)s") % {"errors": form.errors.as_text()})

    context = _budget_swap_context(request.book, month, _budget_tab(request, request.book))
    # Every account type is a valid "Move to..." target in the Actual popup (the
    # client groups them by type); moving onto a feed account makes it a transfer.
    # System accounts (reconciliation adjustments) are bookkeeping, not destinations.
    context["all_accounts"] = picker_accounts_data(request.book)
    context["active_tab"] = "budget"
    context["page_title"] = f"Budget | {book_display_name(request.book)}"
    return render(request, "budget/budget_home.html", context)


def _budget_swap_context(book, month, tab=DEFAULT_BUDGET_TAB):
    """What `budget/components/budget_swap.html` renders: the month's figures
    (`figures.month_figures`, the same the budget API serializes), the tab on
    screen and each row's no-JS form. The month view adds the page chrome around it."""
    figures = month_figures(book, month)
    for section in figures["sections"]:
        for group in section["groups"]:
            for row in group["rows"]:
                budgeted = row["budgeted"]
                # The input has no visible label — the category is its row header.
                form = BudgetAmountForm(initial={"budget_amount": budgeted} if budgeted else None)
                form.fields["budget_amount"].widget.attrs["aria-label"] = _("%(category)s budget") % {
                    "category": row["category"].name
                }
                row["form"] = form
    return {
        "month": month,
        "budget_tab": tab,
        "end_date": month + relativedelta(months=1, days=-1),
        "sections": figures["sections"],
        "has_categories": figures["has_categories"],
        "grand_totals": figures["grand_totals"],
        "net_worth_card": figures["net_worth_card"],
        "sidebar_summary": figures["sidebar_summary"],
        "prev_month": month - relativedelta(months=1),
        "next_month": month + relativedelta(months=1),
        # The cover dialog loads the goals themselves from the API; the markup only
        # needs to know whether to offer "A goal" at all.
        "has_cover_goals": bool(figures["cover_goals"]),
    }


@login_and_book_required
@require_POST
def budget_category_visibility(request, team_slug, book_slug, pk):
    """Hide a category from the budget page, or bring it back: the no-JS form post.

    Form fields: `hidden` ("1" hides, anything else unhides) and `month`. A display
    choice only — nothing about the category's money changes. Redirects back to the
    budget page, on the category's own tab. With JS the page posts to the budget
    API (`api_category_visibility`) instead.
    """
    category = get_object_or_404(budgeted_categories(request.book), pk=pk)
    hidden = request.POST.get("hidden") == "1"
    if category.hidden_from_budget != hidden:
        category.hidden_from_budget = hidden
        category.save(update_fields=["hidden_from_budget", "updated_at"])

    month = _parse_month(request.POST.get("month"))
    template = _("%(category)s is hidden from the budget.") if hidden else _("%(category)s is back in the budget.")
    messages.success(request, template % {"category": category.name})
    return redirect(_budget_home_url(request.book, month, category.account_group.account_type))


AUTOFILL_MESSAGES = {
    "assigned_last_month": _("Budgets set to last month's assigned amounts."),
    "spent_last_month": _("Budgets set to last month's spending."),
    "assign_zero": _("Budgets set to zero."),
    "reset_available_zero": _("Budgets adjusted so all available amounts are zero."),
}


@login_and_book_required
def budget_autofill_view(request, team_slug, book_slug):
    """Auto-Assign from the sidebar: the no-JS form post. With JS the page posts to
    the budget API (`api_autofill`) and repaints in place."""
    if request.method != "POST":
        return redirect("budget:budget_home", team_slug=team_slug, book_slug=book_slug)

    action = request.POST.get("action")
    month = _parse_month(request.POST.get("month"))
    # One tab's categories: each tab carries its own Auto-Assign buttons. Without a
    # `section` (an older form) it covers every budgeted type.
    section = request.POST.get("section")
    # "filtered" marks an explicit selection (possibly empty); without it -- the
    # no-JS form -- the action applies to every category of the tab.
    category_ids = None
    if request.POST.get("filtered"):
        category_ids = [cid for cid in request.POST.getlist("category_ids") if cid.isdigit()]

    apply_autofill(request.book, month, action, section=section, category_ids=category_ids)
    if action in AUTOFILL_MESSAGES:
        messages.success(request, AUTOFILL_MESSAGES[action])

    tab = section if section in budget_tab_keys(request.book) else None
    return redirect(_budget_home_url(request.book, month, tab))


# =============================================================================
# Multi-month grid editor
# =============================================================================


@login_and_book_required
def budget_grid_view(request, team_slug, book_slug):
    """Multi-month budget editor: one row per category, one column per month.

    The page is a shell; the grid (`BudgetGrid.jsx`) loads its range from the
    budget API (`api_grid`) for the `?start=` / `?months=` in the address bar.
    """
    return render(
        request,
        "budget/budget_grid.html",
        {"active_tab": "budget", "page_title": f"Edit Budgets | {book_display_name(request.book)}"},
    )


# =============================================================================
# Goal Views
# =============================================================================


def _goal_card_progress(goal, saved, this_month):
    """
    (pct, remaining) for a goal card: what its bar shows and what it still asks for.

    A goal with a target measures `saved` against the target. An open-ended goal
    (no target) measures this month's contribution against its monthly plan, so
    the bar fills each month and empties the next.
    """
    zero = Decimal("0")
    if goal.has_target:
        pct = max(min(float(saved / goal.target_amount * 100), 100), 0)
        return pct, max(goal.target_amount - saved, zero)
    rate = goal.monthly_contribution or zero
    if rate <= 0:
        return 0, zero
    return max(min(float(this_month / rate * 100), 100), 0), max(rate - this_month, zero)


@login_and_book_required
def goals_list_view(request, team_slug, book_slug):
    """List all goals with progress for the selected month."""
    month = _month_from_request(request)
    show_closed = request.GET.get("show") == "closed"
    service = GoalService(request.book)
    summary = service.get_goal_summary(month, closed=show_closed)
    goals = summary["goals"]
    closed_count = (
        Goal.objects.filter(book=request.book).filter(Q(closed_at__isnull=False) | Q(is_archived=True)).count()
    )

    links_by_goal = defaultdict(list)
    for link in GoalAccountLink.objects.open().filter(goal__in=goals).select_related("account"):
        links_by_goal[link.goal_id].append(link.account.name)

    goal_items = []
    for goal in goals:
        saved = goal.allocated
        this_month = goal.saved_this_month or Decimal("0")
        if goal.has_target:
            remaining, pct = goal.to_fund, goal.progress_percentage
        else:
            pct, remaining = _goal_card_progress(goal, saved, this_month)
        # The spent part of the fill, drawn hatched: spending doesn't slide the bar back.
        spent_pct = min(max(float(goal.spent / goal.target_amount * 100), 0), pct) if goal.has_target else 0

        # The plan: a monthly contribution, or the pace to hit the target date. One
        # projection (`goal_plan`) gives the finish month and the status, so the card
        # can't show two dates that disagree.
        plan = goal_plan(goal, month)
        needed_per_month = None
        if plan and plan["rate"] > 0 and (remaining > 0 or not goal.has_target):
            needed_per_month = plan["rate"]
        behind_pace = bool(plan and plan["status"] == "behind")

        goal_items.append(
            {
                "goal": goal,
                "saved": saved,
                "remaining": remaining,
                "pct": pct,
                "this_month": this_month,
                "has_target": goal.has_target,
                "needed_per_month": needed_per_month,
                "plan_finish": plan["finish"] if plan else None,
                "plan_late": bool(plan and plan["late"]),
                "rate_for_date": plan["rate_for_date"] if plan else None,
                "plan_status": plan["status"] if plan else None,
                "plan_status_label": plan["status_label"] if plan else None,
                "links": links_by_goal.get(goal.pk, []),
                "behind_pace": behind_pace,
                "funded": goal.is_funded,
                "spent": goal.spent,
                "spent_this_month": goal.spent_this_month,
                "left": goal.left,
                "cover_amount": max(-goal.left, Decimal("0")),
                "spent_pct": spent_pct,
                "state": goal.state,
                "state_label": goal.state_label,
                "closed": goal.is_closed,
                "spending_url": _goal_spending_url(goal, request.book),
            }
        )

    # Get net worth card data
    net_worth_service = NetWorthService(request.book)
    net_worth_card = net_worth_service.get_net_worth_card_data(month)
    available = net_worth_card["available"]

    on_track_count = sum(1 for item in goal_items if item["funded"] or not item["behind_pace"])

    total_saved = summary["total_saved"]

    goals_props = {
        "month": month.isoformat(),
        "available": float(available),
        # The metric's name is still being decided; the toasts read it from here.
        "unassignedLabel": str(UNASSIGNED_LABEL),
        "overAssignedLabel": str(OVER_ASSIGNED_LABEL),
        "totalSaved": float(total_saved),
    }

    return render(
        request,
        "budget/goals_list.html",
        {
            "active_tab": "goals",
            "page_title": f"Goals | {book_display_name(request.book)}",
            "month": month,
            "goal_items": goal_items,
            "summary": summary,
            "available": available,
            "on_track_count": on_track_count,
            "net_worth_card": net_worth_card,
            "goals_props": goals_props,
            "prev_month": month - relativedelta(months=1),
            "next_month": month + relativedelta(months=1),
            "show_closed": show_closed,
            "closed_count": closed_count,
        },
    )


def _goal_spending_url(goal, book):
    """The Transactions page filtered to the goal's account (its spending)."""
    if not goal.account_id:
        return None
    base = reverse("journal:transactions_home", args=book.url_args)
    return f"{base}?{urlencode({'f_debit_account': f'a:{goal.account_id}'})}"


def _goal_numbers(goal, month):
    """(allocated, spent, saved in `month`) for `goal` as of the end of `month`."""
    numbers = (
        Goal.objects.filter(pk=goal.pk).with_progress(month).values("allocated", "spent", "saved_this_month").get()
    )
    return numbers["allocated"], numbers["spent"], numbers["saved_this_month"] or Decimal("0")


@login_and_book_required
@require_POST
def goal_assign_available(request, team_slug, book_slug, pk):
    """Assign funds to a goal for a month (JSON endpoint for the goals page).

    Body: {"month": "YYYY-MM-DD", "amount": "123.45"}. Without "amount", assigns
    all currently-available funds, capped at what the goal still needs. Amounts
    are *added* to the month's existing allocation.
    """
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)

    try:
        payload = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    if goal.is_archived or goal.is_closed:
        return JsonResponse({"error": "This goal is no longer active."}, status=400)
    # A funded goal stops asking for money (no quick-assign), but an explicit
    # amount still goes in -- that's how an overspent goal is covered or paid back.
    if goal.is_complete and payload.get("amount") is None:
        return JsonResponse({"error": "This goal is already fully funded."}, status=400)

    month = _parse_month(payload.get("month"))

    with transaction.atomic():
        budget_ledger.lock(request.book)
        month_amount = budget_ledger.goal_allocation(request.book, goal, month)
        old_saved, spent, saved_month = _goal_numbers(goal, month)
        _, remaining = _goal_card_progress(goal, old_saved, saved_month)
        available = NetWorthService(request.book).get_net_worth_card_data(month)["available"]

        raw_amount = payload.get("amount")
        if raw_amount is None:
            if goal.has_target and remaining <= 0:
                return JsonResponse({"error": "This goal is already fully funded."}, status=400)
            # An open-ended goal asks for this month's contribution; once that's
            # in, "add all available" means exactly that.
            amount = min(available, remaining) if remaining > 0 else available
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
        GoalService(request.book).update_allocation(goal, month, month_amount + amount)

    new_saved = old_saved + amount
    old_pct, _ = _goal_card_progress(goal, old_saved, saved_month)
    new_pct, new_remaining = _goal_card_progress(goal, new_saved, saved_month + amount)

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
            "remaining": float(new_remaining),
            "this_month": float(month_amount + amount),
            "new_available": float(available - amount),
            "completed": goal.has_target and new_saved >= goal.target_amount,
            "open_ended": not goal.has_target,
            "spent": float(spent),
            "left": float(new_saved - spent),
        }
    )


@login_and_book_required
@require_POST
def goal_withdraw(request, team_slug, book_slug, pk):
    """Take funds back out of a goal (JSON endpoint for the goals page).

    Body: {"month": "YYYY-MM-DD", "amount": "123.45"}. Without "amount",
    withdraws everything the goal has left. The withdrawal is recorded against
    the given month's allocation (which may go negative), so past months'
    contribution history is never rewritten. Money already spent from the goal
    can't be withdrawn: the cap is left (allocated − spent), not allocated.
    """
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)

    try:
        payload = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    # Funded goals stay withdrawable — that's how a finished goal is cashed out
    if goal.is_archived:
        return JsonResponse({"error": "This goal is archived."}, status=400)
    if goal.is_closed:
        return JsonResponse({"error": "This goal is closed."}, status=400)

    month = _parse_month(payload.get("month"))

    with transaction.atomic():
        budget_ledger.lock(request.book)
        month_amount = budget_ledger.goal_allocation(request.book, goal, month)
        old_saved, spent, saved_month = _goal_numbers(goal, month)
        left = old_saved - spent
        available = NetWorthService(request.book).get_net_worth_card_data(month)["available"]

        if left <= 0:
            return JsonResponse({"error": "Nothing left in this goal to withdraw."}, status=400)

        raw_amount = payload.get("amount")
        if raw_amount is None:
            amount = left
        else:
            try:
                amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except (InvalidOperation, TypeError, ValueError):
                return JsonResponse({"error": "Invalid amount."}, status=400)
            if not amount.is_finite() or amount <= 0 or amount > GRID_MAX_AMOUNT:
                return JsonResponse({"error": "Invalid amount."}, status=400)
            if amount > left:
                return JsonResponse(
                    {"error": f"This goal only has ${left:,.2f} left."},
                    status=400,
                )

        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        GoalService(request.book).update_allocation(goal, month, month_amount - amount)

    new_saved = old_saved - amount
    old_pct, _ = _goal_card_progress(goal, old_saved, saved_month)
    new_pct, new_remaining = _goal_card_progress(goal, new_saved, saved_month - amount)

    log_event(
        AuditEvent.GOAL_FUNDS_WITHDRAWN,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "month": month.isoformat(),
            "amount": str(amount),
            "withdraw_all": raw_amount is None,
        },
    )

    return JsonResponse(
        {
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "withdrawn": float(amount),
            "old_saved": float(old_saved),
            "new_saved": float(new_saved),
            "old_pct": old_pct,
            "new_pct": new_pct,
            "remaining": float(new_remaining),
            "this_month": float(month_amount - amount),
            "new_available": float(available + amount),
            "funded": goal.has_target and new_saved >= goal.target_amount,
            "open_ended": not goal.has_target,
            "spent": float(spent),
            "left": float(new_saved - spent),
        }
    )


def _log_link_changes(request, goal, changes, outflow_before=None):
    """Audit what saving the goal form did to its linked accounts and outflow setting."""
    for link in changes.linked:
        log_event(
            AuditEvent.GOAL_ACCOUNT_LINKED,
            request=request,
            metadata={
                "goal_id": goal.pk,
                "goal_name": goal.name,
                "account_id": link.account_id,
                "account_name": link.account.name,
                "start_date": link.start_date.isoformat(),
                "include_starting_balance": link.include_starting_balance,
            },
        )
    for link in changes.updated:
        log_event(
            AuditEvent.GOAL_ACCOUNT_LINKED,
            request=request,
            metadata={
                "goal_id": goal.pk,
                "goal_name": goal.name,
                "account_id": link.account_id,
                "account_name": link.account.name,
                "start_date": link.start_date.isoformat(),
                "include_starting_balance": link.include_starting_balance,
                "updated": True,
            },
        )
    for link in changes.unlinked:
        _log_unlinked(request, goal, link)
    if outflow_before is not None and outflow_before != goal.outflow:
        log_event(
            AuditEvent.GOAL_OUTFLOW_CHANGED,
            request=request,
            metadata={"goal_id": goal.pk, "goal_name": goal.name, "from": outflow_before, "to": goal.outflow},
        )


def _log_unlinked(request, goal, link):
    log_event(
        AuditEvent.GOAL_ACCOUNT_UNLINKED,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "account_id": link.account_id,
            "account_name": link.account.name,
            "end_date": link.end_date.isoformat() if link.end_date else None,
        },
    )


def _goal_form_view(request, goal=None):
    """Create (`goal` None) or edit a goal, with the accounts its money lives in."""
    is_new = goal is None
    book = request.book
    link_error = None
    link_error_goal = None
    if request.method == "POST":
        form = GoalForm(request.POST, instance=goal, book=book)
        outflow_before = None if is_new else goal.outflow
        try:
            rows = goal_links.parse_link_rows(book, request.POST)
        except goal_links.LinkError as e:
            rows, link_error, link_error_goal = None, str(e), e.goal
        if form.is_valid() and link_error is None:
            try:
                with transaction.atomic():
                    saved = form.save(commit=False)
                    saved.book = book
                    saved.save()
                    changes = goal_links.set_links(saved, rows)
            except goal_links.LinkError as e:
                link_error, link_error_goal = str(e), e.goal
                if is_new:
                    # The rolled-back save left a pk on the unsaved instance.
                    form.instance.pk = None
            else:
                _log_link_changes(request, saved, changes, outflow_before)
                if is_new:
                    messages.success(request, _("Goal created successfully."))
                    return redirect("budget:goals_list", *book.url_args)
                messages.success(request, _("Goal updated successfully."))
                return redirect("budget:goal_detail", *book.url_args, saved.pk)
        options = goal_links.link_options(book, goal, request.POST)
    else:
        form = GoalForm(instance=goal, book=book)
        options = goal_links.link_options(book, goal)

    allocated = Decimal("0")
    if not is_new:
        allocated = Goal.objects.filter(pk=goal.pk).with_progress().values_list("allocated", flat=True).get()
    form_props = {
        "previewUrl": reverse("budget:goal_link_preview", args=book.url_args),
        "goalId": None if is_new else goal.pk,
        "allocated": float(allocated),
    }
    return render(
        request,
        "budget/goal_form.html",
        {
            "active_tab": "goals",
            "page_title": (
                f"New Goal | {book_display_name(book)}" if is_new else f"Edit {goal.name} | {book_display_name(book)}"
            ),
            "form": form,
            "goal": goal,
            "is_new": is_new,
            "link_options": options,
            "link_error": link_error,
            # Another goal standing in the way, to link to (it may be archived, and
            # so on no list).
            "link_error_goal": link_error_goal,
            "any_linked": any(option["checked"] for option in options),
            "form_props": form_props,
        },
    )


@login_and_book_required
def goal_create_view(request, team_slug, book_slug):
    """Create a new goal."""
    return _goal_form_view(request)


@login_and_book_required
def goal_detail_view(request, team_slug, book_slug, pk):
    """View a single goal: its numbers, plan, linked accounts and activity."""
    month = _month_from_request(request)
    goal = get_object_or_404(Goal.objects.filter(book=request.book).with_progress(month), pk=pk)
    links = list(goal.account_links.select_related("account").order_by("end_date", "start_date"))

    return render(
        request,
        "budget/goal_detail.html",
        {
            "active_tab": "goals",
            "page_title": f"{goal.name} | {book_display_name(request.book)}",
            "goal": goal,
            "plan": goal_plan(goal, month),
            "progress_pct": _goal_card_progress(goal, goal.allocated, goal.saved_this_month or Decimal("0"))[0],
            "open_links": [link for link in links if link.is_open],
            "past_links": [link for link in links if not link.is_open],
            "activity": goal_links.goal_activity(goal),
            # A closed goal's history includes its own release; it stays as written.
            "can_edit_contributions": not goal.is_closed and not goal.is_archived,
            "delete_blocked": GoalService(request.book).delete_blocked_reason(goal),
            "spending": GoalService(request.book).spending_lines(goal, limit=50),
            "drift": goal_links.link_drift(goal, goal.left),
            "spending_url": _goal_spending_url(goal, request.book),
        },
    )


@login_and_book_required
def goal_update_view(request, team_slug, book_slug, pk):
    """Update an existing goal."""
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)
    return _goal_form_view(request, goal)


@login_and_book_required
@require_GET
def goal_link_preview(request, team_slug, book_slug):
    """
    What saving the goal form's linked accounts and outflow setting would do, for
    the form's live preview: takes the form's own fields as a query string.
    """
    book = request.book
    goal = None
    goal_id = request.GET.get("goal")
    if goal_id:
        goal = get_object_or_404(Goal.objects.filter(book=book), pk=goal_id)
    outflow = request.GET.get("outflow") or Goal.OUTFLOW_WITHDRAW
    if outflow not in dict(Goal.OUTFLOW_CHOICES):
        return JsonResponse({"ok": False, "error": _("Choose what money moving out does.")}, status=400)
    try:
        rows = goal_links.parse_link_rows(book, request.GET)
        result = goal_links.preview(book, goal, rows, outflow)
    except goal_links.LinkError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    return JsonResponse(
        {
            "ok": True,
            "adds": float(result["adds"]),
            "addsDisplay": currency(result["adds"]),
            "leftBefore": float(result["left_before"]),
            "leftAfter": float(result["left_after"]),
            "unassignedBefore": float(result["unassigned_before"]),
            "unassignedAfter": float(result["unassigned_after"]),
            "unassignedBeforeDisplay": currency(result["unassigned_before"]),
            "unassignedAfterDisplay": currency(result["unassigned_after"]),
        }
    )


@login_and_book_required
@require_POST
def goal_unlink(request, team_slug, book_slug, link_pk):
    """Stop an account feeding a goal. What it already brought in stays."""
    link = get_object_or_404(GoalAccountLink.objects.filter(book=request.book).select_related("goal"), pk=link_pk)
    goal = link.goal
    try:
        goal_links.unlink(link)
    except goal_links.LinkError as e:
        messages.error(request, str(e))
    else:
        if link.pk:
            link.refresh_from_db()
        _log_unlinked(request, goal, link)
        messages.success(
            request,
            _("%(account)s no longer feeds %(goal)s. What it already brought in stays.")
            % {"account": link.account.name, "goal": goal.name},
        )
    return redirect("budget:goal_detail", *request.book.url_args, goal.pk)


@login_and_book_required
@require_POST
def goal_contribution_edit(request, team_slug, book_slug, line_pk):
    """
    Change or undo a past month's manual contribution, from the goal page's
    activity table. `action=undo` removes it; otherwise `amount` replaces it
    (negative = a withdrawal; 0 = undo). The contribution is named by its line on
    the month's budget entry (the goal bucket's); money from linked accounts has
    no such line, so it can't be reached here.
    """
    from apps.journal.models import JournalEntry, JournalLine

    line = get_object_or_404(
        JournalLine.objects.filter(
            book=request.book,
            journal_entry__source=JournalEntry.SOURCE_BUDGET,
            account__paired_account__goal__isnull=False,
        ).select_related("journal_entry", "account"),
        pk=line_pk,
    )
    goal = get_object_or_404(Goal.objects.filter(book=request.book), account_id=line.account.paired_account_id)
    month = line.journal_entry.entry_date
    back = redirect("budget:goal_detail", *request.book.url_args, goal.pk)

    if request.POST.get("action") == "undo":
        amount = Decimal("0")
    else:
        amount = evaluate_amount(request.POST.get("amount", ""))
        if amount is None or abs(amount) > GRID_MAX_AMOUNT:
            messages.error(request, _("Enter an amount, like 250 or -40 for a withdrawal."))
            return back

    try:
        old = GoalService(request.book).edit_allocation(goal, month, amount)
    except GoalAllocationError as e:
        messages.error(request, str(e))
        return back
    if old == amount:
        return back

    month_label = date_format(month, "F Y")
    log_event(
        AuditEvent.GOAL_CONTRIBUTION_EDITED,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "month": month.isoformat(),
            "from": str(old),
            "to": str(amount),
            "undo": amount == 0,
        },
    )
    if amount == 0:
        messages.success(
            request,
            _("Undid the %(amount)s %(kind)s in %(month)s.")
            % {
                "amount": currency(abs(old)),
                "kind": _("contribution") if old > 0 else _("withdrawal"),
                "month": month_label,
            },
        )
    else:
        messages.success(
            request,
            _("%(month)s changed from %(old)s to %(new)s.")
            % {"month": month_label, "old": currency(old), "new": currency(amount)},
        )
    return back


@login_and_book_required
@require_POST
def goal_destroy(request, team_slug, book_slug, pk):
    """
    Delete a goal for good -- open, closed or archived -- with its contributions
    and account links, freeing its name and its accounts' history. Refused while
    transactions are categorized to it.
    """
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)
    try:
        summary = GoalService(request.book).delete(goal)
    except GoalDeleteError as e:
        messages.error(request, str(e))
        return redirect("budget:goal_detail", *request.book.url_args, pk)
    log_event(AuditEvent.GOAL_DELETED, request=request, metadata={"goal_id": pk, **summary})
    messages.success(request, _("Deleted %(goal)s.") % {"goal": summary["goal_name"]})
    return redirect("budget:goals_list", *request.book.url_args)


@login_and_book_required
def goal_delete_view(request, team_slug, book_slug, pk):
    """Delete a goal (or archive it)."""
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)

    if request.method == "POST":
        # Archiving hides a goal. An open goal is closed first, which releases
        # anything left in it -- a hidden goal must not keep holding money.
        if not goal.is_closed:
            try:
                result = GoalService(request.book).close(goal, _month_from_request(request))
            except GoalCloseError as e:
                messages.error(request, str(e))
                return redirect("budget:goal_detail", team_slug=team_slug, book_slug=book_slug, pk=pk)
            goal.refresh_from_db()
            _log_goal_closed(request, goal, result, via="archive")
        goal.is_archived = True
        goal.save()
        messages.success(request, _("Goal archived successfully."))
        return redirect("budget:goals_list", team_slug=team_slug, book_slug=book_slug)

    return render(
        request,
        "budget/goal_confirm_delete.html",
        {
            "active_tab": "goals",
            "page_title": f"Archive {goal.name} | {book_display_name(request.book)}",
            "goal": goal,
        },
    )


@login_and_book_required
def goal_allocation_update_view(request, team_slug, book_slug, pk):
    """Update a goal allocation for a specific month."""
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)

    if request.method == "POST":
        amount = request.POST.get("amount", "0")
        month = _parse_month(request.POST.get("month"))

        amount = evaluate_amount(amount) or Decimal("0")
        if amount < 0:
            messages.error(request, _("Allocation amount cannot be negative."))
            return redirect(f"/a/{team_slug}/{book_slug}/budget/goals/?month={month.isoformat()}")

        service = GoalService(request.book)
        service.update_allocation(goal, month, amount)

        # Return to goals list at the same month
        return redirect(f"/a/{team_slug}/{book_slug}/budget/goals/?month={month.isoformat()}")

    return redirect("budget:goals_list", team_slug=team_slug, book_slug=book_slug)


@login_and_book_required
def goal_complete_view(request, team_slug, book_slug, pk):
    """Mark a goal as funded: it stops asking for money but keeps its claim."""
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)

    if request.method == "POST":
        goal.is_complete = True
        goal.save()
        messages.success(request, _("Congratulations! Goal marked as funded."))

    return redirect("budget:goal_detail", team_slug=team_slug, book_slug=book_slug, pk=pk)


def _log_goal_closed(request, goal, result, via):
    log_event(
        AuditEvent.GOAL_CLOSED,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "released": str(result["released"]),
            "covered": str(result["covered"]),
            "via": via,
        },
    )


def _next_url(request, default):
    """A same-site `next` from the form, or `default`."""
    from django.utils.http import url_has_allowed_host_and_scheme

    candidate = request.POST.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return default


@login_and_book_required
@require_POST
def goal_close_view(request, team_slug, book_slug, pk):
    """
    Close a goal (form post). Anything left is released back to Unassigned; a
    negative goal is topped back up to zero first when `cover` is sent (free: the
    overspending already came out of Unassigned), and
    otherwise refused (it can stay open and be paid back instead).
    """
    goal = get_object_or_404(Goal.objects.filter(book=request.book, is_archived=False), pk=pk)
    month = _parse_month(request.POST.get("month")) if request.POST.get("month") else _month_from_request(request)
    back = _next_url(request, reverse("budget:goals_list", args=request.book.url_args))
    try:
        result = GoalService(request.book).close(goal, month, cover=bool(request.POST.get("cover")))
    except GoalCloseError as e:
        messages.error(request, str(e))
        return redirect(back)

    _log_goal_closed(request, goal, result, via="close")
    if result["released"]:
        messages.success(
            request,
            _("%(name)s closed. %(amount)s went back to your unassigned money.")
            % {"name": goal.name, "amount": currency(result["released"])},
        )
    elif result["covered"]:
        messages.success(
            request,
            _("%(name)s closed. %(amount)s covered its overspending.")
            % {"name": goal.name, "amount": currency(result["covered"])},
        )
    else:
        messages.success(request, _("%(name)s closed.") % {"name": goal.name})
    return redirect(back)
