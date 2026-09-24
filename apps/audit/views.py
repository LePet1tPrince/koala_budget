from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.audit.models import AuditEvent
from apps.audit.serializers import AuditEventSerializer
from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name
from apps.books.permissions import BookAccessPermissions


@extend_schema_view(
    list=extend_schema(
        operation_id="audit_events_list",
        tags=["audit"],
        parameters=[
            OpenApiParameter(
                name="event_type",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter by event type",
                required=False,
            ),
        ],
    ),
    retrieve=extend_schema(operation_id="audit_events_retrieve", tags=["audit"]),
)
class AuditEventViewSet(ReadOnlyModelViewSet):
    serializer_class = AuditEventSerializer
    permission_classes = [BookAccessPermissions]
    queryset = AuditEvent.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        qs = book_events(self.request).select_related("user")
        event_type = self.request.query_params.get("event_type")
        if event_type:
            qs = qs.filter(event_type=event_type)
        return qs


def book_events(request):
    """
    This book's events, plus the team's own (logins, membership changes), which
    belong to no book. Never another book's.
    """
    return AuditEvent.objects.filter(Q(book=request.book) | Q(book__isnull=True, team=request.team))


@login_and_book_required
def audit_log_view(request, team_slug, book_slug):
    from django.shortcuts import render

    event_type_choices = [(value, label) for value, label in AuditEvent.EVENT_TYPE_CHOICES]
    return render(
        request,
        "audit/audit_log.html",
        {
            "active_tab": "settings",
            "settings_section": "audit",
            "settings_page_title": _("Audit log"),
            "settings_page_blurb": _("Logins, imports, syncs and bulk operations for this set of books."),
            "page_title": _("Audit Log | {name}").format(name=book_display_name(request.book)),
            "api_base_url": reverse("audit:audit-event-list", args=request.book.url_args),
            "event_type_choices": event_type_choices,
        },
    )
