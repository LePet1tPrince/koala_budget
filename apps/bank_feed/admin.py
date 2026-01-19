"""
Django admin configuration for bank_feed app.
"""

from django.contrib import admin

from .models import BankTransaction


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    """Admin configuration for BankTransaction model."""

    list_display = [
        "id",
        "posted_date",
        "description",
        "amount",
        "source",
        "is_categorized",
        "team",
        "created_at",
    ]
    list_filter = ["source", "team", "posted_date"]
    search_fields = ["description", "merchant_name", "plaid_transaction__plaid_transaction_id"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["team", "journal_entry"]
    date_hierarchy = "posted_date"

    def is_categorized(self, obj):
        """Check if the transaction has been categorized."""
        return obj.journal_entry is not None

    is_categorized.boolean = True
    is_categorized.short_description = "Categorized"