from apps.accounts.models import ACCOUNT_TYPE_ASSET, Account
from apps.books.helpers import nav_book_for_member

from .models import BankTransaction


def nav_feed_accounts(request):
    """
    Bank-feed accounts for the Inbox nav submenu, grouped by institution
    (accounts without one last, under "Other"). Each links straight to
    `bank_feed_home?account=<id>` with that account pre-selected.
    """
    book = nav_book_for_member(request)
    if not book:
        return {}
    feed_accounts = (
        Account.objects.filter(book=book, has_feed=True)
        .select_related("account_group", "institution")
        .order_by("account_group__account_type", "account_group__sort_order", "sort_order", "name")
    )
    groups = {}
    for account in feed_accounts:
        account.is_bank_account = account.account_group.account_type == ACCOUNT_TYPE_ASSET
        name = account.institution.name if account.institution else None
        groups.setdefault(name, []).append(account)
    ordered = sorted(groups.items(), key=lambda item: (item[0] is None, (item[0] or "").lower()))
    return {"nav_feed_institutions": [{"name": name, "accounts": accounts} for name, accounts in ordered]}


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
    return {
        "inbox_count": BankTransaction.objects.filter(
            book=book,
            journal_entry__isnull=True,
            is_archived=False,
        ).count()
    }
