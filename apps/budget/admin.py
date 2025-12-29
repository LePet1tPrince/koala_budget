from django.contrib import admin

from .models import Budget

@admin.register(Budget)
class JournalEntryAdmin(admin.ModelAdmin):
    """Register Budget model with the admin."""

    list_display = ["month", "category", "budget_amount", "actual_amount", "available", "team"]
    list_filter = ["team"]
    search_fields = ["category__name"]
    ordering = ["month", "category"]
    readonly_fields = ["actual_amount", "available"]