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
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Max, Sum

from apps.accounts.models import Account
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalLine, counted_entries

NO_TRANSACTIONS = "no_transactions"
STALE_ACCOUNT = "stale_account"
UNCATEGORIZED = "uncategorized"
UNRECONCILED = "unreconciled"


def _stale_days() -> int:
    return getattr(settings, "MONTHLY_REVIEW_STALE_DAYS", 14)


def _opening_balances(book, account_ids, before_date) -> dict:
    """Each account's balance from everything dated before `before_date` -- the
    starting point `balance_change` measures this month's movement against."""
    if not account_ids:
        return {}
    counted = counted_entries("journal_entry__")
    rows = (
        JournalLine.objects.filter(book=book, account_id__in=account_ids, journal_entry__entry_date__lt=before_date)
        .filter(counted)
        .values("account_id")
        .annotate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
    )
    return {row["account_id"]: (row["dr"] or Decimal("0")) - (row["cr"] or Decimal("0")) for row in rows}


def account_health(book, month) -> dict:
    """
    Returns:
        {
          "accounts": [{
              "account": Account,
              "transaction_count": int,        # this month: journal entries on the account + uncategorized feed rows
              "uncategorized_count": int,      # posted by month end, non-archived (Inbox definition)
              "unreconciled_count": int,       # this month: journal entries with an unreconciled line on the account
              "last_transaction_date": date | None,
              "balance": Decimal,              # as of month end; voided/archived entries excluded
              "reconciled_balance": Decimal,   # as of month end
              "balance_gap": Decimal,
              "balance_change": Decimal,       # this month's net movement (balance - opening balance)
              "account_type": str,             # "asset" | "liability"
              "institution": str | None,       # institution name, None when unset
              "flags": [{"kind": str, ...}, ...],
          }, ...],
          "flags": [{"kind": str, "account": Account, ...}, ...],  # flattened
          "all_clear": bool,
        }
    """
    month_start = month.replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    accounts = list(
        Account.objects.filter(book=book, has_feed=True, is_system=False)
        .select_related("account_group", "institution")
        # As of month end: reviewing August must not flag what happened in September.
        .with_balance(as_of=month_end)
        .with_reconciled_balance(as_of=month_end)
        .order_by("sort_order", "name")
    )
    account_ids = [a.pk for a in accounts]

    # The month's own activity: journal lines on the account dated in the month,
    # the same set `balance_change` sums. Unreconciled is a subset of it, so the
    # count can never exceed the transaction count.
    month_lines = JournalLine.objects.filter(
        book=book, account_id__in=account_ids, journal_entry__entry_date__range=(month_start, month_end)
    ).filter(counted_entries("journal_entry__"))
    entry_counts = dict(
        month_lines.values("account_id")
        .annotate(count=Count("journal_entry", distinct=True))
        .values_list("account_id", "count")
    )
    unreconciled_counts = dict(
        month_lines.filter(is_reconciled=False)
        .values("account_id")
        .annotate(count=Count("journal_entry", distinct=True))
        .values_list("account_id", "count")
    )
    # Uncategorized feed rows have no journal line yet but are still this month's transactions.
    uncategorized_this_month = dict(
        BankTransaction.objects.filter(
            book=book,
            account_id__in=account_ids,
            journal_entry__isnull=True,
            is_archived=False,
            posted_date__range=(month_start, month_end),
        )
        .values("account_id")
        .annotate(count=Count("id"))
        .values_list("account_id", "count")
    )
    uncategorized_counts = dict(
        BankTransaction.objects.filter(
            book=book,
            account_id__in=account_ids,
            journal_entry__isnull=True,
            is_archived=False,
            posted_date__lte=month_end,
        )
        .values("account_id")
        .annotate(count=Count("id"))
        .values_list("account_id", "count")
    )
    last_transaction_dates = dict(
        BankTransaction.objects.filter(
            book=book, account_id__in=account_ids, is_archived=False, posted_date__lte=month_end
        )
        .values("account_id")
        .annotate(latest=Max("posted_date"))
        .values_list("account_id", "latest")
    )
    opening_balances = _opening_balances(book, account_ids, month_start)

    stale_days = _stale_days()
    result_accounts = []
    all_flags = []

    for account in accounts:
        transaction_count = entry_counts.get(account.pk, 0) + uncategorized_this_month.get(account.pk, 0)
        uncategorized_count = uncategorized_counts.get(account.pk, 0)
        unreconciled_count = unreconciled_counts.get(account.pk, 0)
        last_transaction_date = last_transaction_dates.get(account.pk)
        balance = account._balance
        reconciled_balance = account._reconciled_balance
        balance_gap = balance - reconciled_balance
        balance_change = balance - opening_balances.get(account.pk, Decimal("0"))

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
                "balance_change": balance_change,
                "account_type": account.account_group.account_type,
                "institution": account.institution.name if account.institution else None,
                "flags": flags,
            }
        )
        all_flags.extend(flags)

    return {
        "accounts": result_accounts,
        "flags": all_flags,
        "all_clear": not all_flags,
    }
