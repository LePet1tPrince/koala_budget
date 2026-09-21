"""
The guided onboarding takeover and its JSON endpoints.

The takeover is a full-screen page at its own URL rather than a modal over the
dashboard: the questionnaire is faster to answer without the app behind it, and a
dedicated URL is what makes the flow resumable by simply navigating back to it.

Every endpoint is team-scoped through `@login_and_team_required`, and the state is
read and written server-side -- the client never decides what phase it is on.
"""

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from apps.accounts.models import ACCOUNT_TYPE_EQUITY, AccountGroup
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.budget.models import Goal
from apps.budget.services import NetWorthService
from apps.teams.decorators import login_and_team_required
from apps.teams.services.template_budget import PERSONAL_BUDGET_TEMPLATE
from apps.teams.services.template_engine import apply_template

from .models import OnboardingState
from .questions import (
    CATALOG_VERSION,
    GOAL,
    PHASE_LABELS,
    QUESTION_CATALOG,
    active_phases,
    catalog_payload,
)
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


def get_or_create_state(team) -> OnboardingState:
    """
    The state row is made on demand rather than by a signal on team creation, so
    the signal stays cheap and teams that predate this feature are handled by the
    data migration rather than by a backfill here.
    """
    state, _created = OnboardingState.objects.get_or_create(team=team)
    return state


def _phase_payload() -> list[dict]:
    return [{"key": phase, "label": str(PHASE_LABELS[phase])} for phase in active_phases()]


def _state_payload(state: OnboardingState) -> dict:
    return {
        "phase": state.phase,
        "question_phase": state.question_phase,
        "answers": state.answers,
        "is_finished": state.is_finished,
    }


@ensure_csrf_cookie
@login_and_team_required
def onboarding_home(request, team_slug):
    """The takeover. Finished teams are sent back to the dashboard."""
    state = get_or_create_state(request.team)

    if state.is_finished:
        return redirect("web_team:home", team_slug=team_slug)

    # Only record that they saw it. Advancing the phase here would skip the
    # welcome screen entirely -- the phase moves when the user begins answering.
    if state.started_at is None:
        state.mark_seen()
        state.save(update_fields=["started_at", "updated_at"])
        log_event(AuditEvent.ONBOARDING_STARTED, request=request)

    return render(
        request,
        "onboarding/onboarding.html",
        {
            "page_title": _("Welcome to Koala Budget"),
            "onboarding_props": {
                "teamSlug": team_slug,
                "teamName": request.team.name,
                "firstName": request.user.first_name,
                "questions": catalog_payload(),
                "phases": _phase_payload(),
                "state": _state_payload(state),
                "homeUrl": reverse("web_team:home", args=[team_slug]),
                # The YNAB branch. An export answers every question in the catalog
                # better than the user can, so it skips the questionnaire outright
                # rather than asking them to answer it twice.
                "ynabUrl": (
                    reverse("ynab_import:home", args=[team_slug])
                    if getattr(settings, "YNAB_IMPORT_ENABLED", False)
                    else ""
                ),
                "urls": {
                    "answers": reverse("onboarding:api_answers", args=[team_slug]),
                    "previewCoa": reverse("onboarding:api_preview_coa", args=[team_slug]),
                    "complete": reverse("onboarding:api_complete", args=[team_slug]),
                    "skip": reverse("onboarding:api_skip", args=[team_slug]),
                },
            },
        },
    )


def _json_body(request) -> dict:
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}
    return body if isinstance(body, dict) else {}


def _clean_answers(raw: dict) -> dict:
    """
    Keep only answers the catalog recognises.

    The client is not trusted to send a well-formed payload, and an answer for a
    question that has since been cut would otherwise sit in the database forever
    meaning nothing.
    """
    cleaned = {}
    for question in QUESTION_CATALOG:
        if question.id not in raw:
            continue
        value = raw[question.id]

        if question.options:
            valid = question.option_values
            if isinstance(value, list):
                kept = [v for v in value if isinstance(v, str) and v in valid]
            elif isinstance(value, str) and value in valid:
                kept = [value]
            else:
                kept = []
            if kept:
                cleaned[question.id] = kept
        elif question.kind == GOAL:
            if goal := _clean_goal(value):
                cleaned[question.id] = goal
        elif isinstance(value, str | int | float) and str(value).strip():
            cleaned[question.id] = value

    return cleaned


