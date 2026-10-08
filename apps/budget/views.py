import json
import math
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateformat import format as date_format
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import Account
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name
from apps.utils.amounts import evaluate_amount
from apps.web.templatetags.currency_tags import currency

from . import goal_links
from .forms import MAX_BUDGET_AMOUNT, BudgetAmountForm, GoalForm, parse_budget_amount
from .models import Budget, Goal, GoalAccountLink, GoalAllocation
from .services import (
    BudgetService,
    GoalAllocationError,
    GoalCloseError,
    GoalService,
    NetWorthService,
    budgeted_account_types,
    goal_monthly,
    goal_plan,
    picker_accounts_data,
)
from .unassigned import OVER_ASSIGNED_LABEL, UNASSIGNED_LABEL, compute_unassigned, pill_context


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


def _zero_totals():
    return {"budgeted": Decimal("0"), "actual": Decimal("0"), "available": Decimal("0")}


def _budget_figures(book, month):
    """Every number the budget page shows for `month`, computed in one place.

    The month view renders these; the auto-save endpoint recomputes them and
    returns just the values (see `_budget_cells`), so saving an amount updates
    the page in place instead of reloading it.
    """
    service = BudgetService(book)
    categories = list(_budget_categories(book))

    # Rows are created lazily on first save; a category without one shows zero.
    existing_budgets = {b.category_id: b for b in Budget.objects.filter(book=book, month=month)}
    actuals_map = service.get_actuals_by_category(month)
    # This month's balances and last month's (what rolled in) from one walk of
    # the budget history.
    available_map, prev_available_map = service.get_available_with_previous(month, categories)

    # Income section first, then expenses; groups within a section keep the
    # category ordering (board sort order, then group/account name).
    sections = {
        "income": {"key": "income", "label": _("Income"), "groups": [], "totals": _zero_totals()},
        "expense": {"key": "expense", "label": _("Expenses"), "groups": [], "totals": _zero_totals()},
    }

    # A hidden category is a display choice, not an accounting one: it leaves its
    # account group for a collapsed "Hidden" group at the end of its section, and
    # its figures keep counting in the section totals, the sidebar and Unassigned.
    hidden_groups = {}

    for category in categories:
        budget = existing_budgets.get(category.pk)
        budgeted = budget.budget_amount if budget else Decimal("0")
        actual = actuals_map.get(category.pk, Decimal("0"))
        available = available_map.get(category.pk, Decimal("0"))

        section_key = "income" if category.account_group.account_type == "income" else "expense"
        section = sections[section_key]
        if category.hidden_from_budget:
            group = hidden_groups.setdefault(section_key, _hidden_group())
        else:
            group_name = category.account_group.name
            if not section["groups"] or section["groups"][-1]["name"] != group_name:
                section["groups"].append({"name": group_name, "rows": [], "subtotals": _zero_totals()})
            group = section["groups"][-1]

        # The input has no visible label — the category is its row header.
        form = BudgetAmountForm(instance=budget)
        form.fields["budget_amount"].widget.attrs["aria-label"] = _("%(category)s budget") % {"category": category.name}

        group["rows"].append(
            {
                "category": category,
                "form": form,
                "budgeted": budgeted,
                "actual": actual,
                "available": available,
                "meter": _meter(category.account_group.account_type, budgeted, actual, available),
            }
        )

        for field, amount in (("budgeted", budgeted), ("actual", actual), ("available", available)):
            group["subtotals"][field] += amount
            section["totals"][field] += amount

    for section_key, group in hidden_groups.items():
        group["overspent"] = sum(1 for row in group["rows"] if row["available"] < 0)
        sections[section_key]["groups"].append(group)
        sections[section_key]["hidden_count"] = len(group["rows"])

    section_list = [sections["income"], sections["expense"]]

    # Grand totals across both sections (sidebar summary)
    grand_totals = {
        field: sections["income"]["totals"][field] + sections["expense"]["totals"][field]
        for field in ("budgeted", "actual", "available")
    }

    leftover_last_month = sum(prev_available_map.values(), Decimal("0"))

    return {
        "categories": categories,
        "sections": section_list,
        "has_categories": bool(categories),
        "grand_totals": grand_totals,
        "sidebar_summary": {
            "leftover_last_month": leftover_last_month,
            "assigned_this_month": grand_totals["budgeted"],
            "activity_this_month": grand_totals["actual"],
            "available": grand_totals["available"],
        },
        "net_worth_card": NetWorthService(book).get_net_worth_card_data(month, categories),
    }


