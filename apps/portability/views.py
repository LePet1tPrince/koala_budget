"""
The export/import page and its API (§7 Phase 4).

Everything but the export itself is admin-only (`@book_admin_required`,
`BookAdminPermissions`; §4.4.3) -- exporting is harmless for any member, but
importing is the most destructive operation in the product, and the export
button lives on the same page as the import button either way. The apply
endpoint re-checks the typed book name server-side (§4.4.4): the confirmation
the browser enforces is a courtesy, not the guard.
"""

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from kombu.exceptions import OperationalError
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.api.base import BookAPIView
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.bank_feed.models import BankTransaction
from apps.books.decorators import book_admin_required, login_and_book_required
from apps.books.permissions import BookAdminPermissions
from apps.plaid.models import PlaidAccount
from apps.utils.json_views import UnexpectedErrorsAsJson
from apps.utils.progress import status_payload
from apps.utils.progress_serializers import ImportStatusQuerySerializer

from .models import MAX_UPLOAD_BYTES, DataImport
from .serializers import (
    DataApplyRequestSerializer,
    DataImportStartedSerializer,
    DataImportStatusSerializer,
    DataUploadRequestSerializer,
    DataUploadResultSerializer,
    PortabilityPageSerializer,
)
from .services import export, read, write
from .services.export import ExportError
from .services.schema import DocumentError
from .tasks import run_data_import

TAGS = ["portability"]


def _archive_filename(book, *, suffix: str = "") -> str:
    today = timezone.localdate().isoformat()
    tail = f"-{suffix}" if suffix else ""
    return f"koala-budget-{book.team.slug}-{book.slug}-{today}{tail}.zip"


def _source(book) -> dict:
    """Where an archive came from, for the manifest. Informational only; import never reads it back."""
    return {"team_name": book.team.name, "book_name": book.name}


def _archive_response(data: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Length"] = str(len(data))
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_and_book_required
def export_view(request, team_slug, book_slug):
    """
    Every member may export a set of books of their own team (§9 open
    question -- answered here as yes, read-only, own team). Synchronous and built in
    memory, with a real `Content-Length` (§3.6): a truncated download must be
    a transport error the browser reports, not a file that silently looks
    complete and is not.
    """
    try:
        accounts, journal_rows, budget_rows = export.build_archive(request.book)
    except ExportError as error:
        return render(request, "portability/export_too_large.html", {"error": str(error)}, status=400)

    checks = export.build_checks(request.book)
    omitted = export.build_omitted(request.book)
    data = write.build_archive_bytes(
        accounts=accounts,
        journal=journal_rows,
        budget=budget_rows,
        reconciliations=export.build_reconciliation_rows(request.book),
        goal_links=export.build_goal_link_rows(request.book),
        source=_source(request.book),
        checks=checks,
        omitted=omitted,
    )

    log_event(AuditEvent.DATA_EXPORTED, request=request, metadata={"counts": checks["counts"]})

    return _archive_response(data, _archive_filename(request.book))


@ensure_csrf_cookie
@book_admin_required
def portability_home(request, team_slug, book_slug):
    """The page: an Export card and an Import card (§7 Phase 4). The wizard loads its state from `api/state/`."""
    return render(
        request,
        "portability/portability.html",
        {
            "active_tab": "settings",
            "settings_section": "data_transfer",
            "settings_page_title": _("Export & Import"),
            "settings_page_blurb": _(
                "Download everything in this set of books, or replace it entirely with a Koala Budget export."
            ),
            "page_title": _("Export & Import"),
        },
    )


class PortabilityAPIView(UnexpectedErrorsAsJson, BookAPIView):
    permission_classes = [BookAdminPermissions]
    unexpected_error_label = "Data export/import request"

    def record(self, import_id, message="That import is no longer available.") -> DataImport:
        """The import this request is about, scoped to the book -- never by id alone."""
        record = DataImport.objects.filter(book=self.book, id=import_id).first()
        if record is None:
            raise NotFound(message)
        return record


class StateView(PortabilityAPIView):
    """
    What the page opens on: the export warning's count, and an import to pick back
    up -- one uploaded or running, the most recent first.
    """

    @extend_schema(operation_id="portability_state", tags=TAGS, responses=PortabilityPageSerializer)
    def get(self, request, team_slug, book_slug):
        resume = (
            DataImport.objects.filter(
                book=self.book, status__in=[DataImport.STATUS_UPLOADED, DataImport.STATUS_RUNNING]
            )
            .order_by("-created_at")
            .first()
        )
        data = {
            "book_name": self.book.name,
            "uncategorized_count": BankTransaction.objects.filter(book=self.book, journal_entry__isnull=True).count(),
            "resume": resume.as_dict() if resume else None,
        }
        return Response(PortabilityPageSerializer(data).data)


class UploadView(PortabilityAPIView):
    """
    Parse and validate the uploaded archive, and show what it will replace.
    Writes nothing -- the row this creates just remembers the bytes for the
    apply step, the way `YnabImport` does.
    """

    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="portability_upload",
        tags=TAGS,
        request={"multipart/form-data": DataUploadRequestSerializer},
        responses=DataUploadResultSerializer,
    )
    def post(self, request, team_slug, book_slug):
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": ["Choose an export file (.zip) to upload."]})
        if upload.size > MAX_UPLOAD_BYTES:
            raise ValidationError({"file": [f"{upload.name} is too large to import."]})
        data = upload.read()

        try:
            tables = read.read_archive(data)
        except DocumentError as error:
            raise ValidationError({"file": [str(error)]}) from None

        record = DataImport.objects.create(book=self.book, created_by=request.user, archive=data)

        payload = {
            "import_id": record.id,
            "file": {
                "source": tables.manifest.source,
                "checks": tables.manifest.checks,
                "omitted": tables.manifest.omitted,
                "hash_warnings": tables.hash_warnings,
            },
            "destination": {
                "team_name": request.team.name,
                "book_name": self.book.name,
                "checks": export.build_checks(self.book),
                "has_plaid": PlaidAccount.objects.filter(book=self.book).exists(),
            },
        }
        return Response(DataUploadResultSerializer(payload).data)