def _clean_goal(value) -> dict | None:
    """
    A goal answer is a composite, and every field is optional.

    A blank name is how the user skips the question, so it yields nothing rather
    than a half-formed goal.
    """
    if not isinstance(value, dict):
        return None

    name = str(value.get("name") or "").strip()
    if not name:
        return None

    goal = {"name": name[:200]}

    try:
        amount = Decimal(str(value.get("target_amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    goal["target_amount"] = str(amount) if amount and amount > 0 else None

    target_date = str(value.get("target_date") or "").strip()
    goal["target_date"] = target_date or None

    return goal


def _create_first_goal(team, answers: dict):
    """
    Create the goal the user named, so the Goals page is not empty on first visit.

    `Goal.save()` auto-creates the backing equity account, but falls back to *any*
    equity group when there is no "Goals" one -- which on a freshly generated chart
    of accounts is the system "Equity Adjustments" group. Ensuring the group first
    keeps a user's goal out of a system group.
    """
    question = next((q for q in QUESTION_CATALOG if q.kind == GOAL), None)
    if question is None:
        return

    goal = answers.get(question.id)
    if not isinstance(goal, dict) or not goal.get("name"):
        return

    AccountGroup.objects.get_or_create(
        team=team,
        name="Goals",
        defaults={"account_type": ACCOUNT_TYPE_EQUITY, "description": "Savings goals"},
    )

    target_date = None
    if raw_date := goal.get("target_date"):
        target_date = parse_date(raw_date)

    Goal.objects.create(
        team=team,
        name=goal["name"],
        target_amount=Decimal(goal["target_amount"]) if goal.get("target_amount") else Decimal("0"),
        target_date=target_date,
    )


@require_POST
@login_and_team_required
def api_answers(request, team_slug):
    """
    Save answers and advance.

    Answers are merged rather than replaced, so a client that posts one phase at a
    time -- or the user stepping back and changing one -- never drops the rest.
    """
    state = get_or_create_state(request.team)
    if state.is_finished:
        return JsonResponse({"error": "Onboarding is already finished."}, status=409)

    body = _json_body(request)
    state.answers = {**state.answers, **_clean_answers(body.get("answers", {}))}
    state.catalog_version = CATALOG_VERSION

    if state.phase == OnboardingState.PHASE_WELCOME:
        state.start()

    requested = body.get("question_phase")
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
    return JsonResponse(
        {
            "state": _state_payload(state),
            "unanswered_required": unanswered_required(state.answers),
        }
    )


@require_POST
@login_and_team_required
def api_preview_coa(request, team_slug):
    """
    The chart of accounts these answers would produce, without writing anything.

    Built from the same `build_template` the apply step uses, so what the user
    reviews and what they get cannot drift apart.
    """
    state = get_or_create_state(request.team)

    body = _json_body(request)
    answers = {**state.answers, **_clean_answers(body.get("answers", {}))}

    template = build_template(answers)
    try:
        template = apply_edits(template, parse_edits(body.get("edits")))
    except ReviewError as e:
        return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"sections": grouped_for_review(template)})


@require_POST
@login_and_team_required
def api_complete(request, team_slug):
    """
    Build the chart of accounts, apply the user's edits to it, and finish.

    Refuses while a required question is unanswered -- the client hides Continue
    in that case, but the rule lives here, not in the UI.
    """
    state = get_or_create_state(request.team)
    if state.is_finished:
        return JsonResponse({"redirect": reverse("web_team:home", args=[team_slug])})

    body = _json_body(request)
    if answers := _clean_answers(body.get("answers", {})):
        state.answers = {**state.answers, **answers}

    if missing := unanswered_required(state.answers):
        return JsonResponse(
            {"error": "Some questions still need an answer.", "unanswered_required": missing},
            status=400,
        )

    try:
        template = apply_edits(build_template(state.answers), parse_edits(body.get("edits")))
    except ReviewError as e:
        return JsonResponse({"error": str(e)}, status=400)

    with transaction.atomic():
        apply_template(team=request.team, template=template)
        _create_first_goal(request.team, state.answers)
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

    return JsonResponse({"redirect": reverse("web_team:home", args=[team_slug])})


@login_and_team_required
def api_tasks(request, team_slug):
    """
    The guided tasks with their current state.

    Computed fresh on every call rather than cached: what unlocks a task is the
    user's own data changing, which happens on pages the rail is sitting over.
    """
    state = get_or_create_state(request.team)
    return JsonResponse(
        {
            "tasks": task_state(request.team, state.tasks_done, team_slug=team_slug),
            "active": state.shows_tasks,
        }
    )


@require_POST
@login_and_team_required
def api_task(request, team_slug):
    """
    Record a guided task as done, or dismiss the rail entirely.

    Only tasks the server does not detect for itself can be reported this way --
    "see the report" is done by looking at it, which nothing in the data shows.
    Accepting a claim for an auto-detected task would let a checklist say a user
    imported transactions when they did not.
    """
    state = get_or_create_state(request.team)
    body = _json_body(request)

    if body.get("action") == "resume":
        state.phase = OnboardingState.PHASE_TASKS
        state.save()
        return JsonResponse({"active": True, "tasks": task_state(request.team, state.tasks_done, team_slug=team_slug)})

    if body.get("action") == "dismiss":
        state.finish_tasks()
        state.save()
        log_event(
            AuditEvent.ONBOARDING_FINISHED,
            request=request,
            metadata={"reason": "dismissed", "tasks_done": state.tasks_done},
        )
        return JsonResponse({"active": False, "tasks": task_state(request.team, state.tasks_done, team_slug)})

    slug = body.get("slug")
    task = next((t for t in TASKS if t.slug == slug), None)
    if task is None:
        return JsonResponse({"error": "Unknown task."}, status=400)
    if task.auto_detected:
        return JsonResponse({"error": "That task is detected from your data."}, status=400)

    already_done = task.slug in state.tasks_done
    state.mark_task(task.slug)

    tasks = task_state(request.team, state.tasks_done, team_slug=team_slug)
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

    return JsonResponse(
        {
            "tasks": tasks,
            "active": state.shows_tasks,
            "finished": finished,
            # Only computed when the walkthrough actually ends, so the ordinary
            # task POST stays a cheap write.
            "summary": _finish_summary(request.team) if finished else None,
        }
    )


def _finish_summary(team) -> dict:
    """What the user built, for the finish card. Their own numbers, not a slogan."""
    from apps.accounts.models import Account
    from apps.bank_feed.models import BankTransaction

    return {
        "accounts": Account.objects.filter(team=team, is_system=False).count(),
        "transactions": BankTransaction.objects.filter(team=team).count(),
        "net_worth": str(_net_worth(team)),
    }


@login_and_team_required
def api_opening_balances(request, team_slug):
    """
    GET: the accounts worth asking about, with the team's net worth right now.
    POST: record the balances and return the net worth after.

    The before/after pair is the point of the step: the user sees the number they
    have been looking at move to the one they recognise.
    """
    team = request.team

    if not can_set_opening_balances(team):
        # Enforced here, not merely hidden in the UI. Opening balances before there
        # is any categorized activity would anchor a net worth the user has no way
        # to sanity-check against anything they have seen.
        return JsonResponse(
            {"error": str(GATE_REASONS[NEEDS_ENTRIES]), "allowed": False},
            status=400 if request.method == "POST" else 200,
        )

    if request.method != "POST":
        already = existing_opening_balances(team)
        return JsonResponse(
            {
                "allowed": True,
                "net_worth": str(_net_worth(team)),
                "accounts": [
                    {
                        "id": account.id,
                        "name": account.name,
                        "group": account.account_group.name,
                        "type": account.account_group.account_type,
                        "has_opening_balance": account.id in already,
                    }
                    for account in balance_accounts(team)
                ],
            }
        )

    body = _json_body(request)
    before = _net_worth(team)

    try:
        rows = parse_rows(team, body.get("rows", []))
        skip_existing = existing_opening_balances(team)
        rows = [r for r in rows if r.account.id not in skip_existing]
        create_opening_balances(team, rows, as_of=_opening_date(body.get("as_of")))
    except OpeningBalanceError as e:
        return JsonResponse({"error": str(e)}, status=400)

    state = get_or_create_state(team)
    state.mark_task("opening_balances")
    state.save()

    return JsonResponse(
        {
            "net_worth_before": str(before),
            "net_worth": str(_net_worth(team)),
            "created": len(rows),
        }
    )


def _net_worth(team) -> Decimal:
    return NetWorthService(team).get_net_worth(timezone.now().date().replace(day=1))


def _opening_date(raw) -> date:
    """
    Dated the first of the current month by default.

    Anything the user has already imported sits inside the period they imported, so
    an opening balance needs to land before it to read as a starting position
    rather than a transaction.
    """
    if isinstance(raw, str) and (parsed := parse_date(raw.strip())):
        return parsed
    return timezone.now().date().replace(day=1)


@require_POST
@login_and_team_required
def api_skip(request, team_slug):
    """
    Leave the flow without answering.

    The team still needs books to work in, so the stock personal-budget template
    is applied -- skipping onboarding must not leave someone with no accounts.
    """
    state = get_or_create_state(request.team)
    if state.is_finished:
        return JsonResponse({"redirect": reverse("web_team:home", args=[team_slug])})

    phase_when_skipped = state.question_phase or state.phase

    with transaction.atomic():
        apply_template(team=request.team, template=PERSONAL_BUDGET_TEMPLATE)
        state.skip()
        state.save()

    log_event(AuditEvent.ONBOARDING_SKIPPED, request=request, metadata={"phase": phase_when_skipped})

    return _redirect_or_json(request, reverse("web_team:home", args=[team_slug]))


def _redirect_or_json(request, url):
    """
    The no-JS fallback posts this as a plain form, and a form post that lands on
    raw JSON is a dead end. Answer in whatever the caller asked for.
    """
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"redirect": url})
    return HttpResponseRedirect(url)
