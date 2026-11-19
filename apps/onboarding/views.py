"""
The guided onboarding takeover and its API.

The takeover is a full-screen page at its own URL rather than a modal over the
dashboard: the questionnaire is faster to answer without the app behind it, and a
dedicated URL is what makes the flow resumable by simply navigating back to it.

The page renders an empty shell; the React app loads the catalog and the state
from `api/catalog/` and `api/state/`. Every endpoint is book-scoped
(`BookAccessPermissions`: members of the URL's team), and the state is read and
written server-side -- the client never decides what phase it is on.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.api.base import BookAPIView
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.decorators import login_and_book_required
from apps.budget.services import NetWorthService
from apps.teams.services.template_budget import PERSONAL_BUDGET_TEMPLATE
from apps.teams.services.template_engine import apply_template

from .models import OnboardingState
from .questions import CATALOG_VERSION, PHASE_LABELS, active_phases, book_settings, catalog_payload
from .serializers import (
    CoaPreviewSerializer,
    CoaRequestSerializer,
    OnboardingAnswersRequestSerializer,
    OnboardingAnswersResponseSerializer,
    OnboardingCatalogSerializer,
    OnboardingCompleteResponseSerializer,
    OnboardingPageSerializer,
    OnboardingStateResponseSerializer,
    OnboardingTaskRequestSerializer,
    OnboardingTaskResponseSerializer,
    OnboardingTasksSerializer,
    OpeningBalancesRequestSerializer,
    OpeningBalancesResultSerializer,
    OpeningBalancesSerializer,
)
from .services.answers import clean_answers, create_first_goal
from .services.builder import build_template, unanswered_required
from .services.gates import DONE, GATE_REASONS, NEEDS_ENTRIES, TASKS, can_set_opening_balances, task_state
from .services.opening import (
    OpeningBalanceError,
    balance_accounts,
    create_opening_balances,
    existing_opening_balances,
    parse_rows,
)
from .services.review import ReviewError, apply_edits, grouped_for_review, parse_edits

TAGS = ["onboarding"]


def get_or_create_state(book) -> OnboardingState:
    """
    The state row is made on demand rather than by a signal on book creation, so
    the signal stays cheap and books that predate this feature are handled by the
    data migration rather than by a backfill here.
    """
    state, _created = OnboardingState.objects.get_or_create(book=book)
    return state


def _state_payload(state: OnboardingState) -> dict:
    return {
        "phase": state.phase,
        "question_phase": state.question_phase,
        "answers": state.answers,
        "is_finished": state.is_finished,
        "shows_tasks": state.shows_tasks,
    }


def _refused(message) -> ValidationError:
    return ValidationError({"non_field_errors": [str(message)]})


@ensure_csrf_cookie
@login_and_book_required
def onboarding_home(request, team_slug, book_slug):
    """The takeover. Finished books are sent back to the dashboard."""
    state = get_or_create_state(request.book)

    if state.is_finished:
        return redirect("web_book:home", team_slug=team_slug, book_slug=book_slug)

    # Only record that they saw it. Advancing the phase here would skip the
    # welcome screen entirely -- the phase moves when the user begins answering.
    if state.started_at is None:
        state.mark_seen()
        state.save(update_fields=["started_at", "updated_at"])
        log_event(AuditEvent.ONBOARDING_STARTED, request=request)

    return render(request, "onboarding/onboarding.html", {"page_title": _("Welcome to Koala Budget")})


class CatalogView(BookAPIView):
    """
    The question catalog: prompts, options and answer shapes, with the
    chart-of-accounts rules left behind on the server. The same for every book;
    served under one so a client needs no second base URL.
    """

    @extend_schema(operation_id="onboarding_catalog", tags=TAGS, responses=OnboardingCatalogSerializer)
    def get(self, request, team_slug, book_slug):
        data = {
            "version": CATALOG_VERSION,
            "phases": [{"key": phase, "label": str(PHASE_LABELS[phase])} for phase in active_phases()],
            "questions": catalog_payload(),
        }
        return Response(OnboardingCatalogSerializer(data).data)


class StateView(BookAPIView):
    """Where this book is in the walkthrough, and what the takeover greets the user with."""

    @extend_schema(operation_id="onboarding_state", tags=TAGS, responses=OnboardingPageSerializer)
    def get(self, request, team_slug, book_slug):
        state = get_or_create_state(self.book)
        data = {
            "state": _state_payload(state),
            "unanswered_required": unanswered_required(state.answers),
            "team_name": request.team.name,
            "book_name": self.book.name,
            "first_name": request.user.first_name,
            # The YNAB branch. An export answers every question in the catalog
            # better than the user can, so it skips the questionnaire outright
            # rather than asking them to answer it twice.
            "ynab_import_enabled": bool(getattr(settings, "YNAB_IMPORT_ENABLED", False)),
        }
        return Response(OnboardingPageSerializer(data).data)


class AnswersView(BookAPIView):
    """
    Save answers and advance.

    Answers are merged rather than replaced, so a client that posts one phase at a
    time -- or the user stepping back and changing one -- never drops the rest.
    Answers the catalog does not recognise are dropped. 409 once finished.
    """

    @extend_schema(
        operation_id="onboarding_save_answers",
        tags=TAGS,
        request=OnboardingAnswersRequestSerializer,
        responses=OnboardingAnswersResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        body = OnboardingAnswersRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        state = get_or_create_state(self.book)
        if state.is_finished:
            return Response({"detail": "Onboarding is already finished."}, status=status.HTTP_409_CONFLICT)

        state.answers = {**state.answers, **clean_answers(body.validated_data["answers"])}
        state.catalog_version = CATALOG_VERSION

        if state.phase == OnboardingState.PHASE_WELCOME:
            state.start()

        requested = body.validated_data.get("question_phase")
        if requested in active_phases():
            # The phase the client is moving *to*, so the one it is leaving is the one
            # just completed. This pair of events is what turns the funnel into
            # "which question loses people" rather than a single completion rate.
            if state.question_phase and state.question_phase != requested:
                log_event(
                    AuditEvent.ONBOARDING_PHASE_COMPLETED,
                    request=request,
                    metadata={"phase": state.question_phase, "next": requested},
                )
            state.question_phase = requested

        state.save()
        data = {"state": _state_payload(state), "unanswered_required": unanswered_required(state.answers)}
        return Response(OnboardingAnswersResponseSerializer(data).data)


class PreviewCoaView(BookAPIView):
    """
    The chart of accounts these answers would produce, without writing anything.

    Built from the same `build_template` the apply step uses, so what the user
    reviews and what they get cannot drift apart. An edit that cannot be made (a
    duplicate name, removing a system account) is a 400.
    """

    @extend_schema(
        operation_id="onboarding_preview_coa", tags=TAGS, request=CoaRequestSerializer, responses=CoaPreviewSerializer
    )
    def post(self, request, team_slug, book_slug):
        body = CoaRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        state = get_or_create_state(self.book)
        answers = {**state.answers, **clean_answers(body.validated_data["answers"])}

        try:
            template = apply_edits(build_template(answers), parse_edits(body.validated_data["edits"]))
        except ReviewError as e:
            raise _refused(e) from None

        return Response(CoaPreviewSerializer({"sections": grouped_for_review(template)}).data)


class CompleteView(BookAPIView):
    """
    Build the chart of accounts, apply the user's edits to it, and finish.

    Refuses (400, with `unanswered_required`) while a required question is
    unanswered -- the client hides Continue in that case, but the rule lives here,
    not in the UI. Idempotent: a finished book answers its state again.
    """

    @extend_schema(
        operation_id="onboarding_complete",
        tags=TAGS,
        request=CoaRequestSerializer,
        responses=OnboardingCompleteResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        body = CoaRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        book = self.book
        state = get_or_create_state(book)
        if state.is_finished:
            return Response(OnboardingCompleteResponseSerializer({"state": _state_payload(state)}).data)

        if answers := clean_answers(body.validated_data["answers"]):
            state.answers = {**state.answers, **answers}

        if missing := unanswered_required(state.answers):
            raise ValidationError(
                {"non_field_errors": ["Some questions still need an answer."], "unanswered_required": missing}
            )

        try:
            template = apply_edits(build_template(state.answers), parse_edits(body.validated_data["edits"]))
        except ReviewError as e:
            raise _refused(e) from None

        with transaction.atomic():
            apply_template(book=book, template=template)
            create_first_goal(book, state.answers)
            if settings_chosen := book_settings(state.answers):
                for name, value in settings_chosen.items():
                    setattr(book, name, value)
                book.save(update_fields=[*settings_chosen, "updated_at"])
            state.complete()
            state.save()

        log_event(
            AuditEvent.ONBOARDING_COMPLETED,
            request=request,
            metadata={
                "accounts": len(template["accounts"]),
                # Which answers produced the chart, so a question that turns out to
                # drive nothing can be spotted and cut.
                "answers": state.answers,
            },
        )

        return Response(OnboardingCompleteResponseSerializer({"state": _state_payload(state)}).data)


def skip_onboarding(request) -> OnboardingState:
    """
    Leave the flow without answering.

    The book still needs accounts to work in, so the stock personal-budget template
    is applied -- skipping onboarding must not leave someone with no accounts.
    Skipping a finished book does nothing.
    """
    state = get_or_create_state(request.book)
    if state.is_finished:
        return state

    phase_when_skipped = state.question_phase or state.phase

    with transaction.atomic():
        apply_template(book=request.book, template=PERSONAL_BUDGET_TEMPLATE)
        state.skip()
        state.save()

    log_event(AuditEvent.ONBOARDING_SKIPPED, request=request, metadata={"phase": phase_when_skipped})
    return state


class SkipView(BookAPIView):
    """Skip the questionnaire: the stock chart of accounts is applied instead."""

    @extend_schema(operation_id="onboarding_skip", tags=TAGS, request=None, responses=OnboardingStateResponseSerializer)
    def post(self, request, team_slug, book_slug):
        state = skip_onboarding(request)
        return Response(OnboardingStateResponseSerializer({"state": _state_payload(state)}).data)


@require_POST
@login_and_book_required
def skip_form(request, team_slug, book_slug):
    """The no-JS fallback's plain form post: skip, then go to the dashboard."""
    skip_onboarding(request)
    return HttpResponseRedirect(reverse("web_book:home", args=[team_slug, book_slug]))


