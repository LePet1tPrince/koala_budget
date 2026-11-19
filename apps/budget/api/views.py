"""
The budget API: the month's figures, the writes the budget page makes, the
multi-month grid and Unassigned -- `/a/{team}/{book}/budget/api/...`.

Every figure comes from `apps.budget.figures.month_figures` (the builder the
budget page template renders too), every budget write goes through
`apps.budget.ledger` (directly or via `BudgetService` / `GoalService`), and
Unassigned is `apps.budget.unassigned.compute_unassigned`. A write answers with
the month recomputed, so a client repaints without a second request.

Budget entries are never in a closed period (`apps/journal/services/period_lock.py`
exempts them): a past month's budget stays editable after its books are closed.
Members of the book's team may read and write, as on the budget page.
"""

from datetime import date

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE
from apps.api.base import BookAPIView, month_parameter, month_query_param
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.budget import ledger as budget_ledger
from apps.budget.autofill import apply_autofill
from apps.budget.figures import budget_tab_keys, budgeted_categories, month_figures
from apps.budget.grid import default_grid_start, grid_data
from apps.budget.models import Goal
from apps.budget.services import BudgetService, GoalService
from apps.budget.unassigned import compute_unassigned

from .serializers import (
    COVER_FROM_GOAL,
    AutofillRequestSerializer,
    AutofillResponseSerializer,
    BudgetAmountRequestSerializer,
    BudgetAmountResponseSerializer,
    BudgetMonthSerializer,
    CoverRequestSerializer,
    CoverResponseSerializer,
    GridQuerySerializer,
    GridSaveRequestSerializer,
    GridSaveResponseSerializer,
    GridSerializer,
    UnassignedSerializer,
    VisibilityRequestSerializer,
    VisibilityResponseSerializer,
)

UNKNOWN_CATEGORY = _("Unknown budget category.")


def _figures(book, month):
    return BudgetMonthSerializer(month_figures(book, month)).data


def _budget_category(book, category_id, **filters):
    """One of the categories `book` budgets, or a 400 on `category_id`."""
    category = budgeted_categories(book).filter(pk=category_id, **filters).first()
    if category is None:
        raise ValidationError({"category_id": [UNKNOWN_CATEGORY]})
    return category


class BudgetMonthView(BookAPIView):
    """
    Every figure the budget page shows for one month: a section per tab (income,
    when the book budgets it, then expenses), each with its account groups and the
    collapsed hidden group, each group with a row per category (budgeted, actual,
    available, meter); the section totals, sidebar summary, overspent counts and
    Auto-Assign actions; the grand totals, Unassigned and the goals an overspent
    category can be covered from.
    """

    @extend_schema(
        operation_id="budget_month_retrieve",
        tags=["budget"],
        parameters=[month_parameter(required=True)],
        responses=BudgetMonthSerializer,
    )
    def get(self, request, team_slug, book_slug):
        return Response(_figures(self.book, month_query_param(request)))


