from django.contrib import admin

from .models import Account, AccountGroup, Payee


@admin.register(AccountGroup)
class AccountGroupAdmin(admin.ModelAdmin):
    """Admin for AccountGroup model."""

    list_display = ["name", "account_type", "team"]
    list_filter = ["account_type", "team"]
    search_fields = ["name"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["team"]
    fields = ["name", "account_type", "description", "team", "created_at", "updated_at"]


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    """Admin for Account model."""

    list_display = ["account_number", "name", "account_group", "team"]
    list_filter = ["account_group", "team"]
    search_fields = ["name", "account_number"]
    ordering = ["account_number"]
    readonly_fields = ["balance", "created_at", "updated_at"]
    autocomplete_fields = ["account_group", "team"]
    fields = ["account_number", "name", "account_group", "has_feed", "balance", "team", "created_at", "updated_at"]


@admin.register(Payee)
class PayeeAdmin(admin.ModelAdmin):
    """Admin for Payee model."""

    list_display = ["name", "team", "created_at"]
    list_filter = ["team"]
    search_fields = ["name"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["team"]
    fields = ["name", "team", "created_at", "updated_at"]