def _hidden_group():
    return {"name": _("Hidden"), "hidden": True, "rows": [], "subtotals": _zero_totals()}


def _meter(account_type, budgeted, actual, available):
    """The progress bar beside a budget row.

    Expense: spent against what there was to spend this month -- the budget plus
    whatever rolled in (the previous Available, which is `available − budgeted +
    actual`), so a full bar and a zero Available are the same thing. Red once
    Available is negative. Income: received against expected.
    """
    if account_type == "income":
        whole = budgeted
        over = False
    else:
        rolled_in = available - budgeted + actual
        whole = budgeted + max(rolled_in, Decimal("0"))
        over = available < 0
    pct = float(actual / whole * 100) if whole > 0 else None
    # No budget to measure against: a full bar if anything was spent, else empty.
    width = (100 if actual > 0 else 0) if pct is None else max(min(round(pct), 100), 0)
    return {
        "pct": pct,
        "width": width,
        "over": over,
        "income": account_type == "income",
        "label": f"{round(pct)}%" if pct is not None else "—",
    }


def _tone(amount):
    """Sign class hint for a money cell; mirrors the templates' text-error/text-success."""
    if amount < 0:
        return "neg"
    if amount > 0:
        return "pos"
    return ""


def _budget_cells(figures):
    """Flatten `_budget_figures` into `{cell key: {value, tone}}` for the auto-save
    response. Keys match the `data-budget-cell` attributes in the templates.

    Actuals are left out: a budget amount never moves them, and a recategorized
    transaction's actuals are updated by the Actual popover itself.
    """
    cells = {}

    def put(key, amount, toned=False):
        cells[key] = {"value": currency(amount), "tone": _tone(amount) if toned else ""}

    for section in figures["sections"]:
        for index, group in enumerate(section["groups"]):
            for row in group["rows"]:
                pk = row["category"].pk
                put(f"row:{pk}:available", row["available"], toned=True)
                meter = row["meter"]
                cells[f"row:{pk}:meter"] = {
                    "value": meter["label"],
                    "tone": "neg" if meter["over"] else "",
                    "width": meter["width"],
                }
                # Not rendered — the Auto-Assign confirm dialog reads it off the row checkbox.
                cells[f"row:{pk}:budgeted"] = {"value": f"{row['budgeted']:.2f}", "tone": ""}
            put(f"group:{section['key']}:{index}:budgeted", group["subtotals"]["budgeted"])
            put(f"group:{section['key']}:{index}:available", group["subtotals"]["available"], toned=True)
        put(f"section:{section['key']}:budgeted", section["totals"]["budgeted"])
        put(f"section:{section['key']}:available", section["totals"]["available"])

    summary = figures["sidebar_summary"]
    put("sidebar:assigned", summary["assigned_this_month"])
    put("sidebar:available", summary["available"], toned=True)

    card = figures["net_worth_card"]
    put("networth:net_worth", card["net_worth"])
    put("networth:income_due", card["income_due"])
    put("networth:spend", card["spend"])
    put("networth:save", card["save"])
    put("networth:available", card["available"], toned=True)
    # The line's own name flips to "Over-assigned" when the figure goes negative.
    cells["networth:label"] = {"value": str(card["label"]), "tone": ""}

    return cells