def _tasks(book, state: OnboardingState) -> list[dict]:
    return task_state(book, state.tasks_done, url_args=book.url_args)


class TasksView(BookAPIView):
    """
    The guided tasks with their current state.

    Computed fresh on every call rather than cached: what unlocks a task is the
    user's own data changing, which happens on pages the rail is sitting over.
    """

    @extend_schema(operation_id="onboarding_tasks", tags=TAGS, responses=OnboardingTasksSerializer)
    def get(self, request, team_slug, book_slug):
        state = get_or_create_state(self.book)
        return Response(
            OnboardingTasksSerializer({"tasks": _tasks(self.book, state), "active": state.shows_tasks}).data
        )


class TaskView(BookAPIView):
    """
    Record a guided task as done, or put the rail back (`resume`), or dismiss it.

    Only tasks the server does not detect for itself can be reported this way --
    "see the report" is done by looking at it, which nothing in the data shows.
    Accepting a claim for an auto-detected task would let a checklist say a user
    imported transactions when they did not.
    """

    @extend_schema(
        operation_id="onboarding_task",
        tags=TAGS,
        request=OnboardingTaskRequestSerializer,
        responses=OnboardingTaskResponseSerializer,
    )
    def post(self, request, team_slug, book_slug):
        body = OnboardingTaskRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        action = body.validated_data.get("action")

        book = self.book
        state = get_or_create_state(book)

        if action == "resume":
            state.phase = OnboardingState.PHASE_TASKS
            state.save()
            return self._answer(book, state, active=True)

        if action == "dismiss":
            state.finish_tasks()
            state.save()
            log_event(
                AuditEvent.ONBOARDING_FINISHED,
                request=request,
                metadata={"reason": "dismissed", "tasks_done": state.tasks_done},
            )
            return self._answer(book, state, active=False)

        slug = body.validated_data["slug"]
        task = next((t for t in TASKS if t.slug == slug), None)
        if task is None:
            raise ValidationError({"slug": ["Unknown task."]})
        if task.auto_detected:
            raise ValidationError({"slug": ["That task is detected from your data."]})

        already_done = task.slug in state.tasks_done
        state.mark_task(task.slug)

        tasks = _tasks(book, state)
        finished = all(t["state"] == DONE for t in tasks)
        if finished:
            state.finish_tasks()
        state.save()

        if not already_done:
            log_event(AuditEvent.ONBOARDING_TASK_COMPLETED, request=request, metadata={"task": task.slug})
        if finished:
            log_event(
                AuditEvent.ONBOARDING_FINISHED,
                request=request,
                metadata={"reason": "all_tasks_done", "tasks_done": state.tasks_done},
            )

        return self._answer(
            book,
            state,
            active=state.shows_tasks,
            tasks=tasks,
            finished=finished,
            # Only computed when the walkthrough actually ends, so the ordinary
            # task POST stays a cheap write.
            summary=_finish_summary(book) if finished else None,
        )

    @staticmethod
    def _answer(book, state, *, active, tasks=None, finished=False, summary=None):
        data = {
            "tasks": tasks if tasks is not None else _tasks(book, state),
            "active": active,
            "finished": finished,
            "summary": summary,
        }
        return Response(OnboardingTaskResponseSerializer(data).data)


