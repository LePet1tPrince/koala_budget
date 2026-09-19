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
    """
    return render(
        request,
        "ynab_import/ynab_import.html",
        {
            "page_title": _("Import from YNAB"),
            "ynab_props": {
                "teamSlug": team_slug,
                "teamName": request.team.name,
                "canImport": can_import(request.team),
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

    The row carries the authoritative status; Celery carries the live progress within
    a run, which is finer-grained and survives nothing. Both are reported, and the row
    wins -- a reloaded page must still show a finished import as finished.
    """
    record = YnabImport.objects.filter(team=request.team, id=request.GET.get("import_id")).first()
    if record is None:
        return JsonResponse({"error": "That import is no longer available."}, status=404)

    payload = record.as_dict()
    if record.task_id and not record.is_finished:
        try:
            live = Progress(AsyncResult(record.task_id)).get_info()
        except Exception:  # noqa: BLE001 - a missing result backend must not break the page
            live = None
        if live and live.get("progress"):
            payload["progress"] = max(payload["progress"], int(live["progress"].get("percent") or 0))
            payload["step"] = live["progress"].get("description") or payload["step"]

    return JsonResponse(payload)
