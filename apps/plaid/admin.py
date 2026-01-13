"""
Admin configuration for Plaid app.
"""

from django.contrib import admin

from .models import ImportedTransaction, PlaidAccount, PlaidItem


@admin.register(PlaidItem)
class PlaidItemAdmin(admin.ModelAdmin):
    """Admin for PlaidItem model."""

    list_display = ["institution_name", "plaid_item_id", "is_active", "team", "created_at"]
    list_filter = ["is_active", "team", "created_at"]
    search_fields = ["institution_name", "plaid_item_id"]
    ordering = ["-created_at"]
    readonly_fields = ["plaid_item_id", "created_at", "updated_at"]
    autocomplete_fields = ["team"]
    fields = [
        "plaid_item_id",
        "institution_name",
        "access_token",
        "cursor",
        "is_active",
        "team",
        "created_at",
        "updated_at",
    ]


@admin.register(PlaidAccount)
class PlaidAccountAdmin(admin.ModelAdmin):
    """Admin for PlaidAccount model."""

    list_display = ["name", "mask", "type", "subtype", "account", "item", "team"]
    list_filter = ["type", "subtype", "team", "created_at"]
    search_fields = ["name", "plaid_account_id", "mask"]
    ordering = ["name"]
    readonly_fields = ["plaid_account_id", "created_at", "updated_at"]
    autocomplete_fields = ["item", "account", "team"]
    fields = [
        "plaid_account_id",
        "item",
        "account",
        "name",
        "mask",
        "type",
        "subtype",
        "team",
        "created_at",
        "updated_at",
    ]


@admin.register(ImportedTransaction)
class ImportedTransactionAdmin(admin.ModelAdmin):
    """Admin for ImportedTransaction model."""

    list_display = [
        "date",
        "name",
        "amount",
        "plaid_account",
        "pending",
        "journal_entry",
        "team",
    ]
    list_filter = ["pending", "date", "team", "plaid_account"]
    search_fields = ["name", "merchant_name", "plaid_transaction_id"]
    ordering = ["-date", "-created_at"]
    readonly_fields = ["plaid_transaction_id", "raw", "created_at", "updated_at"]
    autocomplete_fields = ["plaid_account", "journal_entry", "team"]
    fields = [
        "plaid_transaction_id",
        "plaid_account",
        "amount",
        "iso_currency_code",
        "date",
        "authorized_date",
        "pending",
        "pending_transaction_id",
        "name",
        "merchant_name",
        "personal_finance_category",
        "category_confidence",
        "payment_channel",
        "transaction_type",
        "location",
        "merchant_metadata",
        "journal_entry",
        "team",
        "raw",
        "created_at",
        "updated_at",
    ]