def _finish_summary(book) -> dict:
    """What the user built, for the finish card. Their own numbers, not a slogan."""
    from apps.accounts.models import Account
    from apps.bank_feed.models import BankTransaction

    return {
        "accounts": Account.objects.filter(book=book, is_system=False).count(),
        "transactions": BankTransaction.objects.filter(book=book).count(),
        "net_worth": _net_worth(book),
    }


class OpeningBalancesView(BookAPIView):
    """
    GET: the accounts worth asking about, with the book's net worth right now.
    POST: record the balances and return the net worth before and after.

    The before/after pair is the point of the step: the user sees the number they
    have been looking at move to the one they recognise.

    Both wait for categorized activity -- enforced here, not merely hidden in the
    UI. Opening balances before there is any would anchor a net worth the user
    has no way to sanity-check against anything they have seen. The GET answers
    `allowed: false` with the reason; the POST is a 400.
    """

    @extend_schema(operation_id="onboarding_opening_balances", tags=TAGS, responses=OpeningBalancesSerializer)
    def get(self, request, team_slug, book_slug):
        book = self.book
        if not can_set_opening_balances(book):
            data = {"allowed": False, "reason": str(GATE_REASONS[NEEDS_ENTRIES]), "net_worth": None, "accounts": []}
            return Response(OpeningBalancesSerializer(data).data)

        already = existing_opening_balances(book)
        data = {
            "allowed": True,
            "reason": "",
            "net_worth": _net_worth(book),
            "accounts": [
                {
                    "id": account.id,
                    "name": account.name,
                    "group": account.account_group.name,
                    "type": account.account_group.account_type,
                    "has_opening_balance": account.id in already,
                }
                for account in balance_accounts(book)
            ],
        }
        return Response(OpeningBalancesSerializer(data).data)

    @extend_schema(
        operation_id="onboarding_set_opening_balances",
        tags=TAGS,
        request=OpeningBalancesRequestSerializer,
        responses=OpeningBalancesResultSerializer,
    )
    def post(self, request, team_slug, book_slug):
        book = self.book
        if not can_set_opening_balances(book):
            raise _refused(GATE_REASONS[NEEDS_ENTRIES])

        body = OpeningBalancesRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        before = _net_worth(book)

        try:
            rows = parse_rows(book, body.validated_data["rows"])
            skip_existing = existing_opening_balances(book)
            rows = [r for r in rows if r.account.id not in skip_existing]
            create_opening_balances(book, rows, as_of=body.validated_data.get("as_of") or _first_of_this_month())
        except OpeningBalanceError as e:
            raise _refused(e) from None

        state = get_or_create_state(book)
        state.mark_task("opening_balances")
        state.save()

        data = {"net_worth_before": before, "net_worth": _net_worth(book), "created": len(rows)}
        return Response(OpeningBalancesResultSerializer(data).data)


def _net_worth(book) -> Decimal:
    return NetWorthService(book).get_net_worth(_first_of_this_month())


def _first_of_this_month() -> date:
    """
    Opening balances are dated the first of the current month by default.

    Anything the user has already imported sits inside the period they imported, so
    an opening balance needs to land before it to read as a starting position
    rather than a transaction.
    """
    return timezone.now().date().replace(day=1)
