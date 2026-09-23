"""
Step 1 of the guided monthly review: is this month's data trustworthy?

Computed per feed account, following the same fan-out-safe three-query pattern
as `apps.bank_feed.views._annotate_feed_account_activity` (separate queries
rather than chained annotations, since bank_transactions and journal_lines are
different reverse relations and chaining them cross-multiplies the Sum()s).

This step never blocks the walkthrough -- it only produces facts. Turning a
fact into a warning, with copy and severity, is `services/insights.py`'s job.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, F, Max

from apps.accounts.models import Account
from apps.bank_feed.models import BankTransaction

NO_TRANSACTIONS = "no_transactions"
STALE_ACCOUNT = "stale_account"
UNCATEGORIZED = "uncategorized"
UNRECONCILED = "unreconciled"
BALANCE_GAP = "balance_gap"


def _stale_days() -> int:
    return getattr(settings, "MONTHLY_REVIEW_STALE_DAYS", 14)


def account_health(team, month) -> dict:
    """
    Returns:
        {
          "accounts": [{
              "account": Account,
              "transaction_count": int,        # this month, non-archived
              "uncategorized_count": int,      # all time, non-archived (Inbox definition)
              "unreconciled_count": int,       # all time, categorized + non-archived
              "last_transaction_date": date | None,
              "balance": Decimal,
              "reconciled_balance": Decimal,
              "balance_gap": Decimal,  # gap over reconcilable (bank-feed-backed) lines only
              "flags": [{"kind": str, ...}, ...],
          }, ...],
          "flags": [{"kind": str, "account": Account, ...}, ...],  # flattened
          "all_clear": bool,
        }
    """
    month_start = month.replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    accounts = list(
        Account.objects.filter(team=team, has_feed=True, is_system=False)
        .select_related("account_group")
        .with_balance()
        .with_reconciled_balance()
        .with_reconcilable_balance()
        .order_by("sort_order", "name")
    )
    account_ids = [a.pk for a in accounts]

    this_month_counts = dict(
        BankTransaction.objects.filter(
            team=team,
            account_id__in=account_ids,
            is_archived=False,
            posted_date__range=(month_start, month_end),
        )
        .values("account_id")
        .annotate(count=Count("id"))
        .values_list("account_id", "count")
    )
    uncategorized_counts = dict(
        BankTransaction.objects.filter(
            team=team,
            account_id__in=account_ids,
            journal_entry__isnull=True,
            is_archived=False,
        )
        .values("account_id")
        .annotate(count=Count("id"))
        .values_list("account_id", "count")
    )
    unreconciled_counts = dict(
        BankTransaction.objects.filter(
            team=team,
            account_id__in=account_ids,
            is_archived=False,
            journal_entry__isnull=False,
            journal_entry__lines__account_id=F("account_id"),
            journal_entry__lines__is_reconciled=False,
        )
        .values("account_id")
        .annotate(count=Count("id"))
        .values_list("account_id", "count")
    )
    last_transaction_dates = dict(
        BankTransaction.objects.filter(team=team, account_id__in=account_ids, is_archived=False)
        .values("account_id")
        .annotate(latest=Max("posted_date"))
        .values_list("account_id", "latest")
    )

    stale_days = _stale_days()
    result_accounts = []
    all_flags = []

    for account in accounts:
        transaction_count = this_month_counts.get(account.pk, 0)
        uncategorized_count = uncategorized_counts.get(account.pk, 0)
        unreconciled_count = unreconciled_counts.get(account.pk, 0)
        last_transaction_date = last_transaction_dates.get(account.pk)
        balance = account._balance
        reconciled_balance = account._reconciled_balance
        # Gap over lines the user could ever reconcile (backed by a live bank feed
        # transaction) -- a manual entry or opening balance moves `balance` without
        # ever being reconcilable, so it must not read as a permanent gap.
        balance_gap = account._reconcilable_balance - reconciled_balance

        flags = []
        if transaction_count == 0:
            flags.append({"kind": NO_TRANSACTIONS, "account": account})
        elif last_transaction_date and (month_end - last_transaction_date).days > stale_days:
            flags.append(
                {
                    "kind": STALE_ACCOUNT,
                    "account": account,
                    "last_transaction_date": last_transaction_date,
                    "days": (month_end - last_transaction_date).days,
                }
            )

        if uncategorized_count:
            flags.append({"kind": UNCATEGORIZED, "account": account, "count": uncategorized_count})

        if unreconciled_count:
            flags.append(
                {
                    "kind": UNRECONCILED,
                    "account": account,
                    "count": unreconciled_count,
                    "gap": balance_gap,
                }
            )

        if balance_gap != 0 and not any(f["kind"] == UNRECONCILED for f in flags):
            # A gap can exist even with zero unreconciled *bank feed* transactions
            # (e.g. a manual journal entry touching the account) -- surfaced on
            # its own so it is never silently dropped.
            flags.append({"kind": BALANCE_GAP, "account": account, "gap": balance_gap})

        result_accounts.append(
            {
                "account": account,
                "transaction_count": transaction_count,
                "uncategorized_count": uncategorized_count,
                "unreconciled_count": unreconciled_count,
                "last_transaction_date": last_transaction_date,
                "balance": balance,
                "reconciled_balance": reconciled_balance,
                "balance_gap": balance_gap,
                "flags": flags,
            }
        )
        all_flags.extend(flags)

    return {
        "accounts": result_accounts,
        "flags": all_flags,
        "all_clear": not all_flags,
    }
