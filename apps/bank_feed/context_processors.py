from apps.accounts.models import ACCOUNT_TYPE_ASSET, Account
from apps.teams.helpers import get_nav_team

from .models import BankTransaction


def nav_feed_accounts(request):
    """
    Bank-feed accounts for the Inbox nav submenu, grouped by institution
    (accounts without one last, under "Other"). Each links straight to
    `bank_feed_home?account=<id>` with that account pre-selected, and shows its
    balance in the same ledger sign as the feed's account cards (dr - cr, so a
    credit card owing money reads negative).

    `nav_feed_account_id` is the account the feed page opened on, so its
    sub-item is shaded on first paint; the feed updates it as the user switches
    accounts in the page.
    """
    team = get_nav_team(request)
    if not team or not request.user.is_authenticated:
        return {}
    feed_accounts = (
        Account.objects.filter(team=team, has_feed=True)
        .with_balance()
        .select_related("account_group", "institution")
        .order_by("account_group__account_type", "account_group__sort_order", "sort_order", "name")
    )
    groups = {}
    for account in feed_accounts:
        account.is_bank_account = account.account_group.account_type == ACCOUNT_TYPE_ASSET
        name = account.institution.name if account.institution else None
        groups.setdefault(name, []).append(account)
    ordered = sorted(groups.items(), key=lambda item: (item[0] is None, (item[0] or "").lower()))
    selected = request.GET.get("account", "")
    match = getattr(request, "resolver_match", None)
    on_feed = match is not None and match.view_name == "bank_feed:bank_feed_home"
    return {
        "nav_feed_institutions": [{"name": name, "accounts": accounts} for name, accounts in ordered],
        "nav_feed_account_id": int(selected) if on_feed and selected.isdigit() else None,
    }


def inbox_count(request):
    """
    Number of uncategorized bank transactions for the current team.

    Powers the badge on the "Inbox" navigation item so users can see at a
    glance how many transactions are waiting for review. It follows the nav
    team rather than `request.team`, so the badge does not blink out on the
    account pages where the nav itself has no team of its own.
    """
    # request.team is a SimpleLazyObject that may wrap None; truthiness unwraps it
    team = get_nav_team(request)
    if not team or not request.user.is_authenticated:
        return {}
    return {
        "inbox_count": BankTransaction.objects.filter(
            team=team,
            journal_entry__isnull=True,
            is_archived=False,
        ).count()
    }
