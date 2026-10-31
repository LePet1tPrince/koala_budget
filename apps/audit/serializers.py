from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.audit.models import AuditEvent, AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_display = serializers.SerializerMethodField()
    via = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ["id", "action", "source_model", "timestamp", "user_display", "via", "changes", "event_id"]

    @extend_schema_field(serializers.CharField())
    def get_via(self, obj):
        """
        What made the change, when it wasn't a person's own edit -- e.g. "rule
        “Coffee”" for a row an automatic categorization filed. Read from the
        operation-level event the change is linked to; "" otherwise.
        """
        event = obj.event
        if event is None or not isinstance(event.metadata, dict):
            return ""
        return str(event.metadata.get("via") or "")

    @extend_schema_field(serializers.CharField())
    def get_user_display(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.email
        return "System"


class AuditEventSerializer(serializers.ModelSerializer):
    user_display = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = ["id", "event_type", "timestamp", "user_display", "metadata", "ip_address"]

    @extend_schema_field(serializers.CharField())
    def get_user_display(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.email
        return "System"
