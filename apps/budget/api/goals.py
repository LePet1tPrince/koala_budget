"""
The goal API: the goals page's and the goal page's figures, the goal form, and
every action the pages take on a goal -- `/a/{team}/{book}/budget/api/goals/...`.

Figures come from `apps.budget.goal_figures` (what the templates render too);
allocations and contributions are written only through `GoalService` /
`apps.budget.ledger`, links only through `goal_links.set_links` (via
`goal_actions.save_goal`), so the pages and the API can't disagree. A refusal
(nothing left to withdraw, a goal that can't close, a link another goal holds)
is a 400 with the reason the pages show.

Members of the book's team read and write goals, as on the goals page (the same
rule as the budget API). Another book's goal, link or contribution is a 404.
"""

from datetime import date

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.api.base import BookAPIView, month_parameter, month_query_param
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.permissions import BookAccessPermissions
from apps.budget import goal_actions, goal_links
from apps.budget.goal_figures import goal_card_for, goal_detail, goal_with_progress, goals_page
from apps.budget.models import Goal, GoalAccountLink
from apps.budget.services import GoalAllocationError, GoalCloseError, GoalDeleteError, GoalService
from apps.budget.unassigned import compute_unassigned

from .goal_serializers import (
    GoalActivitySerializer,
    GoalAllocateRequestSerializer,
    GoalAllocateResponseSerializer,
    GoalCardSerializer,
    GoalCloseRequestSerializer,
    GoalCloseResponseSerializer,
    GoalContributionRequestSerializer,
    GoalContributionResponseSerializer,
    GoalDetailSerializer,
    GoalFundsRequestSerializer,
    GoalFundsResponseSerializer,
    GoalLinkPreviewRequestSerializer,
    GoalLinkPreviewSerializer,
    GoalListSerializer,
    GoalMonthRequestSerializer,
    GoalUnlinkResponseSerializer,
    GoalWriteSerializer,
    link_rows,
)

TAGS = ["budget"]


def this_month():
    return date.today().replace(day=1)


def month_param(description="A month, as YYYY-MM; defaults to the current month."):
    return month_parameter(description=description)


def refused(error):
    """A service's refusal as a 400 with its message."""
    raise ValidationError({"non_field_errors": [str(error)]})


