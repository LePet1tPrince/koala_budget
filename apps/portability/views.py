"""
The export/import page and its endpoints (§7 Phase 4).

Every write endpoint is `@team_admin_required` (§4.4.3) -- exporting is
harmless for any member, but importing is the most destructive operation in
the product, and the export button lives on the same page as the import
button either way. The apply endpoint re-checks the typed team name
server-side (§4.4.4): the confirmation the browser enforces is a courtesy,
not the guard.
"""

import functools
import json
import logging

from celery.result import AsyncResult
from celery_progress.backend import Progress
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from kombu.exceptions import OperationalError

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.bank_feed.models import BankTransaction
from apps.plaid.models import PlaidAccount
from apps.teams.decorators import login_and_team_required, team_admin_required

from .models import MAX_UPLOAD_BYTES, DataImport
from .services import export, read, write
from .services.export import ExportError
from .services.schema import DocumentError
from .tasks import run_data_import

logger = logging.getLogger(__name__)

# Same reasoning as the YNAB importer's apply screen (apps/ynab_import/views.py):
# 100% is reserved for a row that actually says so.
NEARLY_DONE = 99
DEAD_WORKER_GRACE_SECONDS = 20


def json_errors(view):
    """Answer an unexpected exception with JSON, not Django's HTML error page -- every endpoint here is `fetch`ed."""

    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except Exception as error:  # noqa: BLE001 - the wizard must say something, whatever broke
            logger.exception("Data export/import request failed: %s", request.path)
            detail = f"{type(error).__name__}: {error}" if settings.DEBUG else ""
            return JsonResponse(
                {"error": "The server could not complete that step.", "detail": detail},
                status=500,
            )

    return wrapped


def _archive_filename(team, *, suffix: str = "") -> str:
    today = timezone.localdate().isoformat()
    tail = f"-{suffix}" if suffix else ""
    return f"koala-budget-{team.slug}-{today}{tail}.zip"


