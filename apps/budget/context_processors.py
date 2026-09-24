from datetime import date

from django.urls import reverse
from django.utils.functional import SimpleLazyObject

from apps.books.helpers import nav_book_for_member

from .unassigned import OVER_ASSIGNED_LABEL, UNASSIGNED_LABEL, compute_unassigned, pill_context


def unassigned_pill(request):
    """
    The Unassigned figure for the sidebar pill on every app page.

    It follows the nav book (like the Inbox badge) so the pill stays put on the
    account and team pages, and it is always the current month: the pill answers
    "how much has no job right now". The figure is lazy, so a page that never
    renders the pill (marketing pages, auth pages) never pays for the calculation.
    """
    book = nav_book_for_member(request)
    if not book:
        return {}
    return {
        "unassigned_pill": SimpleLazyObject(lambda: pill_context(compute_unassigned(book, date.today()))),
        "unassigned_url": reverse("budget:api_unassigned", args=book.url_args),
        "unassigned_labels": {"unassigned": UNASSIGNED_LABEL, "over_assigned": OVER_ASSIGNED_LABEL},
    }
