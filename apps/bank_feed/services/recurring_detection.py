"""
Spotting transactions that look recurring, so the bank feed can offer to make
them a schedule.

A suggestion is a run of transactions in one account, to the same payee, in the
same direction, at a regular interval and a similar amount, that is still
going. Nothing here writes; `RecurringTransaction` rows are made only when the
user accepts a suggestion (`recurring.create_rule_from_transaction`).

What counts, in order of the checks below:

* the same account, direction (in/out) and payee -- the payee name, or the
  description when there is none, lowercased with digits and punctuation removed,
  so "NETFLIX.COM 8812" and "Netflix.com 9921" are one payee;
* at least `MIN_OCCURRENCES` on different days within `LOOKBACK_DAYS`;
* every gap between them within a period's tolerance (`PERIODS`);
* every amount within `AMOUNT_TOLERANCE` of the latest one;
* the latest no older than one period plus its tolerance (a cancelled
  subscription stops being suggested);
* no live schedule for that account and payee, and not dismissed by the user.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from django.utils import timezone

from apps.accounts.models import Account

from ..models import BankTransaction, RecurringSuggestionDismissal, RecurringTransaction
from .recurring import describe, following

LOOKBACK_DAYS = 400
MIN_OCCURRENCES = 3
AMOUNT_TOLERANCE = Decimal("0.20")


@dataclass(frozen=True)
class Period:
    """A schedule shape a run of gaps can match."""

    days: int
    tolerance: int
    frequency: str
    interval: int


PERIODS = [
    Period(7, 1, RecurringTransaction.FREQUENCY_WEEKLY, 1),
    Period(14, 2, RecurringTransaction.FREQUENCY_WEEKLY, 2),
    Period(30, 4, RecurringTransaction.FREQUENCY_MONTHLY, 1),
    Period(91, 7, RecurringTransaction.FREQUENCY_MONTHLY, 3),
]

DIRECTION_OUT = RecurringSuggestionDismissal.DIRECTION_OUT
DIRECTION_IN = RecurringSuggestionDismissal.DIRECTION_IN

_NON_LETTERS = re.compile(r"[^a-z]+")


def payee_key(name: str | None) -> str:
    """The name a run is grouped by: lowercase letters only, single-spaced."""
    return " ".join(_NON_LETTERS.sub(" ", (name or "").lower()).split())


def _direction(amount: Decimal) -> str:
    return DIRECTION_OUT if amount > 0 else DIRECTION_IN


def suggestion_key(account_id: int, direction: str, key: str) -> str:
    """The id a suggestion is dismissed by."""
    return f"{account_id}:{direction}:{key}"


def _match_period(dates: list[date]) -> Period | None:
    gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
    typical = median(gaps)
    for period in PERIODS:
        if abs(typical - period.days) <= period.tolerance and all(
            abs(gap - period.days) <= period.tolerance for gap in gaps
        ):
            return period
    return None


def _day_of_month(dates: list[date]) -> int:
    """The day a monthly run falls on: the latest one's, or the last day when it keeps landing near month end."""
    last = dates[-1]
    near_end = [d for d in dates if (d + timedelta(days=1)).month != d.month or d.day >= 28]
    if len(near_end) == len(dates) and len({d.day for d in dates}) > 1:
        return RecurringTransaction.LAST_DAY_OF_MONTH
    return last.day


def _schedule_for(period: Period, dates: list[date]) -> RecurringTransaction:
    """An unsaved schedule starting at the latest occurrence, for `following()` and `describe()`."""
    last = dates[-1]
    return RecurringTransaction(
        frequency=period.frequency,
        interval=period.interval,
        weekday=last.weekday() if period.frequency == RecurringTransaction.FREQUENCY_WEEKLY else None,
        day_of_month=_day_of_month(dates) if period.frequency == RecurringTransaction.FREQUENCY_MONTHLY else None,
        start_date=last,
    )


