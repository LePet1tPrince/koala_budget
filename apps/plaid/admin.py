"""
Admin configuration for Plaid app.
"""

from django.contrib import admin

from .models import PlaidAccount, PlaidItem, PlaidTransaction


@admin.register(PlaidItem)
class PlaidItemAdmin(admin.ModelAdmin):
    """Admin for PlaidItem model."""

    list_display = ["institution_name", "plaid_item_id", "is_archived", "team", "created_at"]
    list_filter = ["is_archived", "team", "created_at"]
    search_fields = ["institution_name", "plaid_item_id"]
    ordering = ["-created_at"]
    readonly_fields = ["plaid_item_id", "created_at", "updated_at"]
    autocomplete_fields = ["team"]
    fields = [
        "plaid_item_id",
        "institution_name",
        "access_token",
        "cursor",
        "is_archived",
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


@admin.register(PlaidTransaction)
class PlaidTransactionAdmin(admin.ModelAdmin):
    """Admin for PlaidTransaction model."""

    list_display = [
        "bank_transaction__posted_date",
        "bank_transaction__description",
        "bank_transaction__amount",
        "plaid_account",
        "pending",
        "bank_transaction__journal_entry",
        "team",
    ]
    list_filter = ["pending", "bank_transaction__posted_date", "team", "plaid_account"]
    search_fields = ["bank_transaction__description", "bank_transaction__merchant_name", "plaid_transaction_id"]
    ordering = ["-bank_transaction__posted_date", "-created_at"]
    readonly_fields = ["plaid_transaction_id", "created_at", "updated_at"]
    autocomplete_fields = ["plaid_account", "team"]
    fields = [
        "plaid_transaction_id",
        "plaid_account",
        "bank_transaction__amount",
        "iso_currency_code",
        "bank_transaction__posted_date",
        "authorized_date",
        "pending",
        "pending_transaction_id",
        "bank_transaction__description",
        "merchant_name",
        "personal_finance_category",
        "category_confidence",
        "payment_channel",
        "transaction_type",
        "location",
        "merchant_metadata",
        "team",
        "created_at",
        "updated_at",
    ]
