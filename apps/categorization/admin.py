from django.contrib import admin

from .models import CategorizationDecision, CategorizationRule


@admin.register(CategorizationRule)
class CategorizationRuleAdmin(admin.ModelAdmin):
    list_display = ["name", "book", "priority", "mode", "is_enabled", "category"]
    list_filter = ["mode", "is_enabled"]
    search_fields = ["name", "payee_value", "description_value"]
    raw_id_fields = ["book", "account", "category"]


@admin.register(CategorizationDecision)
class CategorizationDecisionAdmin(admin.ModelAdmin):
    list_display = ["bank_transaction", "book", "source", "provider", "rule", "category", "created_at"]
    list_filter = ["source", "provider"]
    raw_id_fields = ["book", "bank_transaction", "journal_entry", "category", "rule"]
