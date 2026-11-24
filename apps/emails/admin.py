from django.contrib import admin

from .models import EmailPreferences, SentEmail


@admin.register(EmailPreferences)
class EmailPreferencesAdmin(admin.ModelAdmin):
    list_display = ("user", "bank_connection_alerts", "budget_alerts", "updated_at")
    search_fields = ("user__email",)
    raw_id_fields = ("user",)


@admin.register(SentEmail)
class SentEmailAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "user", "key")
    list_filter = ("kind",)
    search_fields = ("user__email", "key")
    raw_id_fields = ("user", "book")
    readonly_fields = ("user", "kind", "key", "book", "created_at")