class GoalViewSet(viewsets.GenericViewSet):
    """The book's goals (open, closed and archived) and what can be done to one."""

    permission_classes = [BookAccessPermissions]
    serializer_class = GoalDetailSerializer

    def get_queryset(self):
        return Goal.objects.filter(book=self.request.book)

    @property
    def book(self):
        return self.request.book

    def _detail(self, goal, month, status_code=status.HTTP_200_OK):
        goal = goal_with_progress(self.book, goal.pk, month)
        return Response(GoalDetailSerializer(goal_detail(self.book, goal, month)).data, status=status_code)

    def _card(self, goal, month):
        return goal_card_for(self.book, goal, month)

    @extend_schema(
        operation_id="budget_goals_list",
        tags=TAGS,
        parameters=[
            month_param(),
            OpenApiParameter(
                "closed", bool, OpenApiParameter.QUERY, description="The closed and archived goals instead."
            ),
        ],
        responses=GoalListSerializer,
    )
    def overview(self, request, team_slug, book_slug):
        """The goals page for a month: each goal's card, their totals and Unassigned."""
        month = month_query_param(request, default=this_month)
        closed = request.query_params.get("closed") in ("1", "true", "True")
        return Response(GoalListSerializer(goals_page(self.book, month, closed=closed)).data)

    @extend_schema(
        operation_id="budget_goals_create",
        tags=TAGS,
        request=GoalWriteSerializer,
        responses={201: GoalDetailSerializer},
    )
    def create(self, request, team_slug, book_slug):
        """Create a goal, with the accounts its money lives in (validated as the goal form is)."""
        serializer = GoalWriteSerializer(data=request.data, context={"book": self.book})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        goal = Goal(book=self.book, **{field: data[field] for field in GoalWriteSerializer.FIELDS})
        changes = self._save(goal, data["rows"])
        goal_actions.log_link_changes(request, goal, changes)
        return self._detail(goal, this_month(), status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="budget_goals_retrieve",
        tags=TAGS,
        parameters=[month_param()],
        responses=GoalDetailSerializer,
    )
    def retrieve(self, request, team_slug, book_slug, pk):
        """The goal page for a month: the card, linked accounts, spending and drift."""
        goal = self.get_object()
        return self._detail(goal, month_query_param(request, default=this_month))

    @extend_schema(
        operation_id="budget_goals_update",
        tags=TAGS,
        request=GoalWriteSerializer,
        responses=GoalDetailSerializer,
    )
    def update(self, request, team_slug, book_slug, pk):
        """Change a goal's settings and (with `links`) its linked accounts."""
        return self._update(request, partial=False)

    @extend_schema(
        operation_id="budget_goals_partial_update",
        tags=TAGS,
        request=GoalWriteSerializer(partial=True),
        responses=GoalDetailSerializer,
    )
    def partial_update(self, request, team_slug, book_slug, pk):
        """Change some of a goal's settings; the rest stay."""
        return self._update(request, partial=True)

    def _update(self, request, partial):
        goal = self.get_object()
        serializer = GoalWriteSerializer(goal, data=request.data, partial=partial, context={"book": self.book})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        outflow_before = goal.outflow
        for field in GoalWriteSerializer.FIELDS:
            setattr(goal, field, data[field])
        changes = self._save(goal, data["rows"])
        goal_actions.log_link_changes(request, goal, changes, outflow_before)
        return self._detail(goal, this_month())

    def _save(self, goal, rows):
        try:
            return goal_actions.save_goal(goal, rows)
        except goal_links.LinkError as e:
            raise ValidationError({"links": [str(e)]}) from None

    @extend_schema(operation_id="budget_goals_destroy", tags=TAGS, responses={204: None})
    def destroy(self, request, team_slug, book_slug, pk):
        """
        Delete a goal for good -- open, closed or archived -- with its contributions and
        account links, freeing its name and its accounts' history. Whatever it had left
        goes back to Unassigned. Refused (400) while transactions are categorized to it.
        """
        goal = self.get_object()
        try:
            summary = GoalService(self.book).delete(goal)
        except GoalDeleteError as e:
            refused(e)
        log_event(AuditEvent.GOAL_DELETED, request=request, metadata={"goal_id": int(pk), **summary})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(operation_id="budget_goals_activity", tags=TAGS, responses=GoalActivitySerializer)
    def activity(self, request, team_slug, book_slug, pk):
        """Everything that moved the goal, newest first: contributions, linked money, spending."""
        goal = self.get_object()
        events = [
            {
                **event,
                "account_id": event["account"].pk if event["account"] else None,
                "account_name": event["account"].name if event["account"] else None,
                "line_id": event.get("line_id"),
            }
            for event in goal_links.goal_activity(goal)
        ]
        return Response(
            GoalActivitySerializer(
                {
                    "goal_id": goal.pk,
                    "can_edit_contributions": not goal.is_closed and not goal.is_archived,
                    "events": events,
                }
            ).data
        )

    @extend_schema(
        operation_id="budget_goals_allocate",
        tags=TAGS,
        request=GoalAllocateRequestSerializer,
        responses=GoalAllocateResponseSerializer,
    )
    def allocate(self, request, team_slug, book_slug, pk):
        """Set the goal's allocation for a month (replacing it), as the no-JS "Set month" form does."""
        goal = self.get_object()
        serializer = GoalAllocateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month, amount = serializer.validated_data["month"], serializer.validated_data["amount"]
        GoalService(self.book).update_allocation(goal, month, amount)
        return Response(
            GoalAllocateResponseSerializer(
                {
                    "month": month,
                    "amount": amount,
                    "goal": self._card(goal, month),
                    "unassigned": compute_unassigned(self.book, month),
                }
            ).data
        )

    def _funds(self, request, withdrawn):
        goal = self.get_object()
        serializer = GoalFundsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month, amount = serializer.validated_data["month"], serializer.validated_data.get("amount")
        action = goal_actions.withdraw_funds if withdrawn else goal_actions.assign_funds
        try:
            result = action(self.book, goal, month, amount)
        except goal_actions.GoalFundsError as e:
            refused(e)
        goal_actions.log_funds(request, goal, month, result, withdrawn=withdrawn)
        card = self._card(goal, month)
        before = result["before"]["allocated"]
        completed = not withdrawn and goal.has_target and before < goal.target_amount <= before + result["amount"]
        return Response(
            GoalFundsResponseSerializer(
                {
                    "amount": result["amount"],
                    "month": month,
                    "before": result["before"],
                    "goal": card,
                    "completed": completed,
                    "unassigned": compute_unassigned(self.book, month),
                }
            ).data
        )

    @extend_schema(
        operation_id="budget_goals_assign",
        tags=TAGS,
        request=GoalFundsRequestSerializer,
        responses=GoalFundsResponseSerializer,
    )
    def assign(self, request, team_slug, book_slug, pk):
        """
        Add money to the goal for a month (added to the month's allocation). Without an
        amount, everything Unassigned has, capped at what the goal still asks for.
        """
        return self._funds(request, withdrawn=False)

    @extend_schema(
        operation_id="budget_goals_withdraw",
        tags=TAGS,
        request=GoalFundsRequestSerializer,
        responses=GoalFundsResponseSerializer,
    )
    def withdraw(self, request, team_slug, book_slug, pk):
        """
        Take money back out of the goal, recorded against the month (whose allocation may
        go negative; past months stay as they were). Without an amount, everything left.
        Money already spent can't be withdrawn.
        """
        return self._funds(request, withdrawn=True)

    @extend_schema(
        operation_id="budget_goals_complete",
        tags=TAGS,
        request=GoalMonthRequestSerializer,
        responses=GoalCardSerializer,
    )
    def complete(self, request, team_slug, book_slug, pk):
        """Mark the goal funded: it stops asking for money but keeps what it holds."""
        goal = self.get_object()
        serializer = GoalMonthRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        goal_actions.mark_funded(goal)
        month = serializer.validated_data.get("month") or this_month()
        return Response(GoalCardSerializer(self._card(goal, month)).data)

    def _close_response(self, goal, month, result):
        result = result or {"released": 0, "covered": 0}
        return Response(
            GoalCloseResponseSerializer(
                {
                    **result,
                    "goal": self._card(goal, month),
                    "unassigned": compute_unassigned(self.book, month),
                }
            ).data
        )

    @extend_schema(
        operation_id="budget_goals_close",
        tags=TAGS,
        request=GoalCloseRequestSerializer,
        responses=GoalCloseResponseSerializer,
    )
    def close(self, request, team_slug, book_slug, pk):
        """
        Close the goal: anything left goes back to Unassigned this month. A negative goal
        is refused unless `cover` (which tops it back up to zero first -- free, since the
        overspending already came out of Unassigned). An archived goal is a 404.
        """
        goal = get_object_or_404(self.get_queryset().filter(is_archived=False), pk=pk)
        serializer = GoalCloseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data.get("month") or this_month()
        try:
            result = GoalService(self.book).close(goal, month, cover=serializer.validated_data["cover"])
        except GoalCloseError as e:
            refused(e)
        goal_actions.log_goal_closed(request, goal, result, via="close")
        return self._close_response(goal, month, result)

    @extend_schema(
        operation_id="budget_goals_archive",
        tags=TAGS,
        request=GoalMonthRequestSerializer,
        responses=GoalCloseResponseSerializer,
    )
    def archive(self, request, team_slug, book_slug, pk):
        """
        Archive the goal: it leaves every list. An open goal is closed first, releasing
        what it has left (refused, as closing is, while it is negative).
        """
        goal = self.get_object()
        serializer = GoalMonthRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data.get("month") or this_month()
        try:
            result = goal_actions.archive_goal(self.book, goal, month)
        except GoalCloseError as e:
            refused(e)
        if result is not None:
            goal_actions.log_goal_closed(request, goal, result, via="archive")
        return self._close_response(goal, month, result)


