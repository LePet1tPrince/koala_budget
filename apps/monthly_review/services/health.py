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
from django.db.models import Count, F, Max, Min, Sum
from django.urls import reverse

from apps.accounts.models import Account
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalLine, counted_entries
from apps.reconciliation.models import Reconciliation

NO_TRANSACTIONS = "no_transactions"
STALE_ACCOUNT = "stale_account"
UNCATEGORIZED = "uncategorized"
UNRECONCILED = "unreconciled"
BALANCE_GAP = "balance_gap"
STATEMENT_DUE = "statement_due"

#: A statement is due once the last one is this old at the end of the month...
STATEMENT_DUE_DAYS = 45
#: ...or, for an account never reconciled, once it has this much history.
FIRST_STATEMENT_AFTER_DAYS = 30


def _stale_days() -> int:
    return getattr(settings, "MONTHLY_REVIEW_STALE_DAYS", 14)


def _opening_balances(team, account_ids, before_date) -> dict:
    """Each account's balance from everything dated before `before_date` -- the
    starting point `balance_change` measures this month's movement against."""
    if not account_ids:
        return {}
    counted = counted_entries("journal_entry__")
    rows = (
        JournalLine.objects.filter(team=team, account_id__in=account_ids, journal_entry__entry_date__lt=before_date)
        .filter(counted)
        .values("account_id")
        .annotate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
    )
    return {row["account_id"]: (row["dr"] or Decimal("0")) - (row["cr"] or Decimal("0")) for row in rows}


def account_health(team, month) -> dict:
    """
    Returns:
        {
          "accounts": [{
              "account": Account,
              "transaction_count": int,        # this month, non-archived
              "uncategorized_count": int,      # posted by month end, non-archived (Inbox definition)
              "unreconciled_count": int,       # posted by month end, categorized + non-archived
              "last_transaction_date": date | None,
              "balance": Decimal,              # as of month end; voided/archived entries excluded
              "reconciled_balance": Decimal,   # as of month end
              "balance_gap": Decimal,
              "balance_change": Decimal,       # this month's net movement (balance - opening balance)
              "account_type": str,             # "asset" | "liability"
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
        # As of month end: reviewing August must not flag what happened in September.
        .with_balance(as_of=month_end)
        .with_reconciled_balance(as_of=month_end)
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
            posted_date__lte=month_end,
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
            posted_date__lte=month_end,
            journal_entry__isnull=False,
            journal_entry__lines__account_id=F("account_id"),
            journal_entry__lines__is_reconciled=False,
        )
        .values("account_id")
        .annotate(count=Count("id"))
        .values_list("account_id", "count")
    )
    last_transaction_dates = dict(
        BankTransaction.objects.filter(
            team=team, account_id__in=account_ids, is_archived=False, posted_date__lte=month_end
        )
        .values("account_id")
        .annotate(latest=Max("posted_date"))
        .values_list("account_id", "latest")
    )
    first_transaction_dates = dict(
        BankTransaction.objects.filter(team=team, account_id__in=account_ids, is_archived=False)
        .values("account_id")
        .annotate(first=Min("posted_date"))
        .values_list("account_id", "first")
    )
    opening_balances = _opening_balances(team, account_ids, month_start)
    last_statement_dates = dict(
        # As of the month's end, like every other check here: reviewing July must
        # not be satisfied by a statement reconciled in September.
        Reconciliation.objects.filter(
            team=team,
            account_id__in=account_ids,
            status=Reconciliation.STATUS_COMPLETED,
            statement_date__lte=month_end,
        )
        .values("account_id")
        .annotate(latest=Max("statement_date"))
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

        if balance_gap != 0 and not any(f["kind"] == UNRECONCILED for f in flags):
            # A gap can exist even with zero unreconciled *bank feed* transactions
            # (e.g. a manual journal entry touching the account) -- surfaced on
            # its own so it is never silently dropped.
            flags.append({"kind": BALANCE_GAP, "account": account, "gap": balance_gap})

        # The reconciliation guarantee only means something if statements are
        # actually checked: flag an account whose last one is old, or one with a
        # month of history that has never been reconciled.
        last_statement = last_statement_dates.get(account.pk)
        first_transaction = first_transaction_dates.get(account.pk)
        if (last_statement and (month_end - last_statement).days > STATEMENT_DUE_DAYS) or (
            last_statement is None
            and first_transaction
            and (month_end - first_transaction).days >= FIRST_STATEMENT_AFTER_DAYS
        ):
            flags.append(
                {
                    "kind": STATEMENT_DUE,
                    "account": account,
                    "last_statement_date": last_statement,
                    "url": reverse("reconciliation:account", args=[team.slug, account.pk]),
                    "hub_url": reverse("reconciliation:hub", args=[team.slug]),
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
                "account_type": account.account_type,
                "flags": flags,
            }
        )
        all_flags.extend(flags)

    return {
        "accounts": result_accounts,
        "flags": all_flags,
        "all_clear": not all_flags,
    }
