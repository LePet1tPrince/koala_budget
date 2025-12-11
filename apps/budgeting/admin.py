"""
Admin configuration for budgeting app.
"""

from django.contrib import admin

from .models import Account, AccountType, Budget, Goal, Payee, Transaction


@admin.register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    """Admin for AccountType model."""

    list_display = ["type_name", "subtype_name", "team"]
    list_filter = ["type_name", "team"]
    search_fields = ["type_name", "subtype_name"]
    ordering = ["type_name", "subtype_name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    """Admin for Account model."""

    list_display = ["account_number", "name", "account_type", "subtype", "has_feed", "team"]
    list_filter = ["account_type", "subtype", "has_feed", "team"]
    search_fields = ["name", "account_number"]
    ordering = ["account_number"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["account_type", "subtype"]


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

    list_display = ["date_posted", "payee", "amount", "account", "category", "status", "is_cleared", "team"]
    list_filter = ["date_posted", "status", "is_cleared", "is_reconciled", "import_method", "team"]
    search_fields = ["payee__name", "notes"]
    ordering = ["-date_posted", "-created_at"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "date_posted"
    autocomplete_fields = ["payee", "account", "category"]


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    """Admin for Budget model."""

    list_display = ["month", "category", "budget", "team"]
    list_filter = ["month", "team"]
    search_fields = ["category__name"]
    ordering = ["-month", "category__account_number"]
    readonly_fields = ["created_at", "updated_at"]
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
