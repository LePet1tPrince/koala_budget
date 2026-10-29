from django.contrib import admin

from .models import Goal


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    """Register Goal model with the admin."""

    list_display = ["name", "target_amount", "target_date", "is_complete", "is_archived", "book"]
    list_filter = ["is_complete", "is_archived", "book"]
    search_fields = ["name"]
    ordering = ["order", "target_date", "name"]