class GoalLinkPreviewView(BookAPIView):
    """
    What saving the goal form's linked accounts and outflow setting would do -- to the
    goal and to Unassigned -- without writing anything. Refused (400) exactly as saving
    would be.
    """

    @extend_schema(
        operation_id="budget_goals_link_preview",
        tags=TAGS,
        request=GoalLinkPreviewRequestSerializer,
        responses=GoalLinkPreviewSerializer,
    )
    def post(self, request, team_slug, book_slug):
        serializer = GoalLinkPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        goal = None
        if data.get("goal_id"):
            goal = get_object_or_404(Goal.objects.filter(book=self.book), pk=data["goal_id"])
        rows = link_rows(self.book, data.get("links") or [])
        try:
            result = goal_links.preview(self.book, goal, rows, data["outflow"], month=data.get("month"))
        except goal_links.LinkError as e:
            raise ValidationError({"links": [str(e)]}) from None
        return Response(GoalLinkPreviewSerializer(result).data)


class GoalUnlinkView(BookAPIView):
    """Stop an account feeding its goal. What it already brought in stays."""

    @extend_schema(
        operation_id="budget_goal_links_unlink",
        tags=TAGS,
        request=None,
        responses=GoalUnlinkResponseSerializer,
    )
    def post(self, request, team_slug, book_slug, link_pk):
        link = get_object_or_404(
            GoalAccountLink.objects.filter(book=self.book).select_related("goal", "account"), pk=link_pk
        )
        goal = link.goal
        try:
            goal_actions.unlink_account(request, link)
        except goal_links.LinkError as e:
            refused(e)
        return Response(
            GoalUnlinkResponseSerializer(
                {
                    "goal_id": goal.pk,
                    "account_id": link.account_id,
                    "account_name": link.account.name,
                    "end_date": link.end_date if link.pk else None,
                    "removed": link.pk is None,
                }
            ).data
        )


class GoalContributionView(BookAPIView):
    """
    Change or undo a past month's manual contribution, named by its line on the month's
    budget entry (`line_id` in the goal's activity). Money from linked accounts follows
    its transactions and has no such line. Refused on a closed or archived goal, and
    when lowering it would take back money already spent.
    """

    @extend_schema(
        operation_id="budget_goal_contributions_update",
        tags=TAGS,
        request=GoalContributionRequestSerializer,
        responses=GoalContributionResponseSerializer,
    )
    def post(self, request, team_slug, book_slug, line_pk):
        line, goal = goal_actions.contribution_line(self.book, line_pk)
        serializer = GoalContributionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data["amount"]
        month = line.journal_entry.entry_date.replace(day=1)
        try:
            old = GoalService(self.book).edit_allocation(goal, month, amount)
        except GoalAllocationError as e:
            refused(e)
        if old != amount:
            goal_actions.log_contribution_edit(request, goal, month, old, amount)
        return Response(
            GoalContributionResponseSerializer(
                {
                    "goal_id": goal.pk,
                    "month": month,
                    "old": old,
                    "amount": amount,
                    "goal": goal_card_for(self.book, goal, month),
                }
            ).data
        )