def _archive_response(data: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Length"] = str(len(data))
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_and_team_required
def export_view(request, team_slug):
    """
    Every member may export their own team's books (§9 open question --
    answered here as yes, read-only, own team). Synchronous and built in
    memory, with a real `Content-Length` (§3.6): a truncated download must be
    a transport error the browser reports, not a file that silently looks
    complete and is not.
    """
    try:
        accounts, journal_rows, budget_rows = export.build_archive(request.team)
    except ExportError as error:
        return render(request, "portability/export_too_large.html", {"error": str(error)}, status=400)

    checks = export.build_checks(request.team)
    omitted = export.build_omitted(request.team)
    data = write.build_archive_bytes(
        accounts=accounts,
        journal=journal_rows,
        budget=budget_rows,
        source={"team_name": request.team.name},
        checks=checks,
        omitted=omitted,
    )

    log_event(AuditEvent.DATA_EXPORTED, request=request, metadata={"counts": checks["counts"]})

    return _archive_response(data, _archive_filename(request.team))


@ensure_csrf_cookie
@team_admin_required
def portability_home(request, team_slug):
    """The page: an Export card and an Import card (§7 Phase 4)."""
    uncategorized_count = BankTransaction.objects.filter(team=request.team, journal_entry__isnull=True).count()
    resume = (
        DataImport.objects.filter(team=request.team, status__in=[DataImport.STATUS_UPLOADED, DataImport.STATUS_RUNNING])
        .order_by("-created_at")
        .first()
    )

    return render(
        request,
        "portability/portability.html",
        {
            "active_tab": "settings",
            "settings_section": "data_transfer",
            "settings_page_title": _("Export & Import"),
            "settings_page_blurb": _(
                "Download everything in this team's books, or replace them entirely with a Koala Budget export."
            ),
            "page_title": _("Export & Import"),
            "portability_props": {
                "teamSlug": team_slug,
                "teamName": request.team.name,
                "uncategorizedCount": uncategorized_count,
                "bankFeedUrl": reverse("bank_feed:bank_feed_home", args=[team_slug]),
                "homeUrl": reverse("web_team:home", args=[team_slug]),
                "resume": resume.as_dict() if resume else None,
                "urls": {
                    "export": reverse("portability:export", args=[team_slug]),
                    "upload": reverse("portability:api_upload", args=[team_slug]),
                    "apply": reverse("portability:api_apply", args=[team_slug]),
                    "status": reverse("portability:api_status", args=[team_slug]),
                    "safetyExport": reverse("portability:api_safety_export", args=[team_slug]),
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


@require_POST
@team_admin_required
@json_errors
def api_upload(request, team_slug):
    """
    Parse and validate the uploaded archive, and show what it will replace.
    Writes nothing -- the row this creates just remembers the bytes for the
    apply step, the way `YnabImport` does.
    """
    uploads = request.FILES.getlist("file")
    if not uploads:
        return JsonResponse({"error": "Choose an export file (.zip) to upload."}, status=400)
    upload = uploads[0]
    if upload.size > MAX_UPLOAD_BYTES:
        return JsonResponse({"error": f"{upload.name} is too large to import."}, status=400)
    data = upload.read()

    try:
        tables = read.read_archive(data)
    except DocumentError as error:
        return JsonResponse({"error": str(error)}, status=400)

    record = DataImport.objects.create(team=request.team, created_by=request.user, archive=data)

    return JsonResponse(
        {
            "import_id": record.id,
            "file": {
                "source": tables.manifest.source,
                "checks": tables.manifest.checks,
                "omitted": tables.manifest.omitted,
                "hash_warnings": tables.hash_warnings,
            },
            "destination": {
                "team_name": request.team.name,
                "checks": export.build_checks(request.team),
                "has_plaid": PlaidAccount.objects.filter(team=request.team).exists(),
            },
        }
    )


@require_POST
@team_admin_required
@json_errors
def api_apply(request, team_slug):
    """
    Start the import. The typed team name is checked here, server-side --
    the confirmation dialog the browser shows is a courtesy, not the guard
    (§4.4.4).
    """
    body = _json_body(request)
    record = DataImport.objects.filter(team=request.team, id=body.get("import_id")).first()
    if record is None:
        return JsonResponse({"error": "That upload is no longer available. Start again."}, status=404)
    if record.status != DataImport.STATUS_UPLOADED:
        return JsonResponse({"import_id": record.id, **record.as_dict()})

    typed_name = (body.get("team_name") or "").strip()
    if typed_name != request.team.name:
        return JsonResponse({"error": "Type the team name exactly to confirm."}, status=400)

    try:
        async_result = run_data_import.delay(record.id)
        DataImport.objects.filter(id=record.id).update(task_id=async_result.id)
        task_id = async_result.id
    except OperationalError:
        # No broker reachable (a dev machine without Celery, say). Running it
        # here makes for a slow request, which is far better than a wizard
        # that sits at 0% forever with nothing to explain why.
        run_data_import(record.id)
        task_id = ""

    record.refresh_from_db()
    return JsonResponse({"import_id": record.id, "task_id": task_id, **record.as_dict()})


@team_admin_required
@json_errors
def api_status(request, team_slug):
    """Where the import has got to. Modelled on the YNAB importer's own status endpoint -- same reasoning throughout."""
    record = DataImport.objects.filter(team=request.team, id=request.GET.get("import_id")).first()
    if record is None:
        return JsonResponse({"error": "That import is no longer available."}, status=404)

    payload = record.as_dict()
    if record.is_finished or not record.task_id:
        return JsonResponse(payload)

    live = _live_progress(record)
    if live is None:
        return JsonResponse(payload)

    if live["complete"]:
        if _worker_is_gone(record):
            record.status = DataImport.STATUS_FAILED
            record.error = (
                "The import stopped before it finished. Nothing was written -- it is applied in one go, so a "
                "run that does not reach the end leaves your books exactly as they were. Check the worker log, "
                "then start again."
            )
            record.finished_at = timezone.now()
            record.save(update_fields=["status", "error", "finished_at", "updated_at"])
            return JsonResponse(record.as_dict())
        payload["progress"] = max(payload["progress"], NEARLY_DONE)
        return JsonResponse(payload)

    progress = live.get("progress") or {}
    percent = int(progress.get("percent") or 0)
    payload["progress"] = min(NEARLY_DONE, max(payload["progress"], percent))
    payload["step"] = progress.get("description") or payload["step"]
    payload["started"] = payload["started"] or not progress.get("pending")

    return JsonResponse(payload)


@team_admin_required
def api_safety_export(request, team_slug):
    """The pre-wipe copy, while `SAFETY_EXPORT_WINDOW` has not yet elapsed."""
    record = DataImport.objects.filter(team=request.team, id=request.GET.get("import_id")).first()
    if record is None or not record.safety_archive_available:
        raise Http404
    return _archive_response(bytes(record.safety_archive), _archive_filename(request.team, suffix="before-import"))


def _live_progress(record) -> dict | None:
    try:
        return Progress(AsyncResult(record.task_id)).get_info()
    except Exception:  # noqa: BLE001 - a missing result backend must not break the page
        logger.debug("No live progress for data import %s", record.id, exc_info=True)
        return None


def _worker_is_gone(record) -> bool:
    last_seen = record.updated_at or record.started_at
    if last_seen is None:
        return True
    return (timezone.now() - last_seen).total_seconds() > DEAD_WORKER_GRACE_SECONDS
