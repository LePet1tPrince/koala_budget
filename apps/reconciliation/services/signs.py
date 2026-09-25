"""
The one place a sign is flipped.

The ledger stores every balance as dr - cr, so a credit card owing $1,234.56
holds -1,234.56. A statement prints the card's balance as 1,234.56. The server
computes in ledger sign and the API and page speak statement sign; these two
functions are the whole of the conversion, and nothing else negates an amount.
"""

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY

RECONCILABLE_TYPES = (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)


def account_type(account) -> str:
    return account.account_group.account_type


def is_liability(account) -> bool:
    return account_type(account) == ACCOUNT_TYPE_LIABILITY


def is_reconcilable(account) -> bool:
    """Assets and liabilities hold a balance a statement can confirm; system accounts are bookkeeping."""
    return account_type(account) in RECONCILABLE_TYPES and not account.is_system


def to_statement(account, ledger_amount):
    """Ledger sign (dr - cr) -> the sign printed on the account's statement."""
    return -ledger_amount if is_liability(account) else ledger_amount


def to_ledger(account, statement_amount):
    """The sign printed on the statement -> ledger sign (dr - cr)."""
    return -statement_amount if is_liability(account) else statement_amount
