"""
The YNAB import wizard and its API.

Every screen before the last one is a preview: the analysis and the build are pure,
so what the user reviews is produced by the same code that writes the books. The
only endpoint that changes anything is `api/apply/`, and it hands the work to a
Celery task rather than doing it while the browser waits.

Any member of the book's team may import (`BookAccessPermissions`); the record is
always looked up within the URL's book, never by id alone.
"""

from django.conf import settings
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import OpenApiRequest, extend_schema
from kombu.exceptions import OperationalError
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.api.base import BookAPIView
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.books.decorators import login_and_book_required
from apps.onboarding.models import OnboardingState
from apps.utils.json_views import UnexpectedErrorsAsJson
from apps.utils.progress import status_payload
from apps.utils.progress_serializers import ImportStatusQuerySerializer

from .models import MAX_UPLOAD_BYTES, YnabImport
from .serializers import (
    YnabChoicesRequestSerializer,
    YnabPageSerializer,
    YnabPreviewResultSerializer,
    YnabStartedSerializer,
    YnabStatusSerializer,
    YnabUploadRequestSerializer,
    YnabUploadResultSerializer,
)
from .services.apply import can_import
from .services.build import BuildError, build, parse_choices
from .services.parse import ParseError, identify, parse_plan, parse_register
from .services.payload import analysis_payload, plan_payload
from .services.reconcile import reconcile
from .services.session import analyse_record
from .tasks import run_ynab_import

TAGS = ["ynab-import"]

GONE = "That import is no longer available. Start again."

NOT_EMPTY = (
    "This set of books already has transactions. A YNAB import brings a whole set of books, so it needs "
    "an empty one -- create a new set of books, or delete the existing transactions first."
)


