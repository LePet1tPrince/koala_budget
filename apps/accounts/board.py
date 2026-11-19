"""
The drag-and-drop chart-of-accounts board: what it shows and how it is reordered.

`board_sections` builds the board's payload (type sections -> groups -> account
rows); the board API serves it and `AccountsBoardViewSet` writes through the
other functions here. Rows carry ids, never URLs: the frontend builds links from
the page's `book-base`.
"""

from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from .models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_BUDGET,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from .validators import default_has_feed

# Display order and section labels for the chart-of-accounts board
ACCOUNT_TYPE_ORDER = [
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_LIABILITY,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_EQUITY,
]
ACCOUNT_TYPE_SECTION_LABELS = {
    ACCOUNT_TYPE_ASSET: _("Assets"),
    ACCOUNT_TYPE_LIABILITY: _("Liabilities"),
    ACCOUNT_TYPE_INCOME: _("Income"),
    ACCOUNT_TYPE_EXPENSE: _("Expenses"),
    ACCOUNT_TYPE_EQUITY: _("Goals"),
}

# Display-only section for equity-type groups that hold no goal (opening balances).
SECTION_EQUITY = "equity"


def account_row(account, goal_left=None):
    """
    One account as the board shows it.

    A goal account shows what the goal has `left`, not its raw ledger balance:
    its ledger holds only the spending, while its claim is allocations - spending.
    An income account's balance is credit-normal, so it is shown cr - dr: a salary
    reads positive.
    """
    if goal_left is not None:
        balance = goal_left
    elif account.account_group.account_type == ACCOUNT_TYPE_INCOME:
        balance = -account.balance
    else:
        balance = account.balance
    return {
        "id": account.pk,
        "name": account.name,
        "balance": balance,
        "is_goal": goal_left is not None,
        "institution_id": account.institution_id,
        "institution_name": account.institution.name if account.institution_id else None,
        "is_hidden": account.is_hidden,
        "is_system": account.is_system,
    }


def group_row(group, accounts=None):
    """One group card: the group and its account rows, in board order."""
    return {
        "id": group.pk,
        "name": group.name,
        "account_type": group.account_type,
        "is_system": group.is_system,
        "accounts": accounts if accounts is not None else [],
    }


def board_sections(book):
    """
    The board: one section per account type in balance-sheet order, then plain
    equity. Budget buckets and the budget group belong to the app and are left out.
    """
    from apps.budget.models import GOALS_GROUP_NAME
    from apps.budget.services import goal_left_by_account

    goal_left = goal_left_by_account(book)
    accounts_by_group = {}
    accounts = (
        Account.objects.filter(book=book)
        .exclude_budget_buckets()
        .with_balance()
        .select_related("institution", "account_group")
        .order_by("sort_order", "name")
    )
    for account in accounts:
        accounts_by_group.setdefault(account.account_group_id, []).append(
            account_row(account, goal_left.get(account.pk))
        )

    # The equity type is stored as "goal" but also holds plain equity (opening
    # balances), so it is shown as two sections: groups holding goals, and the rest.
    sections = {account_type: [] for account_type in (*ACCOUNT_TYPE_ORDER, SECTION_EQUITY)}
    groups = (
        AccountGroup.objects.filter(book=book).exclude(account_type=ACCOUNT_TYPE_BUDGET).order_by("sort_order", "name")
    )
    for group in groups:
        accounts_in_group = accounts_by_group.get(group.pk, [])
        key = group.account_type
        if key == ACCOUNT_TYPE_EQUITY and not (
            any(a["is_goal"] for a in accounts_in_group) or (group.name == GOALS_GROUP_NAME and not group.is_system)
        ):
            key = SECTION_EQUITY
        sections[key].append(group_row(group, accounts_in_group))

    result = [
        {
            "key": account_type,
            "account_type": account_type,
            "label": str(ACCOUNT_TYPE_SECTION_LABELS[account_type]),
            # Goals are created on the Goals page, which makes their account.
            "creates_goals": account_type == ACCOUNT_TYPE_EQUITY,
            "groups": sections[account_type],
        }
        for account_type in ACCOUNT_TYPE_ORDER
    ]
    result.append(
        {
            "key": SECTION_EQUITY,
            "account_type": ACCOUNT_TYPE_EQUITY,
            "label": str(_("Equity")),
            "creates_goals": False,
            "groups": sections[SECTION_EQUITY],
        }
    )
    return result


def apply_account_order(accounts, placements):
    """
    Persist the board's account order: `placements` is {account: (group, position)}.
    Returns how many accounts moved to another group. All-or-nothing.
    """
    moved = 0
    for account, (group, position) in placements.items():
        if account.account_group_id != group.pk:
            moved += 1
        account.account_group = group
        account.sort_order = position
    with transaction.atomic():
        Account.objects.bulk_update(list(placements), ["account_group", "sort_order"], batch_size=500)
    return moved


def apply_group_order(groups):
    """Persist one type's group order: `groups` in their new order."""
    for position, group in enumerate(groups):
        group.sort_order = position
    with transaction.atomic():
        AccountGroup.objects.bulk_update(groups, ["sort_order"], batch_size=500)


def next_account_sort_order(book, group):
    """The position after the last account in `group`: a new account goes at the bottom."""
    last = Account.objects.filter(book=book, account_group=group).aggregate(m=Max("sort_order"))["m"]
    return 0 if last is None else last + 1


def next_group_sort_order(book, account_type):
    """The position after the last group of `account_type`."""
    last = AccountGroup.objects.filter(book=book, account_type=account_type).aggregate(m=Max("sort_order"))["m"]
    return 0 if last is None else last + 1


def create_account(book, name, group):
    """An account at the bottom of `group`, with a feed if it is an asset or liability."""
    with transaction.atomic():
        return Account.objects.create(
            book=book,
            name=name,
            account_group=group,
            has_feed=default_has_feed(group.account_type),
            sort_order=next_account_sort_order(book, group),
        )


def create_group(book, name, account_type):
    """A group at the bottom of its type's section."""
    with transaction.atomic():
        return AccountGroup.objects.create(
            book=book,
            name=name,
            account_type=account_type,
            sort_order=next_group_sort_order(book, account_type),
        )
