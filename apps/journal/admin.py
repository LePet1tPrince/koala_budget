from django.contrib import admin

from .models import JournalEntry, JournalLine


class JournalLineInline(admin.TabularInline):
    """Inline admin for JournalLine model."""

    model = JournalLine
    extra = 2
    fields = ["account", "dr_amount", "cr_amount", "is_cleared", "is_reconciled"]
    autocomplete_fields = ["account"]


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    """Admin for JournalEntry model."""

    list_display = [
        "id",
        "entry_date",
        "payee",
        "description_short",
        "status",
        "total_debits",
        "total_credits",
        "is_balanced",
        "team",
    ]
    list_filter = ["status", "source", "entry_date", "team"]
    search_fields = ["description", "payee__name"]
    ordering = ["-entry_date", "-created_at"]
    readonly_fields = ["created_at", "updated_at", "total_debits", "total_credits", "is_balanced"]
    autocomplete_fields = ["payee", "team"]
    date_hierarchy = "entry_date"
    inlines = [JournalLineInline]

    fieldsets = (
        (None, {"fields": ("entry_date", "payee", "description", "status", "source", "team")}),
        (
            "Totals",
            {
                "fields": ("total_debits", "total_credits", "is_balanced"),
                "classes": ("collapse",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def description_short(self, obj):
        """Return shortened description for list display."""
        return obj.description[:50] + "..." if len(obj.description) > 50 else obj.description

    description_short.short_description = "Description"

    def save_formset(self, request, form, formset, change):
        """Save the formset and ensure team is set on all journal lines."""
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, JournalLine):
                # Set team from the parent journal entry
                instance.team = form.instance.team
            instance.save()
        formset.save_m2m()


@admin.register(JournalLine)
class JournalLineAdmin(admin.ModelAdmin):
    """Admin for JournalLine model."""

    list_display = ["id", "journal_entry", "account", "dr_amount", "cr_amount", "is_cleared", "is_reconciled", "team"]
    list_filter = ["is_cleared", "is_reconciled", "team"]
    search_fields = ["journal_entry__description", "account__name"]
    ordering = ["journal_entry", "id"]
    readonly_fields = ["created_at", "updated_at", "amount"]
    autocomplete_fields = ["journal_entry", "account", "team"]

    fieldsets = (
        (None, {"fields": ("journal_entry", "account", "dr_amount", "cr_amount", "amount")}),
        (
            "Status",
            {
                "fields": ("is_cleared", "is_reconciled", "team"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
