"""
The bank-feed figures in the app chrome: the Inbox badge and its account submenu.

One copy, read by the context processors (server-rendered sidebar) and by the
nav-state API (`apps.api.views.NavStateView`, the phone app and React chrome).
"""

from apps.accounts.models import ACCOUNT_TYPE_ASSET, Account

from ..models import BankTransaction


def inbox_count(book) -> int:
    """Uncategorized, unvoided bank transactions in `book`'s visible accounts: the Inbox badge."""
    return BankTransaction.objects.filter(
        book=book,
        journal_entry__isnull=True,
        is_void=False,
        account__is_hidden=False,
    ).count()


def feed_accounts_by_institution(book) -> list[dict]:
    """
    `book`'s visible bank-feed accounts grouped by institution, for the Inbox submenu:
    `[{"name": <institution name or None>, "accounts": [Account, ...]}, ...]`.

    Institutions sort by name, accounts without one last (the "Other" group, whose
    `name` is None). Each account carries `is_bank_account` (an asset account, as
    opposed to a credit card or other liability), which picks its icon.
    """
    feed_accounts = (
        Account.objects.filter(book=book, has_feed=True, is_hidden=False)
        .select_related("account_group", "institution")
        .order_by("account_group__account_type", "account_group__sort_order", "sort_order", "name")
    )
    groups = {}
    for account in feed_accounts:
        account.is_bank_account = account.account_group.account_type == ACCOUNT_TYPE_ASSET
        name = account.institution.name if account.institution else None
        groups.setdefault(name, []).append(account)
    ordered = sorted(groups.items(), key=lambda item: (item[0] is None, (item[0] or "").lower()))
    return [{"name": name, "accounts": accounts} for name, accounts in ordered]
