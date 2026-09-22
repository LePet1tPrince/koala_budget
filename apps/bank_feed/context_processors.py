from apps.accounts.models import ACCOUNT_TYPE_ASSET, Account
from apps.teams.helpers import get_nav_team

from .models import BankTransaction


def nav_feed_accounts(request):
    """
    Bank-feed accounts for the Inbox nav submenu, split into bank accounts
    (assets) and credit cards (liabilities) so each links straight to
    `bank_feed_home?account=<id>` with that account pre-selected.
    """
    team = get_nav_team(request)
    if not team or not request.user.is_authenticated:
        return {}
    feed_accounts = list(
        Account.objects.filter(team=team, has_feed=True)
        .select_related("account_group")
        .order_by("account_group__account_type", "account_group__sort_order", "sort_order", "name")
    )
    return {
        "nav_bank_accounts": [a for a in feed_accounts if a.account_group.account_type == ACCOUNT_TYPE_ASSET],
        "nav_credit_cards": [a for a in feed_accounts if a.account_group.account_type != ACCOUNT_TYPE_ASSET],
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