class BudgetAmountView(BookAPIView):
    """Set one category's budget for a month (replacing what was there; blank clears it)."""

    @extend_schema(
        operation_id="budget_amount_save",
        tags=["budget"],
        request=BudgetAmountRequestSerializer,
        responses=BudgetAmountResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        serializer = BudgetAmountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        category = _budget_category(self.book, data["category_id"])
        budget_ledger.set_budget(self.book, category, data["month"], data["amount"])
        return Response(
            BudgetAmountResponseSerializer(
                {
                    "category_id": category.pk,
                    "month": data["month"],
                    "amount": data["amount"],
                    "figures": month_figures(self.book, data["month"]),
                }
            ).data
        )


class BudgetCoverView(BookAPIView):
    """
    Cover an overspent expense category (docs/goals-envelopes-plan.md §4.4).

    - From Unassigned: the category's budget for the month rises by `amount`. The
      overspending already came out of Unassigned (an overspent envelope claims
      nothing), so filling the hole leaves Unassigned where it is; only an amount
      past the shortfall is a new claim on it.
    - From a goal: the goal gives up `amount` (a negative allocation this month) and
      the budget rises by the same, so the money the goal releases goes back into
      Unassigned. The goal may go negative -- overspending is carried.
    """

    @extend_schema(
        operation_id="budget_cover",
        tags=["budget"],
        request=CoverRequestSerializer,
        responses=CoverResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        serializer = CoverRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        book, month, amount = self.book, data["month"], data["amount"]
        category = _budget_category(book, data["category_id"], account_group__account_type=ACCOUNT_TYPE_EXPENSE)

        goal = None
        if data["source"] == COVER_FROM_GOAL:
            goal = Goal.objects.filter(book=book, pk=data["goal_id"], is_archived=False, closed_at__isnull=True).first()
            if goal is None:
                raise ValidationError({"goal_id": [_("Unknown goal.")]})

        with transaction.atomic():
            if goal is None:
                budget = BudgetService(book).raise_budget(category, month, amount)
            else:
                budget = GoalService(book).cover_from_goal(goal, category, month, amount)
        if goal is not None:
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

        return Response(
            CoverResponseSerializer(
                {
                    "source": data["source"],
                    "category_id": category.pk,
                    "month": month,
                    "amount": budget,
                    "goal_id": goal.pk if goal else None,
                    "goal_left": GoalService(book).left(goal, month) if goal else None,
                    "figures": month_figures(book, month),
                }
            ).data
        )


class BudgetCategoryVisibilityView(BookAPIView):
    """
    Hide a category from the budget page, or bring it back. A display choice only:
    the category moves to its section's hidden group (or back to its account group)
    and no figure changes. Another book's category, or an account that isn't a
    budgeted category, is a 404.
    """

    @extend_schema(
        operation_id="budget_category_visibility",
        tags=["budget"],
        request=VisibilityRequestSerializer,
        responses=VisibilityResponseSerializer,
    )
    def post(self, request, team_slug, book_slug, pk):
        category = get_object_or_404(budgeted_categories(self.book), pk=pk)
        serializer = VisibilityRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hidden = serializer.validated_data["hidden"]
        if category.hidden_from_budget != hidden:
            category.hidden_from_budget = hidden
            category.save(update_fields=["hidden_from_budget", "updated_at"])
        return Response(
            VisibilityResponseSerializer(
                {
                    "category_id": category.pk,
                    "hidden": hidden,
                    "figures": month_figures(self.book, serializer.validated_data["month"]),
                }
            ).data
        )


class BudgetAutofillView(BookAPIView):
    """
    Auto-Assign: set every reached category's budget for the month at once --
    last month's budget, last month's activity, zero, or whatever brings
    Available to zero. Hidden categories are never reached.
    """

    @extend_schema(
        operation_id="budget_autofill",
        tags=["budget"],
        request=AutofillRequestSerializer,
        responses=AutofillResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        serializer = AutofillRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        section = data.get("section")
        if section and section not in budget_tab_keys(self.book):
            raise ValidationError({"section": [_("This book doesn't budget that section.")]})
        changed = apply_autofill(
            self.book, data["month"], data["action"], section=section, category_ids=data.get("category_ids")
        )
        return Response(
            AutofillResponseSerializer(
                {"action": data["action"], "changed": changed, "figures": month_figures(self.book, data["month"])}
            ).data
        )


class BudgetGridView(BookAPIView):
    """
    The multi-month grid editor's data: a row per (visible) budgeted category, its
    budget for each month of the range, and three reference actuals (this year's
    and last year's monthly average, last month), measured from today.
    """

    @extend_schema(
        operation_id="budget_grid_retrieve",
        tags=["budget"],
        parameters=[
            month_parameter("start", description="The first month, as YYYY-MM; defaults to January this year."),
            OpenApiParameter("months", int, OpenApiParameter.QUERY, description="Months to show, 1–24 (default 12)."),
        ],
        responses=GridSerializer,
    )
    def get(self, request, team_slug, book_slug):
        query = GridQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        start = query.validated_data.get("start") or default_grid_start()
        return Response(GridSerializer(grid_data(self.book, start, query.validated_data["months"])).data)


class BudgetGridSaveView(BookAPIView):
    """
    Save a batch of grid edits, all or nothing: one unknown category or bad amount
    rejects the whole batch. The last change to a cell wins.
    """

    @extend_schema(
        operation_id="budget_grid_save",
        tags=["budget"],
        request=GridSaveRequestSerializer,
        responses=GridSaveResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        serializer = GridSaveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = serializer.validated_data["changes"]

        ids = {change["category_id"] for change in changes}
        known = set(budgeted_categories(self.book).filter(pk__in=ids).values_list("pk", flat=True))
        if ids - known:
            raise ValidationError({"changes": [UNKNOWN_CATEGORY]})

        merged = {(change["category_id"], change["month"]): change["amount"] for change in changes}
        if merged:
            budget_ledger.set_budgets(self.book, merged)
            log_event(
                AuditEvent.BULK_EDIT,
                request=request,
                metadata={
                    "scope": "budget_grid",
                    "saved": len(merged),
                    "months": sorted({month.isoformat() for _cid, month in merged}),
                },
            )
        return Response(GridSaveResponseSerializer({"saved": len(merged)}).data)


class UnassignedView(BookAPIView):
    """
    Unassigned for a month (default: this month, the figure the sidebar pill shows):
    net worth less what the expense envelopes and the goals hold, every term of the
    sum, and Expected income beside it.
    """

    @extend_schema(
        operation_id="budget_unassigned_retrieve",
        tags=["budget"],
        parameters=[month_parameter(description="A month, as YYYY-MM; defaults to the current month.")],
        responses=UnassignedSerializer,
    )
    def get(self, request, team_slug, book_slug):
        month = month_query_param(request, default=lambda: date.today().replace(day=1))
        return Response(UnassignedSerializer(compute_unassigned(self.book, month)).data)
