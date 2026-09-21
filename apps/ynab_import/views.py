"""
The YNAB import wizard and its endpoints.

Every screen before the last one is a preview: the analysis and the build are pure,
so what the user reviews is produced by the same code that writes the books. The
only endpoint that changes anything is `api_apply`, and it hands the work to a
Celery task rather than doing it while the browser waits.
"""

import functools
import json
import logging

from celery.result import AsyncResult
from celery_progress.backend import Progress
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from kombu.exceptions import OperationalError

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.teams.decorators import login_and_team_required

from .models import MAX_UPLOAD_BYTES, YnabImport
from .services.apply import can_import
from .services.build import BuildError, build, parse_choices
from .services.parse import ParseError, identify, parse_plan, parse_register
from .services.payload import analysis_payload, plan_payload
from .services.reconcile import reconcile
from .services.session import analyse_record
from .tasks import run_ynab_import

logger = logging.getLogger(__name__)

# The bar never shows a full sweep while work is still going on: 100% is reserved
# for a row that says so.
NEARLY_DONE = 99

# How long a task Celery calls finished may leave its row untouched before it is
# treated as a worker that died rather than one that is a moment behind.
DEAD_WORKER_GRACE_SECONDS = 20


def json_errors(view):
    """
    Answer an unexpected exception with JSON, not with Django's HTML error page.

    Every endpoint here is called by `fetch`, which reads `error` off the body. An
    unhandled exception returns an HTML page instead, so the wizard has nothing to
    show but "Something went wrong." -- which is exactly the least useful thing to
    say to someone whose migrations have not been run. The exception is still
    logged with its traceback, so an error tracker reading the log sees it, and in
    DEBUG the reason itself is handed to the browser, because a developer looking
    at the wizard is the person who can act on it.
    """

    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except Exception as error:  # noqa: BLE001 - the wizard must say something, whatever broke
            logger.exception("YNAB import request failed: %s", request.path)
            detail = f"{type(error).__name__}: {error}" if settings.DEBUG else ""
            return JsonResponse(
                {
                    "error": (
                        "The server could not complete that step. If this team was set up from a new "
                        "version of the app, its database may need migrating."
                    ),
                    "detail": detail,
                },
                status=500,
            )

    return wrapped


