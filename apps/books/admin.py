from django.contrib import admin

from .models import Book


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "team", "budget_future_income", "is_archived", "created_at"]
    list_filter = ["is_archived", "budget_future_income"]
    search_fields = ["name", "slug", "team__name", "team__slug"]
    autocomplete_fields = ["team"]
