from django.contrib import admin

from .models import Account, AccountGroup, Payee


@admin.register(AccountGroup)
class AccountGroupAdmin(admin.ModelAdmin):
    """Admin for AccountGroup model."""

    list_display = ["name", "account_type", "book"]
    list_filter = ["account_type", "book"]
    search_fields = ["name"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["book"]
    fields = ["name", "account_type", "description", "book", "created_at", "updated_at"]


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    """Admin for Account model."""

    list_display = ["name", "account_group", "book"]
    list_filter = ["account_group", "book"]
    search_fields = ["name"]
    ordering = ["name"]
    readonly_fields = ["balance", "created_at", "updated_at"]
    autocomplete_fields = ["account_group", "book"]
    fields = ["name", "account_group", "has_feed", "balance", "book", "created_at", "updated_at"]


@admin.register(Payee)
class PayeeAdmin(admin.ModelAdmin):
    """Admin for Payee model."""

    list_display = ["name", "book", "created_at"]
    list_filter = ["book"]
    search_fields = ["name"]
    ordering = ["name"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["book"]
    fields = ["name", "book", "created_at", "updated_at"]
