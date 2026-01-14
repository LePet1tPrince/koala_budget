from django.contrib import admin

from .models import Goal


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    """Register Budget model with the admin."""

    list_display = ["name", "goal_amount", "target_date", "saved_amount", "team"]
    list_filter = ["team"]
    search_fields = ["name"]
    ordering = ["name"]