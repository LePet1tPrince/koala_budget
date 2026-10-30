"""Linking a bank into a book, and keeping its account list current."""

from .models import PlaidAccount
from .services import account_currency


def add_accounts(item, accounts) -> list[PlaidAccount]:
    """
    Create a PlaidAccount for each of Plaid's `accounts` the item doesn't have yet.

    New accounts start unmapped; the user maps each to a ledger account. Returns
    only the ones created, so update mode can offer just those for mapping.
    """
    known = set(item.accounts.values_list("plaid_account_id", flat=True))
    created = []
    for account in accounts:
        if account["account_id"] in known:
            continue
        created.append(
            PlaidAccount.objects.create(
                book=item.book,
                plaid_account_id=account["account_id"],
                item=item,
                account=None,
                name=account.get("name") or "",
                mask=account.get("mask") or "",
                subtype=str(account.get("subtype") or ""),
                type=str(account.get("type") or ""),
                iso_currency_code=account_currency(account),
            )
        )
    return created
