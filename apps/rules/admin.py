from django.contrib import admin

from .models import Rule, RuleMatch, RuleProposal


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ["name", "book", "priority", "mode", "action", "is_active", "times_applied", "last_matched_at"]
    list_filter = ["mode", "action", "is_active"]
    search_fields = ["name"]


@admin.register(RuleMatch)
class RuleMatchAdmin(admin.ModelAdmin):
    list_display = ["transaction", "rule_name", "status", "held_reason", "created_at"]
    list_filter = ["status", "held_reason"]
    raw_id_fields = ["transaction", "rule", "category"]


@admin.register(RuleProposal)
class RuleProposalAdmin(admin.ModelAdmin):
    list_display = ["signature", "book", "category", "evidence_count", "consistency", "status"]
    list_filter = ["status"]
