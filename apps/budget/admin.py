from django.contrib import admin

from .models import Budget

@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    """Register Budget model with the admin."""

    list_display = ["month", "category", "budget_amount", "team"]
    list_filter = ["team"]
    search_fields = ["category__name"]
    ordering = ["month", "category"]
