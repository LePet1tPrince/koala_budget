"""
The guided monthly review: a page view rendering the whole payload for one
month, plus tiny JSON POSTs recording walkthrough progress.

Not a takeover -- unlike onboarding, a returning user must be able to leave
mid-review, so this page extends the ordinary app shell and keeps the sidebar
(docs/monthly-review-plan.md §5.4).

The whole review ships in one `json_script` payload (§2): there is no data
endpoint for the walkthrough or the dashboard, only these small state writes.
"""

import json
from dataclasses import asdict as dataclass_asdict
from dataclasses import is_dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Model
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.journal.models import JournalEntry
from apps.teams.decorators import login_and_team_required

from .exports import export_monthly_review_csv
from .models import MonthlyReviewState
from .services.budget import _next_month, _prev_month
from .services.review import build_review


def _parse_month(value):
    if value:
        parsed = parse_date(str(value)) or parse_date(f"{value}-01")
        if parsed:
            return parsed.replace(day=1)
    return None


def _default_month():
    """The last complete month -- a half-finished month has nothing to review."""
    return _prev_month(date.today().replace(day=1))


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


def _json_body(request) -> dict:
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}
    return body if isinstance(body, dict) else {}


def _json_safe(value):
    """Recursively convert a `build_review` payload into JSON-safe types for
    `json_script`: Decimal -> float, dates -> ISO strings, model instances ->
    {id, name}, Insight dataclasses -> dict."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(dataclass_asdict(value))
    if isinstance(value, Model):
        return {"id": value.pk, "name": str(value)}
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _get_or_create_state(team, month) -> MonthlyReviewState:
    state, _created = MonthlyReviewState.objects.get_or_create(team=team, month=month)
    return state


def _team_has_activity_by(team, month) -> bool:
    """Whether the team had any (non-void) ledger activity on or before `month`."""
    first_entry_date = (
        JournalEntry.objects.filter(team=team)
        .exclude(status=JournalEntry.STATUS_VOID)
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    return first_entry_date is not None and month >= first_entry_date.replace(day=1)


@ensure_csrf_cookie
@login_and_team_required
def monthly_review_home(request, team_slug):
    month = _month_from_request(request)
    state = _get_or_create_state(request.team, month)

    if state.started_at is None:
        state.start()
        state.save(update_fields=["started_at", "updated_at"])
        log_event(AuditEvent.MONTHLY_REVIEW_STARTED, request=request, metadata={"month": month.isoformat()})

    context = {
        "active_tab": "monthly-review",
        "page_title": _("Monthly Review"),
        "month": month,
        "prev_month": _prev_month(month),
        "next_month": _next_month(month),
        "empty_state": not _team_has_activity_by(request.team, month),
    }

    if not context["empty_state"]:
        review = build_review(request.team, month)
        context["monthly_review_props"] = {
            "teamSlug": team_slug,
            "month": month.isoformat(),
            "review": _json_safe(review),
            "state": {
                "step": state.step,
                "stepsSeen": state.steps_seen,
                "baseline": state.baseline,
                "isFinished": state.is_finished,
            },
            "urls": {
                "step": reverse("monthly_review:api_step", args=[team_slug]),
                "complete": reverse("monthly_review:api_complete", args=[team_slug]),
                "dismiss": reverse("monthly_review:api_dismiss", args=[team_slug]),
                "export": reverse("monthly_review:export", args=[team_slug]) + f"?month={month.isoformat()}",
                "reportsHome": reverse("reports:reports_home", args=[team_slug]),
            },
        }

    return render(request, "monthly_review/monthly_review_home.html", context)


@require_POST
@login_and_team_required
def api_step(request, team_slug):
    body = _json_body(request)
    month = _parse_month(body.get("month")) or _default_month()
    state = _get_or_create_state(request.team, month)

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
    if isinstance(step, int) and step != state.step:
        log_event(
            AuditEvent.MONTHLY_REVIEW_STEP_COMPLETED,
            request=request,
            metadata={"month": month.isoformat(), "step": state.step, "next": step},
        )
        state.advance(step)

    state.save()
    return JsonResponse({"step": state.step, "steps_seen": state.steps_seen, "baseline": state.baseline})


@require_POST
@login_and_team_required
def api_complete(request, team_slug):
    body = _json_body(request)
    month = _parse_month(body.get("month")) or _default_month()
    state = _get_or_create_state(request.team, month)

    if state.is_finished:
        return JsonResponse({"already_finished": True})

    state.complete()
    state.save()

    review = build_review(request.team, month)
    log_event(
        AuditEvent.MONTHLY_REVIEW_COMPLETED,
        request=request,
        metadata={
            "month": month.isoformat(),
            "steps_seen": state.steps_seen,
            "flags": [flag["kind"] for flag in review["health"]["flags"]],
        },
    )
    return JsonResponse({"current": _json_safe(review["current"])})


@require_POST
@login_and_team_required
def api_dismiss(request, team_slug):
    body = _json_body(request)
    month = _parse_month(body.get("month")) or _default_month()
    state = _get_or_create_state(request.team, month)

    if state.is_finished:
        return JsonResponse({"already_finished": True})

    state.dismiss()
    state.save()
    log_event(
        AuditEvent.MONTHLY_REVIEW_DISMISSED, request=request, metadata={"month": month.isoformat(), "step": state.step}
    )
    return JsonResponse({"dismissed": True})


@login_and_team_required
def export_monthly_review(request, team_slug):
    month = _parse_month(request.GET.get("month")) or _default_month()
    return export_monthly_review_csv(request.team, month)
