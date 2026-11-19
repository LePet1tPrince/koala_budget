from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateformat import format as date_format
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name
from apps.utils.amounts import evaluate_amount
from apps.web.templatetags.currency_tags import currency

from . import goal_actions, goal_links
from . import ledger as budget_ledger
from .autofill import apply_autofill
from .figures import budget_tab_keys, budgeted_categories, month_figures
from .forms import BudgetAmountForm, GoalForm
from .goal_figures import goal_detail, goals_page
from .grid import GRID_MAX_AMOUNT
from .models import Goal, GoalAccountLink
from .services import (
    GoalAllocationError,
    GoalCloseError,
    GoalDeleteError,
    GoalService,
    NetWorthService,
    picker_accounts_data,
)


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
#
# The pages are server-rendered; their figures come from `goal_figures` and their
# writes from `goal_actions`, the same the goal API (`apps/budget/api/goals.py`)
# uses. With JS the goals page assigns and withdraws through that API; the form
# posts below are what the pages submit (and the no-JS fallbacks).


def _goal_spending_url(goal, book):
    """The Transactions page filtered to the goal's account (its spending)."""
    if not goal.account_id:
        return None
    base = reverse("journal:transactions_home", args=book.url_args)
    return f"{base}?{urlencode({'f_debit_account': f'a:{goal.account_id}'})}"


@login_and_book_required
def goals_list_view(request, team_slug, book_slug):
    """List all goals with progress for the selected month."""
    month = _month_from_request(request)
    show_closed = request.GET.get("show") == "closed"
    page = goals_page(request.book, month, closed=show_closed)
    goal_items = page["cards"]
    for item in goal_items:
        item["spending_url"] = _goal_spending_url(item["goal"], request.book)

    net_worth_card = NetWorthService.card_data(page["unassigned"])
    summary = page["summary"]
    return render(
        request,
        "budget/goals_list.html",
        {
            "active_tab": "goals",
            "page_title": f"Goals | {book_display_name(request.book)}",
            "month": month,
            "goal_items": goal_items,
            "summary": summary,
            "available": net_worth_card["available"],
            "on_track_count": summary["on_track_count"],
            "net_worth_card": net_worth_card,
            "prev_month": month - relativedelta(months=1),
            "next_month": month + relativedelta(months=1),
            "show_closed": show_closed,
            "closed_count": page["closed_count"],
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
            saved = form.save(commit=False)
            saved.book = book
            try:
                changes = goal_actions.save_goal(saved, rows)
            except goal_links.LinkError as e:
                link_error, link_error_goal = str(e), e.goal
            else:
                goal_actions.log_link_changes(request, saved, changes, outflow_before)
                if is_new:
                    messages.success(request, _("Goal created successfully."))
                    return redirect("budget:goals_list", *book.url_args)
                messages.success(request, _("Goal updated successfully."))
                return redirect("budget:goal_detail", *book.url_args, saved.pk)
        options = goal_links.link_options(book, goal, request.POST)
    else:
        form = GoalForm(instance=goal, book=book)
        options = goal_links.link_options(book, goal)

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
    detail = goal_detail(request.book, goal, month)
    return render(
        request,
        "budget/goal_detail.html",
        {
            "active_tab": "goals",
            "page_title": f"{goal.name} | {book_display_name(request.book)}",
            "goal": goal,
            "plan": detail["plan"],
            "progress_pct": detail["progress_pct"],
            "open_links": detail["open_links"],
            "past_links": detail["past_links"],
            "activity": goal_links.goal_activity(goal),
            "can_edit_contributions": detail["can_edit_contributions"],
            "delete_blocked": detail["delete_blocked"],
            "spending": detail["spending"],
            "drift": detail["drift"],
            "spending_url": _goal_spending_url(goal, request.book),
        },
    )


@login_and_book_required
def goal_update_view(request, team_slug, book_slug, pk):
    """Update an existing goal."""
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)
    return _goal_form_view(request, goal)


@login_and_book_required
@require_POST
def goal_unlink(request, team_slug, book_slug, link_pk):
    """Stop an account feeding a goal. What it already brought in stays."""
    link = get_object_or_404(GoalAccountLink.objects.filter(book=request.book).select_related("goal"), pk=link_pk)
    goal = link.goal
    try:
        goal_actions.unlink_account(request, link)
    except goal_links.LinkError as e:
        messages.error(request, str(e))
    else:
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
    line, goal = goal_actions.contribution_line(request.book, line_pk)
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

    goal_actions.log_contribution_edit(request, goal, month, old, amount)
    month_label = date_format(month, "F Y")
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
    """Archive a goal (closing it first if it is open), after a confirmation page."""
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)

    if request.method == "POST":
        try:
            result = goal_actions.archive_goal(request.book, goal, _month_from_request(request))
        except GoalCloseError as e:
            messages.error(request, str(e))
            return redirect("budget:goal_detail", team_slug=team_slug, book_slug=book_slug, pk=pk)
        if result is not None:
            goal_actions.log_goal_closed(request, goal, result, via="archive")
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
    """Set a goal's allocation for a month: the goals page's no-JS form post."""
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)

    if request.method == "POST":
        month = _parse_month(request.POST.get("month"))
        back = reverse("budget:goals_list", args=request.book.url_args) + f"?month={month.isoformat()}"
        amount = evaluate_amount(request.POST.get("amount", "0")) or Decimal("0")
        if amount < 0:
            messages.error(request, _("Allocation amount cannot be negative."))
            return redirect(back)
        GoalService(request.book).update_allocation(goal, month, amount)
        # Back to the goals list at the same month
        return redirect(back)

    return redirect("budget:goals_list", team_slug=team_slug, book_slug=book_slug)


@login_and_book_required
def goal_complete_view(request, team_slug, book_slug, pk):
    """Mark a goal as funded: it stops asking for money but keeps its claim."""
    goal = get_object_or_404(Goal.objects.filter(book=request.book), pk=pk)

    if request.method == "POST":
        goal_actions.mark_funded(goal)
        messages.success(request, _("Congratulations! Goal marked as funded."))

    return redirect("budget:goal_detail", team_slug=team_slug, book_slug=book_slug, pk=pk)


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

    goal_actions.log_goal_closed(request, goal, result, via="close")
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
