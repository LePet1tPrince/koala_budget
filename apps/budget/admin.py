from django.contrib import admin

from .models import Budget, Goal, GoalAllocation


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    """Register Budget model with the admin."""

    list_display = ["month", "category", "budget_amount", "team"]
    list_filter = ["team"]
    search_fields = ["category__name"]
    ordering = ["month", "category"]


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    """Register Goal model with the admin."""

    list_display = ["name", "target_amount", "target_date", "is_complete", "is_archived", "team"]
    list_filter = ["is_complete", "is_archived", "team"]
    search_fields = ["name"]
    ordering = ["order", "target_date", "name"]


@admin.register(GoalAllocation)
class GoalAllocationAdmin(admin.ModelAdmin):
    """Register GoalAllocation model with the admin."""

    list_display = ["goal", "month", "amount", "team"]
    list_filter = ["month", "team"]
    search_fields = ["goal__name"]
    ordering = ["-month"]
