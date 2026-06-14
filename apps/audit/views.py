from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.audit.models import AuditEvent
from apps.audit.serializers import AuditEventSerializer
from apps.teams.permissions import TeamModelAccessPermissions


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
    permission_classes = [TeamModelAccessPermissions]
    queryset = AuditEvent.objects.none()  # for drf-spectacular schema generation

    def get_queryset(self):
        qs = AuditEvent.objects.filter(team=self.request.team).select_related("user")
        event_type = self.request.query_params.get("event_type")
        if event_type:
            qs = qs.filter(event_type=event_type)
        return qs