@login_and_book_required
def budget_month_view(request, team_slug, book_slug):
    month = _month_from_request(request)

    if request.method == "POST":
        # The <noscript> fallback: a full form post per row. With JS the page
        # saves through `budget_save_amount` instead and never navigates.
        # Budget rows are created lazily on first save (a GET must not write).
        # The form posts budget_id when a row already exists, category_id otherwise.
        # Only the categories this book budgets: with future income off, an income
        # row is refused here exactly as the JSON endpoints refuse it.
        budget_id = request.POST.get("budget_id")
        if budget_id:
            budget = get_object_or_404(
                Budget, id=budget_id, book=request.book, category__in=_budget_categories(request.book)
            )
        else:
            category = get_object_or_404(_budget_categories(request.book), id=request.POST.get("category_id"))
            budget, _created = Budget.objects.get_or_create(
                book=request.book,
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
            return redirect(f"/a/{team_slug}/{book_slug}/budget/?month={month.isoformat()}")
        messages.error(request, _("Could not save budget amount: %(errors)s") % {"errors": form.errors.as_text()})

    context = _budget_swap_context(request.book, month)
    # Every account type is a valid "Move to..." target in the Actual popup (the
    # client groups them by type); moving onto a feed account makes it a transfer.
    # System accounts (reconciliation adjustments) are bookkeeping, not destinations.
    context["all_accounts"] = picker_accounts_data(request.book)
    context["api_urls"] = {"lines": f"/a/{team_slug}/{book_slug}/journal/api/lines/"}
    context["active_tab"] = "budget"
    context["page_title"] = f"Budget | {book_display_name(request.book)}"
    return render(request, "budget/budget_home.html", context)


def _budget_swap_context(book, month):
    """What `budget/components/budget_swap.html` renders: the month's figures and
    the URLs its forms post to. The month view adds the page chrome around it."""
    figures = _budget_figures(book, month)
    return {
        "month": month,
        "end_date": month + relativedelta(months=1, days=-1),
        "sections": figures["sections"],
        "has_categories": figures["has_categories"],
        "grand_totals": figures["grand_totals"],
        "net_worth_card": figures["net_worth_card"],
        "sidebar_summary": figures["sidebar_summary"],
        "prev_month": month - relativedelta(months=1),
        "next_month": month + relativedelta(months=1),
        "save_amount_url": reverse("budget:budget_save_amount", args=book.url_args),
        "figures_url": reverse("budget:budget_figures", args=book.url_args),
        "cover_url": reverse("budget:budget_cover", args=book.url_args),
        # Goals an overspent category can be covered from (emergency fund, ...), besides Unassigned.
        "cover_goals": [
            {"id": goal.pk, "name": goal.name, "left": f"{goal.left:.2f}"}
            for goal in GoalService(book).get_goals_with_progress(month)
        ],
    }


@login_and_book_required
@require_GET
def unassigned_api(request, team_slug, book_slug):
    """The Unassigned figure for the current month, for the sidebar pill to refresh
    itself after any write (see assets/javascript/unassigned/unassigned-pill.js)."""
    return JsonResponse(pill_context(compute_unassigned(request.book, date.today())))


@login_and_book_required
@require_GET
def budget_figures(request, team_slug, book_slug):
    """Every figure the budget page shows for `?month=` (the same cells `budget_save_amount`
    returns), for repainting after a write made elsewhere on the page — moving a
    transaction to another category from the Actual popover changes actuals, and with
    them Available, the meters, the totals and Unassigned.
    """
    month = parse_date(request.GET.get("month") or "")
    if month is None:
        return JsonResponse({"error": _("Invalid month.")}, status=400)
    month = month.replace(day=1)
    return JsonResponse({"cells": _budget_cells(_budget_figures(request.book, month))})


@login_and_book_required
@require_POST
def budget_save_amount(request, team_slug, book_slug):
    """Save one budget amount and return every figure the page shows for that month.

    The budget table posts here on blur/Enter so the row, its subtotals, the
    section totals, the sidebar summary and the net-worth card all update in
    place — the old full-page redirect reset the scroll position and focus on
    every save, which made typing down a column unusable.

    Body: {"category_id": int, "month": "YYYY-MM-DD", "amount": "123.45"}
    """
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return JsonResponse({"error": _("Invalid request body.")}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    try:
        category_id = int(payload.get("category_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": _("Unknown budget category.")}, status=400)
    category = _budget_categories(request.book).filter(pk=category_id).first()
    if category is None:
        return JsonResponse({"error": _("Unknown budget category.")}, status=400)

    month = parse_date(str(payload.get("month") or ""))
    if month is None:
        return JsonResponse({"error": _("Invalid month.")}, status=400)
    month = month.replace(day=1)

    amount = parse_budget_amount(payload.get("amount"))
    if amount is None:
        return JsonResponse({"error": _("Enter a number, for example 250 or 1,250.50.")}, status=400)

    with transaction.atomic():
        budget, created = Budget.objects.select_for_update().get_or_create(
            book=request.book,
            category=category,
            month=month,
            defaults={"budget_amount": amount},
        )
        if not created and budget.budget_amount != amount:
            budget.budget_amount = amount
            budget.save(update_fields=["budget_amount"])

    return JsonResponse(
        {
            "saved": True,
            "category_id": category.pk,
            "amount": f"{amount:.2f}",
            "cells": _budget_cells(_budget_figures(request.book, month)),
        }
    )


@login_and_book_required
@require_POST
def budget_category_visibility(request, team_slug, book_slug, pk):
    """Hide a category from the budget page, or bring it back.

    Form fields: `hidden` ("1" hides, anything else unhides) and `month`. A display
    choice only — nothing about the category's money changes. Three answers:

    - `X-Budget-Fragment: 1` (the page's own script): the re-rendered
      `#budget-swap` region for `month`, so the page updates in one round trip
      instead of a POST followed by a GET of the whole page.
    - `Accept: application/json`: `{category_id, hidden}`.
    - otherwise (no JS): a redirect back to the budget page.
    """
    category = get_object_or_404(_budget_categories(request.book), pk=pk)
    hidden = request.POST.get("hidden") == "1"
    if category.hidden_from_budget != hidden:
        category.hidden_from_budget = hidden
        category.save(update_fields=["hidden_from_budget", "updated_at"])

    month = _parse_month(request.POST.get("month"))
    if request.headers.get("X-Budget-Fragment") == "1":
        return render(request, "budget/components/budget_swap.html", _budget_swap_context(request.book, month))
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"category_id": category.pk, "hidden": hidden})

    template = _("%(category)s is hidden from the budget.") if hidden else _("%(category)s is back in the budget.")
    messages.success(request, template % {"category": category.name})
    return redirect(f"{reverse('budget:budget_home', args=request.book.url_args)}?month={month.isoformat()}")


