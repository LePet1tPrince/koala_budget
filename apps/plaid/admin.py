"""
Admin configuration for Plaid app.
"""

from django.contrib import admin

from .models import PlaidTransaction, PlaidAccount, PlaidItem


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


@admin.register(PlaidTransaction)
class PlaidTransactionAdmin(admin.ModelAdmin):
    """Admin for PlaidTransaction model."""

    list_display = [
        "bank_transaction_date",
        "bank_transaction_name",
        "bank_transaction_amount",
        "plaid_account",
        "pending",
        "personal_finance_category",
        "team",
    ]
    list_filter = ["pending", "bank_transaction__date", "team", "plaid_account"]
    search_fields = ["plaid_transaction_id", "bank_transaction__name", "personal_finance_category"]
    ordering = ["-bank_transaction__date", "-created_at"]
    readonly_fields = ["plaid_transaction_id", "created_at", "updated_at"]
    autocomplete_fields = ["plaid_account", "team"]
    fields = [
        "plaid_transaction_id",
        "bank_transaction",
        "plaid_account",
        "iso_currency_code",
        "unofficial_currency_code",
        "authorized_date",
        "pending",
        "pending_transaction_id",
        "personal_finance_category",
        "personal_finance_category_id",
        "category_confidence",
        "payment_channel",
        "transaction_type",
        "location",
        "merchant_metadata",
        "team",
        "created_at",
        "updated_at",
    ]

    def bank_transaction_date(self, obj):
        return obj.bank_transaction.date
    bank_transaction_date.admin_order_field = "bank_transaction__date"
    bank_transaction_date.short_description = "Date"

    def bank_transaction_name(self, obj):
        return obj.bank_transaction.name
    bank_transaction_name.admin_order_field = "bank_transaction__name"
    bank_transaction_name.short_description = "Name"

    def bank_transaction_amount(self, obj):
        return obj.bank_transaction.amount
    bank_transaction_amount.admin_order_field = "bank_transaction__amount"
    bank_transaction_amount.short_description = "Amount"
