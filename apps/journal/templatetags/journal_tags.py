from django import template

from apps.journal.models import JournalEntry, counted_entries

register = template.Library()


@register.simple_tag
def first_entry_date(book):
    """The book's earliest counted entry date as yyyy-MM-dd ("" when empty) -- the start of an "All time" range."""
    if book is None:
        return ""
    first = (
        JournalEntry.objects.filter(book=book)
        .filter(counted_entries())
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    return first.isoformat() if first else ""