@login_and_book_required
def budget_autofill_view(request, team_slug, book_slug):
    """Handle auto-fill budget actions from the sidebar."""
    if request.method != "POST":
        return redirect("budget:budget_home", team_slug=team_slug, book_slug=book_slug)

    action = request.POST.get("action")
    month = _parse_month(request.POST.get("month"))

    prev_month = month - relativedelta(months=1)
    service = BudgetService(request.book)

    # Hidden categories are left alone: a bulk fill is aimed at what is on screen.
    categories = list(
        Account.for_book.filter(
            account_group__account_type__in=budgeted_account_types(request.book),
            hidden_from_budget=False,
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
    existing_budgets = {b.category_id: b for b in Budget.objects.filter(book=request.book, month=month)}
    missing_budgets = []
    for category in categories:
        if category.pk not in existing_budgets:
            missing_budgets.append(
                Budget(
                    book=request.book,
                    category=category,
                    month=month,
                    budget_amount=0,
                )
            )
    if missing_budgets:
        Budget.objects.bulk_create(missing_budgets, ignore_conflicts=True)
        existing_budgets = {b.category_id: b for b in Budget.objects.filter(book=request.book, month=month)}

    if action == "assigned_last_month":
        prev_budgets = {
            b.category_id: b.budget_amount for b in Budget.objects.filter(book=request.book, month=prev_month)
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
        Budget.objects.filter(book=request.book, month=month, category_id__in=category_pks).update(
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

    return redirect(f"/a/{team_slug}/{book_slug}/budget/?month={month.isoformat()}")


# =============================================================================
# Multi-month grid editor
# =============================================================================

GRID_MAX_MONTHS = 24
GRID_DEFAULT_MONTHS = 12
GRID_MAX_AMOUNT = MAX_BUDGET_AMOUNT


def _budget_categories(book):
    """The categories a book budgets (see `budgeted_account_types`), in budget-table
    display order: income sections first, then expenses, each grouped alphabetically."""
    return (
        Account.objects.filter(book=book, account_group__account_type__in=budgeted_account_types(book))
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


# Reference figures shown beside the grid's month columns. Each mode is a window of
# whole months measured from today (not from the grid's range), so planning next
# year reads against this year's and last year's real spending.
GRID_ACTUAL_MODES = ("avg_this_year", "avg_last_year", "last_month")
CENTS = Decimal("0.01")


def _grid_actual_windows(today):
    """`{mode: (first_month, last_month, label, detail)}` for each actuals mode, or a
    `None` window when the mode has no complete month yet (January's "this year").

    Only complete months count: the running month would drag an average down."""
    this_month = today.replace(day=1)
    last_month = this_month - relativedelta(months=1)
    year_start = this_month.replace(month=1)
    last_year_start = year_start.replace(year=year_start.year - 1)
    last_year_end = year_start - relativedelta(months=1)

    def span(first, last):
        if first == last:
            return first.strftime("%b %Y")
        return f"{first.strftime('%b')}–{last.strftime('%b %Y')}"

    this_year = (year_start, last_month) if last_month >= year_start else None
    return {
        "avg_this_year": (
            *(this_year or (None, None)),
            _("Average this year"),
            _("Monthly average, %(span)s") % {"span": span(*this_year)} if this_year else _("No complete month yet"),
        ),
        "avg_last_year": (
            last_year_start,
            last_year_end,
            _("Average last year"),
            _("Monthly average, %(span)s") % {"span": span(last_year_start, last_year_end)},
        ),
        "last_month": (last_month, last_month, _("Last month"), last_month.strftime("%b %Y")),
    }


def _grid_actuals(book, categories, today):
    """Per-category actuals for every mode in `GRID_ACTUAL_MODES`.

    Returns `(modes, actuals)`: `modes` is `[{key, label, detail}]` for the picker,
    `actuals` is `{category_id: {mode: "123.45" | None}}` — None only when the mode's
    window holds no complete month. Averages divide by every month in the window, so
    a month with no spending counts as $0. One query covers all three windows."""
    windows = _grid_actual_windows(today)
    firsts = [w[0] for w in windows.values() if w[0]]
    lasts = [w[1] for w in windows.values() if w[1]]
    by_month = BudgetService(book).get_all_actuals_by_month_category(min(firsts), max(lasts))

    actuals = {}
    for category in categories:
        row = {}
        for mode in GRID_ACTUAL_MODES:
            first, last = windows[mode][0], windows[mode][1]
            if first is None:
                row[mode] = None
                continue
            months = (last.year - first.year) * 12 + last.month - first.month + 1
            total = sum(
                (by_month.get((first + relativedelta(months=i), category.pk), Decimal("0")) for i in range(months)),
                Decimal("0"),
            )
            row[mode] = str((total / months).quantize(CENTS, rounding=ROUND_HALF_UP))
        actuals[category.pk] = row

    modes = [
        {"key": mode, "label": str(windows[mode][2]), "detail": str(windows[mode][3])} for mode in GRID_ACTUAL_MODES
    ]
    return modes, actuals


@login_and_book_required
def budget_grid_view(request, team_slug, book_slug):
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

    # Hidden categories stay off the grid as they stay collapsed on the month page.
    categories = list(_budget_categories(request.book).filter(hidden_from_budget=False))
    actual_modes, actuals = _grid_actuals(request.book, categories, date.today())

    amounts = {}
    for budget in Budget.objects.filter(book=request.book, month__gte=months[0], month__lte=months[-1]):
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
                "actuals": actuals[category.pk],
            }
        )

    grid_props = {
        "months": [{"key": m.isoformat(), "label": m.strftime("%b %Y")} for m in months],
        "groups": groups,
        "actualModes": actual_modes,
        "start": start.isoformat(),
        "numMonths": num_months,
        "prevStart": (start - relativedelta(months=num_months)).isoformat(),
        "nextStart": (start + relativedelta(months=num_months)).isoformat(),
        "saveUrl": f"/a/{team_slug}/{book_slug}/budget/grid/save/",
        "budgetUrl": f"/a/{team_slug}/{book_slug}/budget/",
    }

    return render(
        request,
        "budget/budget_grid.html",
        {
            "active_tab": "budget",
            "page_title": f"Edit Budgets | {book_display_name(request.book)}",
            "grid_props": grid_props,
            "start": start,
            "end": months[-1],
        },
    )


@login_and_book_required
@require_POST
def budget_grid_save(request, team_slug, book_slug):
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
    valid_category_ids = set(_budget_categories(request.book).filter(pk__in=category_ids).values_list("pk", flat=True))

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
                book=request.book,
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
                creates.append(Budget(book=request.book, category_id=category_id, month=month, budget_amount=amount))
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
    style = _goals_style(request)
    show_closed = request.GET.get("show") == "closed"
    service = GoalService(request.book)
    summary = service.get_goal_summary(month, closed=show_closed)
    goals = summary["goals"]
    closed_count = Goal.objects.filter(book=request.book, is_archived=False, closed_at__isnull=False).count()

    # What each goal was given per month (assigned + from linked accounts);
    # used for streaks and pace.
    amounts_by_goal = {
        goal_id: {m: values["saved"] for m, values in months.items()}
        for goal_id, months in goal_monthly(request.book, goals).items()
    }

    links_by_goal = defaultdict(list)
    for link in GoalAccountLink.objects.open().filter(goal__in=goals).select_related("account"):
        links_by_goal[link.goal_id].append(link.account.name)

    goal_items = []
    any_streak_3 = False
    any_half_way = False
    big_month = False
    for goal in goals:
        amounts = amounts_by_goal.get(goal.pk, {})
        saved = goal.allocated
        this_month = goal.saved_this_month or Decimal("0")
        if goal.has_target:
            remaining, pct = goal.to_fund, goal.progress_percentage
        else:
            pct, remaining = _goal_card_progress(goal, saved, this_month)
        # The spent part of the fill, drawn hatched: spending doesn't slide the bar back.
        spent_pct = min(max(float(goal.spent / goal.target_amount * 100), 0), pct) if goal.has_target else 0

        saved_months = {m for m, amt in amounts.items() if amt > 0}
        streak = _goal_streak(saved_months, month)

        # The plan: a monthly contribution, or the pace to hit the target date.
        plan = goal_plan(goal, month)
        months_left = None
        needed_per_month = None
        if plan and plan["rate"] > 0 and (remaining > 0 or not goal.has_target):
            needed_per_month = plan["rate"]
            if plan["finish"]:
                finish = plan["finish"]
                months_left = max((finish.year - month.year) * 12 + finish.month - month.month, 1)

        # Projection from the recent saving rate (average of the last 3 months)
        recent = [amounts.get(month - relativedelta(months=i), Decimal("0")) for i in range(3)]
        recent_avg = sum(recent) / 3
        projected_date = None
        if goal.has_target and remaining > 0 and recent_avg > 0:
            projected_date = month + relativedelta(months=math.ceil(remaining / recent_avg))
        behind_pace = bool(plan and plan["status"] == "behind")

        any_streak_3 = any_streak_3 or streak >= 3
        any_half_way = any_half_way or pct >= 50
        big_month = big_month or any(amt >= 500 for amt in amounts.values())

        goal_items.append(
            {
                "goal": goal,
                "saved": saved,
                "remaining": remaining,
                "pct": pct,
                "this_month": this_month,
                "has_target": goal.has_target,
                "streak": streak,
                "months_left": months_left,
                "needed_per_month": needed_per_month,
                "plan_finish": plan["finish"] if plan else None,
                "plan_status": plan["status"] if plan else None,
                "plan_status_label": plan["status_label"] if plan else None,
                "links": links_by_goal.get(goal.pk, []),
                "projected_date": projected_date,
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
                "milestones": [25, 50, 75, 100],
            }
        )

    # Get net worth card data
    net_worth_service = NetWorthService(request.book)
    net_worth_card = net_worth_service.get_net_worth_card_data(month)
    available = net_worth_card["available"]

    on_track_count = sum(1 for item in goal_items if item["funded"] or not item["behind_pace"])

    total_saved = summary["total_saved"]
    has_completed_goal = Goal.objects.filter(book=request.book, is_complete=True).exists()
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
        # The metric's name is still being decided; the toasts read it from here.
        "unassignedLabel": str(UNASSIGNED_LABEL),
        "overAssignedLabel": str(OVER_ASSIGNED_LABEL),
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
            "page_title": f"Goals | {book_display_name(request.book)}",
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
        allocation = (
            GoalAllocation.objects.select_for_update().filter(book=request.book, goal=goal, month=month).first()
        )
        month_amount = allocation.amount if allocation else Decimal("0")
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
        allocation = (
            GoalAllocation.objects.select_for_update().filter(book=request.book, goal=goal, month=month).first()
        )
        month_amount = allocation.amount if allocation else Decimal("0")
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
    if request.method == "POST":
        form = GoalForm(request.POST, instance=goal, book=book)
        outflow_before = None if is_new else goal.outflow
        try:
            rows = goal_links.parse_link_rows(book, request.POST)
        except goal_links.LinkError as e:
            rows, link_error = None, str(e)
        if form.is_valid() and link_error is None:
            try:
                with transaction.atomic():
                    saved = form.save(commit=False)
                    saved.book = book
                    saved.save()
                    changes = goal_links.set_links(saved, rows)
            except goal_links.LinkError as e:
                link_error = str(e)
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
def goal_contribution_edit(request, team_slug, book_slug, allocation_pk):
    """
    Change or undo a past month's manual contribution, from the goal page's
    activity table. `action=undo` removes it; otherwise `amount` replaces it
    (negative = a withdrawal; 0 = undo). Money from linked accounts isn't a
    `GoalAllocation`, so it can't be reached here.
    """
    allocation = get_object_or_404(
        GoalAllocation.objects.filter(book=request.book).select_related("goal"), pk=allocation_pk
    )
    goal = allocation.goal
    back = redirect("budget:goal_detail", *request.book.url_args, goal.pk)

    if request.POST.get("action") == "undo":
        amount = Decimal("0")
    else:
        amount = evaluate_amount(request.POST.get("amount", ""))
        if amount is None or abs(amount) > GRID_MAX_AMOUNT:
            messages.error(request, _("Enter an amount, like 250 or -40 for a withdrawal."))
            return back

    try:
        old = GoalService(request.book).edit_allocation(allocation, amount)
    except GoalAllocationError as e:
        messages.error(request, str(e))
        return back
    if old == amount:
        return back

    month_label = date_format(allocation.month, "F Y")
    log_event(
        AuditEvent.GOAL_CONTRIBUTION_EDITED,
        request=request,
        metadata={
            "goal_id": goal.pk,
            "goal_name": goal.name,
            "month": allocation.month.isoformat(),
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


COVER_FROM_UNASSIGNED = "unassigned"
COVER_FROM_GOAL = "goal"


@login_and_book_required
@require_POST
def budget_cover(request, team_slug, book_slug):
    """
    Cover an overspent budget row (docs/goals-envelopes-plan.md §4.4).

    Body: {"category_id": int, "month": "YYYY-MM-DD", "amount": "123.45",
           "source": "unassigned" | "goal", "goal_id": int (with source "goal")}.

    - From Unassigned: the category's budget for the month rises by `amount`. The
      overspending already came out of Unassigned (an overspent envelope claims
      nothing), so filling the hole leaves Unassigned where it is; only an amount
      past the shortfall is a new claim on it.
    - From a goal: the goal gives up `amount` (a negative allocation this month) and
      the budget rises by the same, so the money the goal releases goes back into
      Unassigned. The goal may go negative -- overspending is carried.

    Either way it is one transaction, and the response carries every figure the
    budget page shows, like `budget_save_amount`.
    """
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return JsonResponse({"error": _("Invalid request body.")}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    source = payload.get("source") or (COVER_FROM_GOAL if payload.get("goal_id") else COVER_FROM_UNASSIGNED)
    if source not in (COVER_FROM_UNASSIGNED, COVER_FROM_GOAL):
        return JsonResponse({"error": _("Pick where the money comes from.")}, status=400)

    try:
        category_id = int(payload.get("category_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": _("Unknown budget category.")}, status=400)
    category = _budget_categories(request.book).filter(pk=category_id, account_group__account_type="expense").first()
    if category is None:
        return JsonResponse({"error": _("Unknown budget category.")}, status=400)

    goal = None
    if source == COVER_FROM_GOAL:
        try:
            goal_id = int(payload.get("goal_id"))
        except (TypeError, ValueError):
            return JsonResponse({"error": _("Pick a goal.")}, status=400)
        goal = Goal.objects.filter(book=request.book, pk=goal_id, is_archived=False, closed_at__isnull=True).first()
        if goal is None:
            return JsonResponse({"error": _("Unknown goal.")}, status=400)

    month = parse_date(str(payload.get("month") or ""))
    if month is None:
        return JsonResponse({"error": _("Invalid month.")}, status=400)
    month = month.replace(day=1)

    amount = parse_budget_amount(payload.get("amount"))
    if amount is None or amount <= 0 or amount > GRID_MAX_AMOUNT:
        return JsonResponse({"error": _("Enter an amount greater than zero.")}, status=400)

    if goal is None:
        budget = BudgetService(request.book).raise_budget(category, month, amount)
    else:
        budget = GoalService(request.book).cover_from_goal(goal, category, month, amount)
        log_event(
            AuditEvent.GOAL_COVERED_BUDGET,
            request=request,
            metadata={
                "goal_id": goal.pk,
                "goal_name": goal.name,
                "category_id": category.pk,
                "category_name": category.name,
                "month": month.isoformat(),
                "amount": str(amount),
            },
        )

    return JsonResponse(
        {
            "covered": True,
            "source": source,
            "category_id": category.pk,
            "amount": f"{budget.budget_amount:.2f}",
            "goal_left": f"{GoalService(request.book).left(goal, month):.2f}" if goal else None,
            "cells": _budget_cells(_budget_figures(request.book, month)),
        }
    )
