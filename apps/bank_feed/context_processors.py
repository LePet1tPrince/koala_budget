from apps.books.helpers import nav_book_for_member

from .services import nav


def nav_feed_accounts(request):
    """
    Bank-feed accounts for the Inbox nav submenu, grouped by institution
    (accounts without one last, under "Other"). Each links straight to
    `bank_feed_home?account=<id>` with that account pre-selected.
    """
    book = nav_book_for_member(request)
    if not book:
        return {}
    return {"nav_feed_institutions": nav.feed_accounts_by_institution(book)}


def inbox_count(request):
    """
    Number of uncategorized bank transactions in the current set of books.

    Powers the badge on the "Inbox" navigation item so users can see at a
    glance how many transactions are waiting for review. It follows the nav
    book rather than `request.book`, so the badge does not blink out on the
    team and account pages, where the URL names no book of its own.
    """
    book = nav_book_for_member(request)
    if not book:
        return {}
    return {"inbox_count": nav.inbox_count(book)}
