from django.contrib import admin
from .models import BankTransaction


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    """Admin configuration for BankTransaction model."""

    list_display = [
        "id",
        "account_name",
        "posted_date",
        "description",
        "amount",
        "source",
        "is_categorized",
        "team",
        "created_at",
    ]

    list_filter = ["source", "team", "posted_date"]
    search_fields = [
        "description",
        "merchant_name",
        "plaid_transaction__plaid_transaction_id",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
        "is_categorized",
    ]

    autocomplete_fields = ["team", "journal_entry"]

    date_hierarchy = "posted_date"

    fields = [
        "account",
        "posted_date",
        "description",
        "amount",
        "source",
        "team",
        "journal_entry",  # ✅ now editable
        "is_categorized",
        "is_archived",
    ]

    def account_name(self, obj):
        return obj.account.name if obj.account else None

    account_name.admin_order_field = "account__name"
    account_name.short_description = "Account"

    def is_categorized(self, obj):
        return obj.journal_entry is not None

    is_categorized.boolean = True
    is_categorized.short_description = "Categorized"