def _category_of(tx: BankTransaction):
    """(category account, is_split) of a row's entry: (None, False) when uncategorized."""
    if tx.journal_entry_id is None:
        return None, False
    others = [line for line in tx.journal_entry.lines.all() if line.account_id != tx.account_id]
    if len(others) > 1:
        return None, True
    return (others[0].account if others else None), False


def find_suggestions(book, account_ids=None, today: date | None = None) -> list[dict]:
    """Every live recurring pattern in `book` (in `account_ids`, when given), soonest expected first."""
    today = today or timezone.localdate()
    rows = (
        BankTransaction.objects.filter(
            book=book,
            is_void=False,
            is_transfer_mirror=False,
            account__has_feed=True,
            account__is_hidden=False,
            posted_date__gte=today - timedelta(days=LOOKBACK_DAYS),
            posted_date__lte=today,
        )
        .exclude(amount=0)
        .select_related("account")
        .order_by("posted_date", "id")
    )
    if account_ids:
        rows = rows.filter(account_id__in=account_ids)

    runs = defaultdict(list)
    for tx in rows:
        key = payee_key(tx.merchant_name or tx.description)
        if key:
            runs[(tx.account_id, _direction(tx.amount), key)].append(tx)

    scheduled = set()
    for rule in RecurringTransaction.objects.filter(book=book, next_date__isnull=False):
        scheduled.add((rule.account_id, _direction(rule.amount), payee_key(rule.payee_name or rule.description)))
    dismissed = set(
        RecurringSuggestionDismissal.objects.filter(book=book).values_list("account_id", "direction", "payee_key")
    )
    # Accounts a bank feeds through Plaid: a schedule there duplicates the bank's own copy.
    bank_synced = set(Account.objects.filter(book=book, plaid_accounts__isnull=False).values_list("id", flat=True))

    candidates = []
    for (account_id, direction, key), txs in runs.items():
        if (account_id, direction, key) in scheduled or (account_id, direction, key) in dismissed:
            continue
        # One per day: a split payment or a same-day correction is not a second occurrence.
        by_day = {}
        for tx in txs:
            by_day[tx.posted_date] = tx
        dates = sorted(by_day)
        if len(dates) < MIN_OCCURRENCES:
            continue
        period = _match_period(dates)
        if period is None:
            continue
        latest = by_day[dates[-1]]
        tolerance = abs(latest.amount) * AMOUNT_TOLERANCE
        if any(abs(by_day[d].amount - latest.amount) > tolerance for d in dates):
            continue
        if (today - dates[-1]).days > period.days + period.tolerance:
            continue
        candidates.append((account_id, direction, key, period, dates, latest))

    # Categories are read only for the survivors: one entry's lines each.
    latest_ids = [c[5].id for c in candidates]
    latest_rows = {
        tx.id: tx
        for tx in BankTransaction.objects.filter(id__in=latest_ids)
        .select_related("account__account_group", "account__institution", "journal_entry")
        .prefetch_related("journal_entry__lines__account__account_group", "journal_entry__lines__account__institution")
    }

    suggestions = []
    for account_id, direction, key, period, dates, latest in candidates:
        latest = latest_rows[latest.id]
        schedule = _schedule_for(period, dates)
        category, is_split = _category_of(latest)
        amount = latest.amount
        suggestions.append(
            {
                "key": suggestion_key(account_id, direction, key),
                "transaction_id": latest.id,
                "account": latest.account,
                "bank_synced": account_id in bank_synced,
                "payee": latest.merchant_name or latest.description,
                "category": category,
                "is_split": is_split,
                "inflow": -amount if amount < 0 else Decimal("0"),
                "outflow": amount if amount > 0 else Decimal("0"),
                "frequency": schedule.frequency,
                "interval": schedule.interval,
                "weekday": schedule.weekday,
                "day_of_month": schedule.day_of_month,
                "schedule": describe(schedule),
                "occurrences": len(dates),
                "last_date": dates[-1],
                "next_date": following(schedule, dates[-1]),
            }
        )
    suggestions.sort(key=lambda s: (s["next_date"], s["payee"].lower()))
    return suggestions
