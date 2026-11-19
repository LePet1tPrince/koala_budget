"""
The guided monthly review: a page view (the empty state, or the React app's
mount) and its API -- the whole review for one month, plus small POSTs
recording walkthrough progress.

Not a takeover -- unlike onboarding, a returning user must be able to leave
mid-review, so this page extends the ordinary app shell and keeps the sidebar
(docs/monthly-review-plan.md §5.4).

The whole review is one read (`api/review/`, §2): the walkthrough and the
dashboard both render from it, and changing the baseline never asks again.
"""

from datetime import date

from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from apps.api.base import BookAPIView, month_parameter, month_query_param
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.decorators import login_and_book_required
from apps.journal.models import JournalEntry, counted_entries, transaction_entries
from apps.utils.months import add_months

from .exports import export_monthly_review_csv
from .models import MonthlyReviewState
from .serializers import (
    MonthlyReviewSerializer,
    ReviewCompleteResponseSerializer,
    ReviewFinishResponseSerializer,
    ReviewMonthRequestSerializer,
    ReviewStepRequestSerializer,
    ReviewStepResponseSerializer,
)
from .services.review import build_review

TAGS = ["monthly_review"]


def _parse_month(value):
    if value:
        parsed = parse_date(str(value)) or parse_date(f"{value}-01")
        if parsed:
            return parsed.replace(day=1)
    return None


def _default_month():
    """The last complete month -- a half-finished month has nothing to review."""
    return add_months(date.today(), -1)


def _month_from_request(request):
    """An explicit ?month= wins (and is remembered for the session); otherwise
    the last month viewed; otherwise the last complete month."""
    value = request.GET.get("month")
    if value:
        month = _parse_month(value) or _default_month()
        request.session["monthly_review_month"] = month.isoformat()
        return month
    stored = request.session.get("monthly_review_month")
    if stored and (month := _parse_month(stored)):
        return month
    return _default_month()


def _get_or_create_state(book, month) -> MonthlyReviewState:
    state, _created = MonthlyReviewState.objects.get_or_create(book=book, month=month)
    return state


