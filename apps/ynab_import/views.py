"""
The YNAB import wizard and its endpoints.

Every screen before the last one is a preview: the analysis and the build are pure,
so what the user reviews is produced by the same code that writes the books. The
only endpoint that changes anything is `api_apply`, and it hands the work to a
Celery task rather than doing it while the browser waits.
"""

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from kombu.exceptions import OperationalError

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.decorators import login_and_book_required
from apps.onboarding.models import OnboardingState
from apps.utils.json_views import json_body, json_errors
from apps.utils.progress import status_payload

from .models import MAX_UPLOAD_BYTES, YnabImport
from .services.apply import can_import
from .services.build import BuildError, build, parse_choices
from .services.parse import ParseError, identify, parse_plan, parse_register
from .services.payload import analysis_payload, plan_payload
from .services.reconcile import reconcile
from .services.session import analyse_record
from .tasks import run_ynab_import

ynab_json_errors = json_errors(
    "The server could not complete that step. If this book was set up from a new "
    "version of the app, its database may need migrating.",
    log_label="YNAB import request",
)


@ensure_csrf_cookie
@login_and_book_required
def ynab_import_home(request, team_slug, book_slug):
    """
    The wizard.

    Reachable both from the onboarding takeover ("Coming from YNAB?") and on its own,
    for a user who clicked through onboarding first and only then found their export.

    The import runs in a worker, so the browser is free to go away -- which means
    this page has to be able to answer what happened while it was gone. An import
    still running, or one that finished or failed in the last day, is handed to the
    wizard so it opens on that rather than on an upload form (or, once the
    transactions are in, on a "this book already has transactions" refusal that
    tells the user nothing about the import they ran).
    """
    resume = YnabImport.objects.resumable(request.book)

    return render(
        request,
        "ynab_import/ynab_import.html",
        {
            "page_title": _("Import from YNAB"),
            "takeover_title": _("Import from YNAB"),
            "takeover_eyebrow": request.book.name,
            "takeover_close_url": _close_url(request.book),
            "ynab_props": {
                "teamSlug": team_slug,
                "teamName": request.book.name,
                "bookName": request.book.name,
                "canImport": can_import(request.book),
                "resume": resume.as_dict() if resume else None,
                "homeUrl": reverse("web_book:home", args=[team_slug, book_slug]),
                "accountsUrl": reverse("accounts:accounts_home", args=[team_slug, book_slug]),
                "budgetUrl": reverse("budget:budget_home", args=[team_slug, book_slug]),
                "goalsUrl": reverse("budget:goals_list", args=[team_slug, book_slug]),
                "urls": {
                    "upload": reverse("ynab_import:api_upload", args=[team_slug, book_slug]),
                    "preview": reverse("ynab_import:api_preview", args=[team_slug, book_slug]),
                    "apply": reverse("ynab_import:api_apply", args=[team_slug, book_slug]),
                    "status": reverse("ynab_import:api_status", args=[team_slug, book_slug]),
                },
            },
        },
    )


def _close_url(book) -> str:
    """
    Where the takeover's close button goes.

    A book still being set up (a new book whose owner chose "Import from YNAB",
    or the onboarding takeover's "Coming from YNAB?") goes back to its home, which
    sends it into the onboarding welcome -- the screen that offers the other ways
    to start. A book already in use came here from Settings, so it goes back there.
    """
    if settings.ONBOARDING_ENABLED and not (
        OnboardingState.objects.filter(book=book)
        .filter(Q(completed_at__isnull=False) | Q(skipped_at__isnull=False))
        .exists()
    ):
        return reverse("web_book:home", args=book.url_args)
    return reverse("web_team:settings", args=[book.team.slug])


def _record(request, body) -> YnabImport | None:
    """The import this request is about, scoped to the book -- never by id alone."""
    return YnabImport.objects.filter(book=request.book, id=body.get("import_id")).first()


@require_POST
@login_and_book_required
@ynab_json_errors
def api_upload(request, team_slug, book_slug):
    """
    Take both exports, work out which is which, and hand back what we found.

    The files are stored so the later screens and the Celery worker read the same
    bytes; nothing is written to the books here.
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
        book=request.book,
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
            "can_import": can_import(request.book),
            **analysis_payload(analysis),
            **plan_payload(build(analysis)),
        }
    )


@require_POST
@login_and_book_required
@ynab_json_errors
def api_preview(request, team_slug, book_slug):
    """
    What the import will produce, given the answers so far.

    Built from the same `build()` the apply step runs, so the preview cannot promise
    something the import does not do.
    """
    body = json_body(request)
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
@login_and_book_required
@ynab_json_errors
def api_apply(request, team_slug, book_slug):
    """
    Start the import.

    The emptiness guard is here as well as in `apply_plan`: refusing before the task
    is queued is a message the user sees immediately, while the one inside the
    transaction is what actually makes it safe.
    """
    body = json_body(request)
    record = _record(request, body)
    if record is None:
        return JsonResponse({"error": "That import is no longer available. Start again."}, status=404)
    if record.status != YnabImport.STATUS_UPLOADED:
        return JsonResponse({"import_id": record.id, **record.as_dict()})
    if not can_import(request.book):
        return JsonResponse(
            {
                "error": (
                    "This set of books already has transactions. A YNAB import brings a whole set of books, "
                    "so it needs "
                    "an empty one -- create a new set of books, or delete the existing transactions first."
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


@login_and_book_required
@ynab_json_errors
def api_status(request, team_slug, book_slug):
    """Where the import has got to. See `apps.utils.progress.status_payload`."""
    record = YnabImport.objects.filter(book=request.book, id=request.GET.get("import_id")).first()
    if record is None:
        return JsonResponse({"error": "That import is no longer available."}, status=404)

    return JsonResponse(status_payload(record))