class ApplyView(PortabilityAPIView):
    """
    Start the import: the book is wiped and replaced by the uploaded archive. The
    typed book name is checked here, server-side -- the confirmation dialog the
    browser shows is a courtesy, not the guard (§4.4.4). An import already started
    answers its status rather than starting again.
    """

    @extend_schema(
        operation_id="portability_apply",
        tags=TAGS,
        request=DataApplyRequestSerializer,
        responses=DataImportStartedSerializer,
    )
    def post(self, request, team_slug, book_slug):
        body = DataApplyRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        record = self.record(body.validated_data["import_id"], "That upload is no longer available. Start again.")
        if record.status != DataImport.STATUS_UPLOADED:
            return self._started(record, task_id=record.task_id)

        # The book is what gets replaced, so its name -- not the team's -- is the one
        # typed: in a team with several books, that is what says which one goes.
        if body.validated_data["book_name"].strip() != self.book.name:
            raise ValidationError({"book_name": ["Type the name of this set of books exactly to confirm."]})

        try:
            async_result = run_data_import.delay(record.id)
            task_id = str(async_result.id or "")
            DataImport.objects.filter(id=record.id).update(task_id=task_id)
        except OperationalError:
            # No broker reachable (a dev machine without Celery, say). Running it
            # here makes for a slow request, which is far better than a wizard
            # that sits at 0% forever with nothing to explain why.
            run_data_import(record.id)
            task_id = ""

        record.refresh_from_db()
        return self._started(record, task_id=task_id)

    @staticmethod
    def _started(record, *, task_id):
        data = {"import_id": record.id, "task_id": task_id, **record.as_dict()}
        return Response(DataImportStartedSerializer(data).data)


class StatusView(PortabilityAPIView):
    """Where the import has got to. See `apps.utils.progress.status_payload`."""

    # Polled about once a second for as long as an import runs: the per-user
    # throttle would cut a long import's progress bar off part-way.
    throttle_classes = []

    @extend_schema(
        operation_id="portability_status",
        tags=TAGS,
        parameters=[ImportStatusQuerySerializer],
        responses=DataImportStatusSerializer,
    )
    def get(self, request, team_slug, book_slug):
        query = ImportStatusQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        record = self.record(query.validated_data["import_id"])
        return Response(DataImportStatusSerializer(status_payload(record)).data)


class SafetyExportView(PortabilityAPIView):
    """
    The pre-wipe copy of the book, as a .zip download, while `SAFETY_EXPORT_WINDOW`
    has not yet elapsed; a 404 after it, or before anything has run. A plain link
    in the web app (a browser download), so it is not wrapped by the api-client.
    """

    @extend_schema(
        operation_id="portability_safety_export",
        tags=TAGS,
        parameters=[ImportStatusQuerySerializer],
        responses={(200, "application/zip"): OpenApiResponse(OpenApiTypes.BINARY, description="The archive.")},
    )
    def get(self, request, team_slug, book_slug):
        query = ImportStatusQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        record = self.record(query.validated_data["import_id"])
        if not record.safety_archive_available:
            raise NotFound("The copy taken before this import is no longer available.")
        return _archive_response(bytes(record.safety_archive), _archive_filename(self.book, suffix="before-import"))