def _book_has_activity_by(book, month) -> bool:
    """Whether the book had any (non-void) ledger activity on or before `month`."""
    first_entry_date = (
        JournalEntry.objects.filter(book=book)
        .filter(counted_entries(), transaction_entries())
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    return first_entry_date is not None and month >= first_entry_date.replace(day=1)


@ensure_csrf_cookie
@login_and_book_required
def monthly_review_home(request, team_slug, book_slug):
    """
    The review's page: the empty state, or the mount the React app fills from
    `api/review/` (it shows a skeleton until the review lands). Opening the page
    is what starts a month's review.
    """
    month = _month_from_request(request)
    state = _get_or_create_state(request.book, month)

    if state.started_at is None:
        state.start()
        state.save(update_fields=["started_at", "updated_at"])
        log_event(AuditEvent.MONTHLY_REVIEW_STARTED, request=request, metadata={"month": month.isoformat()})

    context = {
        "active_tab": "monthly-review",
        "page_title": _("Monthly Review"),
        "month": month,
        "prev_month": add_months(month, -1),
        "next_month": add_months(month, 1),
        "empty_state": not _book_has_activity_by(request.book, month),
    }
    return render(request, "monthly_review/monthly_review_home.html", context)


def _state_payload(state: MonthlyReviewState) -> dict:
    return {
        "step": state.step,
        "steps_seen": state.steps_seen,
        "baseline": state.baseline,
        "is_finished": state.is_finished,
        "completed_at": state.completed_at,
        "dismissed_at": state.dismissed_at,
    }


def _month_body(request, serializer_class=ReviewMonthRequestSerializer):
    body = serializer_class(data=request.data)
    body.is_valid(raise_exception=True)
    return body.validated_data


class ReviewView(BookAPIView):
    """
    The whole review of one month, every comparison baseline precomputed (a client
    reslices it per baseline without asking again), with where the user got to.
    The month defaults to the last complete one. A month before the book's first
    activity has nothing to review: `has_activity` is false and `review` null.

    A read: it does not start the review (opening the page does, or the first
    `api/step/`).
    """

    @extend_schema(
        operation_id="monthly_review_retrieve",
        tags=TAGS,
        parameters=[month_parameter(description="The reviewed month, as YYYY-MM (default: last month).")],
        responses=MonthlyReviewSerializer,
    )
    def get(self, request, team_slug, book_slug):
        month = month_query_param(request, default=_default_month)
        state = MonthlyReviewState.objects.filter(book=self.book, month=month).first() or MonthlyReviewState(
            book=self.book, month=month
        )
        has_activity = _book_has_activity_by(self.book, month)
        data = {
            "month": month,
            "has_activity": has_activity,
            "review": build_review(self.book, month) if has_activity else None,
            "state": _state_payload(state),
        }
        return Response(MonthlyReviewSerializer(data).data)


class StepView(BookAPIView):
    """Record the step the user is on and the baseline they chose (each optional); starts the review."""

    @extend_schema(
        operation_id="monthly_review_step",
        tags=TAGS,
        request=ReviewStepRequestSerializer,
        responses=ReviewStepResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        body = _month_body(request, ReviewStepRequestSerializer)
        month = body["month"]
        state = _get_or_create_state(self.book, month)

        if state.started_at is None:
            state.start()
            log_event(AuditEvent.MONTHLY_REVIEW_STARTED, request=request, metadata={"month": month.isoformat()})

        baseline = body.get("baseline")
        if baseline and baseline != state.baseline:
            log_event(
                AuditEvent.MONTHLY_REVIEW_BASELINE_CHANGED,
                request=request,
                metadata={"month": month.isoformat(), "from": state.baseline, "to": baseline},
            )
            state.baseline = baseline

        step = body.get("step")
        if step is not None and step != state.step:
            log_event(
                AuditEvent.MONTHLY_REVIEW_STEP_COMPLETED,
                request=request,
                metadata={"month": month.isoformat(), "step": state.step, "next": step},
            )
            state.advance(step)

        state.save()
        return Response(ReviewStepResponseSerializer({"state": _state_payload(state)}).data)


class CompleteView(BookAPIView):
    """Mark the month reviewed (once): the client opens the month's dashboard. Returns its headline figures."""

    @extend_schema(
        operation_id="monthly_review_complete",
        tags=TAGS,
        request=ReviewMonthRequestSerializer,
        responses=ReviewCompleteResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        month = _month_body(request)["month"]
        state = _get_or_create_state(self.book, month)
        if state.is_finished:
            data = {"already_finished": True, "state": _state_payload(state), "current": None}
            return Response(ReviewCompleteResponseSerializer(data).data)

        state.complete()
        state.save()
        review = build_review(self.book, month)
        log_event(
            AuditEvent.MONTHLY_REVIEW_COMPLETED,
            request=request,
            metadata={
                "month": month.isoformat(),
                "steps_seen": state.steps_seen,
                "flags": [flag["kind"] for flag in review["health"]["flags"]],
            },
        )
        data = {"already_finished": False, "state": _state_payload(state), "current": review["current"]}
        return Response(ReviewCompleteResponseSerializer(data).data)


class DismissView(BookAPIView):
    """Skip the month's review (once): the dashboard stops nudging for it."""

    @extend_schema(
        operation_id="monthly_review_dismiss",
        tags=TAGS,
        request=ReviewMonthRequestSerializer,
        responses=ReviewFinishResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        month = _month_body(request)["month"]
        state = _get_or_create_state(self.book, month)
        if state.is_finished:
            return Response(
                ReviewFinishResponseSerializer({"already_finished": True, "state": _state_payload(state)}).data
            )

        state.dismiss()
        state.save()
        log_event(
            AuditEvent.MONTHLY_REVIEW_DISMISSED,
            request=request,
            metadata={"month": month.isoformat(), "step": state.step},
        )
        return Response(
            ReviewFinishResponseSerializer({"already_finished": False, "state": _state_payload(state)}).data
        )


@login_and_book_required
def export_monthly_review(request, team_slug, book_slug):
    month = _parse_month(request.GET.get("month")) or _default_month()
    return export_monthly_review_csv(request.book, month)
