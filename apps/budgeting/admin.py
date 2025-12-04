"""
Admin configuration for budgeting app.
"""

from django.contrib import admin

from .models import Account, Budget, Goal, Payee, Transaction


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    """Admin for Account model."""

    list_display = ["account_number", "name", "account_type", "balance", "team", "in_bank_feed"]
    list_filter = ["account_type", "in_bank_feed", "team"]
    search_fields = ["name", "account_number"]
    ordering = ["account_number"]
    readonly_fields = ["balance", "created_at", "updated_at"]


@admin.register(Payee)
class PayeeAdmin(admin.ModelAdmin):
    """Admin for Payee model."""

    list_display = ["name", "team", "created_at"]
    list_filter = ["team"]
    search_fields = ["name"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Admin for Transaction model."""

    list_display = ["date", "payee", "amount", "account", "category", "team"]
    list_filter = ["date", "team"]
    search_fields = ["payee__name", "notes"]
    ordering = ["-date", "-created_at"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "date"
    autocomplete_fields = ["payee", "account", "category"]


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    """Admin for Budget model."""

    list_display = ["month", "category", "budgeted_amount", "actual_amount", "available_amount", "team"]
    list_filter = ["month", "team"]
    search_fields = ["category__name", "category_name"]
    ordering = ["-month", "category__account_number"]
    readonly_fields = ["actual_amount", "available_amount", "category_name", "created_at", "updated_at"]
    date_hierarchy = "month"
    autocomplete_fields = ["category"]


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    """Admin for Goal model."""

    list_display = ["name", "target_amount", "saved_amount", "remaining_amount", "team"]
    list_filter = ["team"]
    search_fields = ["name", "description"]
    ordering = ["name"]
    readonly_fields = ["remaining_amount", "created_at", "updated_at"]