@ensure_csrf_cookie
@login_and_team_required
def ynab_import_home(request, team_slug):
    """
    The wizard.

    Reachable both from the onboarding takeover ("Coming from YNAB?") and on its own,
    for a user who clicked through onboarding first and only then found their export.

    The import runs in a worker, so the browser is free to go away -- which means
    this page has to be able to answer what happened while it was gone. An import
    still running, or one that finished or failed in the last day, is handed to the
    wizard so it opens on that rather than on an upload form (or, once the
    transactions are in, on a "this team already has transactions" refusal that
    tells the user nothing about the import they ran).
    """
    resume = YnabImport.objects.resumable(request.team)

    return render(
        request,
        "ynab_import/ynab_import.html",
        {
            "active_tab": "settings",
            "settings_section": "import",
            "settings_page_title": _("Import from YNAB"),
            "settings_page_blurb": _(
                "Your accounts, your whole transaction history, your monthly budgets and your savings — "
                "brought over and checked against YNAB’s own numbers."
            ),
            "page_title": _("Import from YNAB"),
            "ynab_props": {
                "teamSlug": team_slug,
                "teamName": request.team.name,
                "canImport": can_import(request.team),
                "resume": resume.as_dict() if resume else None,
                "homeUrl": reverse("web_team:home", args=[team_slug]),
                "accountsUrl": reverse("accounts:accounts_home", args=[team_slug]),
                "budgetUrl": reverse("budget:budget_home", args=[team_slug]),
                "goalsUrl": reverse("budget:goals_list", args=[team_slug]),
                "urls": {
                    "upload": reverse("ynab_import:api_upload", args=[team_slug]),
                    "preview": reverse("ynab_import:api_preview", args=[team_slug]),
                    "apply": reverse("ynab_import:api_apply", args=[team_slug]),
                    "status": reverse("ynab_import:api_status", args=[team_slug]),
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


def _record(request, body) -> YnabImport | None:
    """The import this request is about, scoped to the team -- never by id alone."""
    return YnabImport.objects.filter(team=request.team, id=body.get("import_id")).first()


@require_POST
@login_and_team_required
@json_errors
def api_upload(request, team_slug):
    """
    Take both exports, work out which is which, and hand back what we found.

    The files are stored so the later screens and the Celery worker read the same
    bytes; nothing is written to the team's books here.
    """
    uploads = request.FILES.getlist("files")
    if len(uploads) < 2:
        return JsonResponse({"error": "Upload both files: the register and the plan."}, status=400)

    files = []
    for upload in uploads[:4]:
        if upload.size > MAX_UPLOAD_BYTES:
            return JsonResponse({"error": f"{upload.name} is too large to import."}, status=400)
        files.append((upload.name, upload.read()))

    try:
        register_bytes, plan_bytes = identify(files)
        register = parse_register(register_bytes)
        plan_rows = parse_plan(plan_bytes)
    except ParseError as error:
        return JsonResponse({"error": str(error)}, status=400)

    record = YnabImport.objects.create(
        team=request.team,
        created_by=request.user,
        register_csv=register_bytes.decode("utf-8", errors="replace"),
        plan_csv=plan_bytes.decode("utf-8", errors="replace"),
    )

    from .services.analyse import analyse

    analysis = analyse(register, plan_rows)
    log_event(
        AuditEvent.YNAB_IMPORT_STARTED,
        request=request,
        metadata={"rows": len(register), "accounts": len(analysis.accounts)},
    )

    return JsonResponse(
        {
            "import_id": record.id,
            "can_import": can_import(request.team),
            **analysis_payload(analysis),
            **plan_payload(build(analysis)),
        }
    )


@require_POST
@login_and_team_required
@json_errors
def api_preview(request, team_slug):
    """
    What the import will produce, given the answers so far.

    Built from the same `build()` the apply step runs, so the preview cannot promise
    something the import does not do.
    """
    body = _json_body(request)
    record = _record(request, body)
    if record is None:
        return JsonResponse({"error": "That import is no longer available. Start again."}, status=404)

    record.choices = body.get("choices") or {}
    record.save(update_fields=["choices", "updated_at"])

    try:
        analysis = analyse_record(record)
        plan = build(analysis, parse_choices(analysis, record.choices))
    except (ParseError, BuildError) as error:
        return JsonResponse({"error": str(error)}, status=400)

    return JsonResponse(
        {
            "import_id": record.id,
            **plan_payload(plan),
            "reconciliation": reconcile(analysis, plan).as_dict(),
        }
    )


@require_POST
@login_and_team_required
@json_errors
def api_apply(request, team_slug):
    """
    Start the import.

    The emptiness guard is here as well as in `apply_plan`: refusing before the task
    is queued is a message the user sees immediately, while the one inside the
    transaction is what actually makes it safe.
    """
    body = _json_body(request)
    record = _record(request, body)
    if record is None:
        return JsonResponse({"error": "That import is no longer available. Start again."}, status=404)
    if record.status != YnabImport.STATUS_UPLOADED:
        return JsonResponse({"import_id": record.id, **record.as_dict()})
    if not can_import(request.team):
        return JsonResponse(
            {
                "error": (
                    "This team already has transactions. A YNAB import brings a whole set of books, so it needs "
                    "an empty team -- create a new team, or delete the existing transactions first."
                )
            },
            status=409,
        )

    if choices := body.get("choices"):
        record.choices = choices
        record.save(update_fields=["choices", "updated_at"])

    try:
        result = run_ynab_import.delay(record.id)
        YnabImport.objects.filter(id=record.id).update(task_id=result.id)
        task_id = result.id
    except OperationalError:
        # No broker reachable (a dev machine without Celery, say). Running it here
        # makes for a slow request, which is a great deal better than a wizard that
        # sits at 0% forever with nothing to explain why.
        run_ynab_import(record.id)
        task_id = ""

    record.refresh_from_db()
    return JsonResponse({"import_id": record.id, "task_id": task_id, **record.as_dict()})


@login_and_team_required
@json_errors
def api_status(request, team_slug):
    """
    Where the import has got to.

    The row is authoritative -- a reloaded page must show a finished import as
    finished -- and Celery is consulted only for progress the row has not caught up
    with yet, since the two are written from the same worker microseconds apart.

    The one thing Celery is trusted for outright is *death*. A worker that is
    killed (an out-of-memory container, a deploy mid-import) never reaches the code
    that marks the row failed, so the row says "running" forever. Without this the
    wizard sits at whatever it last saw, waiting for a worker that is not coming.
    """
    record = YnabImport.objects.filter(team=request.team, id=request.GET.get("import_id")).first()
    if record is None:
        return JsonResponse({"error": "That import is no longer available."}, status=404)

    payload = record.as_dict()
    if record.is_finished or not record.task_id:
        return JsonResponse(payload)

    live = _live_progress(record)
    if live is None:
        return JsonResponse(payload)

    if live["complete"]:
        # `celery_progress` reports 100% for a finished task whether it succeeded or
        # failed, so that number must never reach the bar while the row still says
        # running -- that is the full-bar-forever the user would otherwise stare at.
        if _worker_is_gone(record):
            record.status = YnabImport.STATUS_FAILED
            record.error = (
                "The import stopped before it finished. Nothing was written -- it is applied in one go, so a "
                "run that does not reach the end leaves your books exactly as they were. Check the worker log, "
                "then start again."
            )
            record.finished_at = timezone.now()
            record.save(update_fields=["status", "error", "finished_at", "updated_at"])
            return JsonResponse(record.as_dict())
        # Still within the moment between the task returning and the row being
        # written: report near-complete rather than complete, and let the next poll
        # see the row itself.
        payload["progress"] = max(payload["progress"], NEARLY_DONE)
        return JsonResponse(payload)

    progress = live.get("progress") or {}
    percent = int(progress.get("percent") or 0)
    payload["progress"] = min(NEARLY_DONE, max(payload["progress"], percent))
    payload["step"] = progress.get("description") or payload["step"]
    payload["started"] = payload["started"] or not progress.get("pending")

    return JsonResponse(payload)


def _live_progress(record) -> dict | None:
    """What Celery makes of the task, or None when there is no result backend to ask."""
    try:
        return Progress(AsyncResult(record.task_id)).get_info()
    except Exception:  # noqa: BLE001 - a missing result backend must not break the page
        logger.debug("No live progress for YNAB import %s", record.id, exc_info=True)
        return None


def _worker_is_gone(record) -> bool:
    """
    Whether a task Celery calls finished has stopped writing to its row.

    The grace period is what separates a dead worker from the ordinary race: the
    task returns, and a moment later the same worker commits the row. Only silence
    that outlasts the grace period is a death.
    """
    last_seen = record.updated_at or record.started_at
    if last_seen is None:
        return True
    return (timezone.now() - last_seen).total_seconds() > DEAD_WORKER_GRACE_SECONDS