@ensure_csrf_cookie
@login_and_book_required
def ynab_import_home(request, team_slug, book_slug):
    """
    The wizard.

    Reachable both from the onboarding takeover ("Coming from YNAB?") and on its own,
    for a user who clicked through onboarding first and only then found their export.
    The page is an empty shell; the wizard loads its starting point from `api/state/`.
    """
    return render(
        request,
        "ynab_import/ynab_import.html",
        {
            "page_title": _("Import from YNAB"),
            "takeover_title": _("Import from YNAB"),
            "takeover_eyebrow": request.book.name,
            "takeover_close_url": _close_url(request.book),
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


class YnabAPIView(UnexpectedErrorsAsJson, BookAPIView):
    # The commonest unexpected error is a database that has not been migrated,
    # which is a one-command fix the user can only make if they are told.
    unexpected_error_message = (
        "The server could not complete that step. If this book was set up from a new "
        "version of the app, its database may need migrating."
    )
    unexpected_error_label = "YNAB import request"

    def record(self, import_id) -> YnabImport:
        """The import this request is about, scoped to the book -- never by id alone."""
        record = YnabImport.objects.filter(book=self.book, id=import_id).first()
        if record is None:
            raise NotFound(GONE)
        return record


class StateView(YnabAPIView):
    """
    Where the wizard opens.

    The import runs in a worker, so the browser is free to go away -- which means
    the wizard has to be able to answer what happened while it was gone. An import
    still running, or one that finished or failed in the last day, is `resume`, so
    the wizard opens on that rather than on an upload form (or, once the
    transactions are in, on a "this book already has transactions" refusal that
    tells the user nothing about the import they ran).
    """

    @extend_schema(operation_id="ynab_import_state", tags=TAGS, responses=YnabPageSerializer)
    def get(self, request, team_slug, book_slug):
        resume = YnabImport.objects.resumable(self.book)
        data = {
            "book_name": self.book.name,
            "can_import": can_import(self.book),
            "resume": resume.as_dict() if resume else None,
        }
        return Response(YnabPageSerializer(data).data)


class UploadView(YnabAPIView):
    """
    Take both exports, work out which is which, and hand back what we found.

    The files are stored so the later screens and the Celery worker read the same
    bytes; nothing is written to the books here.
    """

    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="ynab_import_upload",
        tags=TAGS,
        # `explode`: one `files` part per file, which is how the generated client sends a list.
        request=OpenApiRequest(YnabUploadRequestSerializer, encoding={"files": {"style": "form", "explode": True}}),
        responses=YnabUploadResultSerializer,
    )
    def post(self, request, team_slug, book_slug):
        uploads = request.FILES.getlist("files")
        if len(uploads) < 2:
            raise ValidationError({"files": ["Upload both files: the register and the plan."]})

        files = []
        for upload in uploads[:4]:
            if upload.size > MAX_UPLOAD_BYTES:
                raise ValidationError({"files": [f"{upload.name} is too large to import."]})
            files.append((upload.name, upload.read()))

        try:
            register_bytes, plan_bytes = identify(files)
            register = parse_register(register_bytes)
            plan_rows = parse_plan(plan_bytes)
        except ParseError as error:
            raise ValidationError({"files": [str(error)]}) from None

        record = YnabImport.objects.create(
            book=self.book,
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

        data = {
            "import_id": record.id,
            "can_import": can_import(self.book),
            **analysis_payload(analysis),
            **plan_payload(build(analysis)),
        }
        return Response(YnabUploadResultSerializer(data).data)


class PreviewView(YnabAPIView):
    """
    What the import will produce, given the answers so far, checked against YNAB's
    own numbers. The choices are saved on the import.

    Built from the same `build()` the apply step runs, so the preview cannot promise
    something the import does not do.
    """

    @extend_schema(
        operation_id="ynab_import_preview",
        tags=TAGS,
        request=YnabChoicesRequestSerializer,
        responses=YnabPreviewResultSerializer,
    )
    def post(self, request, team_slug, book_slug):
        body = YnabChoicesRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        record = self.record(body.validated_data["import_id"])

        record.choices = body.validated_data["choices"] or {}
        record.save(update_fields=["choices", "updated_at"])

        try:
            analysis = analyse_record(record)
            plan = build(analysis, parse_choices(analysis, record.choices))
        except (ParseError, BuildError) as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from None

        data = {"import_id": record.id, **plan_payload(plan), "reconciliation": reconcile(analysis, plan).as_dict()}
        return Response(YnabPreviewResultSerializer(data).data)


class ApplyView(YnabAPIView):
    """
    Start the import (`choices`, when given, replace the saved ones). An import
    already started answers its status rather than starting again.

    The emptiness guard (409) is here as well as in `apply_plan`: refusing before
    the task is queued is a message the user sees immediately, while the one inside
    the transaction is what actually makes it safe.
    """

    @extend_schema(
        operation_id="ynab_import_apply",
        tags=TAGS,
        request=YnabChoicesRequestSerializer,
        responses={200: YnabStartedSerializer},
    )
    def post(self, request, team_slug, book_slug):
        body = YnabChoicesRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        record = self.record(body.validated_data["import_id"])

        if record.status != YnabImport.STATUS_UPLOADED:
            return self._started(record, task_id=record.task_id)
        if not can_import(self.book):
            return Response({"detail": NOT_EMPTY}, status=status.HTTP_409_CONFLICT)

        if choices := body.validated_data["choices"]:
            record.choices = choices
            record.save(update_fields=["choices", "updated_at"])

        try:
            result = run_ynab_import.delay(record.id)
            task_id = str(result.id or "")
            YnabImport.objects.filter(id=record.id).update(task_id=task_id)
        except OperationalError:
            # No broker reachable (a dev machine without Celery, say). Running it here
            # makes for a slow request, which is a great deal better than a wizard that
            # sits at 0% forever with nothing to explain why.
            run_ynab_import(record.id)
            task_id = ""

        record.refresh_from_db()
        return self._started(record, task_id=task_id)

    @staticmethod
    def _started(record, *, task_id):
        return Response(YnabStartedSerializer({"import_id": record.id, "task_id": task_id, **record.as_dict()}).data)


class StatusView(YnabAPIView):
    """Where the import has got to. See `apps.utils.progress.status_payload`."""

    # Polled about once a second for as long as an import runs: the per-user
    # throttle would cut a long import's progress bar off part-way.
    throttle_classes = []

    @extend_schema(
        operation_id="ynab_import_status",
        tags=TAGS,
        parameters=[ImportStatusQuerySerializer],
        responses=YnabStatusSerializer,
    )
    def get(self, request, team_slug, book_slug):
        query = ImportStatusQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        record = self.record(query.validated_data["import_id"])
        return Response(YnabStatusSerializer(status_payload(record)).data)
