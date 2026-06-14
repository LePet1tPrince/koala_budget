from django.contrib import admin

from apps.audit.models import AuditEvent, AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "action", "source_model", "object_id", "journal_entry_id", "user", "team"]
    list_filter = ["action", "source_model", "timestamp"]
    search_fields = ["object_id", "journal_entry_id"]
    readonly_fields = [
        "content_type",
        "object_id",
        "journal_entry_id",
        "team",
        "user",
        "event",
        "action",
        "timestamp",
        "changes",
        "source_model",
    ]
    date_hierarchy = "timestamp"


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "event_type", "user", "team", "ip_address"]
    list_filter = ["event_type", "timestamp"]
    search_fields = ["ip_address"]
    readonly_fields = ["team", "user", "event_type", "timestamp", "ip_address", "metadata"]
    date_hierarchy = "timestamp"
