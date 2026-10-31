"""
The accounts the Inbox shows, and the account groups its pickers offer.

`feed_accounts` is what both the page and the `feed_accounts` endpoint list: every
account on a feed that isn't hidden, in board order, with its balances and the
review facts its card shows. `create_category_account` is the CSV wizard's
"create a category" step.
"""

from django.db.models import Count, F, Max

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_BUDGET,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from apps.reconciliation.models import Reconciliation
from apps.reconciliation.services.integrity import intact_map

from ..models import BankTransaction
from .errors import FeedError


def feed_accounts(book):
    """Every account on a feed that isn't hidden, in board order, with balances and review facts."""
    accounts = list(
        Account.objects.filter(book=book, has_feed=True, is_hidden=False)
        .with_balance()
        .with_reconciled_balance()
        .select_related("account_group", "institution")
        .order_by("account_group__account_type", "account_group__sort_order", "sort_order", "name")
    )
    annotate_activity(accounts, book)
    return accounts


def annotate_activity(accounts, book):
    """
    Attach per-account review/activity fields to feed accounts: uncategorized_count,
    latest_transaction_date, latest_reconciled_date, last_statement_date, last_statement_intact.

    Computed as separate queries (not chained onto the with_balance()/with_reconciled_balance()
    annotations) to avoid the join fan-out that would inflate the Sum()
    balances: bank_transactions and journal_lines are different reverse relations, so annotating
    both in one query would cross-multiply their rows per account.
    """
    uncategorized_counts = dict(
        BankTransaction.objects.filter(
            book=book,
            account__has_feed=True,
            account__is_hidden=False,
            journal_entry__isnull=True,
            is_void=False,
        )
        .values("account_id")
        .annotate(count=Count("id"))
        .values_list("account_id", "count")
    )
    latest_transaction_dates = dict(
        BankTransaction.objects.filter(
            book=book,
            account__has_feed=True,
            account__is_hidden=False,
            is_void=False,
        )
        .values("account_id")
        .annotate(latest_date=Max("posted_date"))
        .values_list("account_id", "latest_date")
    )
    latest_reconciled_dates = dict(
        BankTransaction.objects.filter(
            book=book,
            account__has_feed=True,
            account__is_hidden=False,
            is_void=False,
            journal_entry__isnull=False,
            journal_entry__lines__account_id=F("account_id"),
            journal_entry__lines__is_reconciled=True,
        )
        .distinct("account_id")
        .order_by("account_id", "-posted_date")
        .values_list("account_id", "posted_date")
    )
    # The last finished statement per account and whether it still holds, so a
    # card can say "Reconciled through Aug 31" (and warn when that changed).
    last_statements = {}
    for rec in Reconciliation.objects.filter(book=book, status=Reconciliation.STATUS_COMPLETED).order_by(
        "account_id", "-statement_date", "-id"
    ):
        last_statements.setdefault(rec.account_id, rec)
    intact = intact_map(list(last_statements.values()))

    for account in accounts:
        account.uncategorized_count = uncategorized_counts.get(account.id, 0)
        account.latest_transaction_date = latest_transaction_dates.get(account.id)
        account.latest_reconciled_date = latest_reconciled_dates.get(account.id)
        statement = last_statements.get(account.id)
        account.last_statement_date = statement.statement_date if statement else None
        account.last_statement_intact = intact.get(statement.id) if statement else None


def category_groups(book):
    """The account groups a new account can go in: every group but the budget buckets' system one."""
    return AccountGroup.objects.filter(book=book).exclude(account_type=ACCOUNT_TYPE_BUDGET)


def create_category_account(book, name, account_group_id):
    """
    Create an account from the CSV wizard's category step, at the end of its group.

    Names are unique per book whatever the case, as the accounts board enforces;
    an asset or liability account starts on a feed. Raises `FeedError`.
    """
    name = (name or "").strip()
    if not name:
        raise FeedError("name is required")
    if not account_group_id:
        raise FeedError("account_group_id is required")
    try:
        account_group = category_groups(book).get(id=account_group_id)
    except AccountGroup.DoesNotExist:
        raise FeedError.not_found("Account group not found") from None
    if Account.objects.filter(book=book).exclude_budget_buckets().filter(name__iexact=name).exists():
        raise FeedError(f'An account named "{name}" already exists')
    return Account.objects.create(
        name=name,
        account_group=account_group,
        book=book,
        has_feed=account_group.account_type in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY),
    )
