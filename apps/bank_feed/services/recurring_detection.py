"""
Spotting transactions that look recurring, so the bank feed can offer to make
them a schedule.

A suggestion is a run of transactions in one account, to the same payee, in the
same direction, at a regular interval and a similar amount, that is still
going. Nothing here writes; `RecurringTransaction` rows are made only when the
user accepts a suggestion (`recurring.create_rule_from_transaction`).

What counts, in order of the checks below:

* the same account, direction (in/out) and payee -- the payee name, or the
  description when there is none, without any word that holds a digit
  (reference codes, dates, store numbers), as its first `KEY_WORDS` words of
  lowercase letters: "NETFLIX.COM 8812" and "Netflix.com 9921" are one payee,
  and so are "AMAZON PRIME*AB12CD" and "Amazon Prime*XY34ZZ";
* within `LOOKBACK_DAYS`, the *latest run*: walking back from the most recent
  occurrence, at least `MIN_OCCURRENCES` (on different days) one period apart
  (within the period's tolerance, `PERIODS`) and within `AMOUNT_TOLERANCE` of
  the latest amount. Anything in between that does not fit -- a one-off
  purchase from the same payee, a refund-sized amount -- is stepped over; the
  run ends at the first gap longer than a period, so older history (a price
  change, a skipped month last spring) never disqualifies it;
* still going: the latest no older than one period plus its tolerance, counted
  from the account's own newest transaction rather than today, so an account
  whose import is a few weeks behind still gets suggestions;
* no live schedule for that account and payee, and not dismissed by the user.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import Account

from ..models import BankTransaction, RecurringSuggestionDismissal, RecurringTransaction
from .recurring import describe, following

LOOKBACK_DAYS = 400
MIN_OCCURRENCES = 3
AMOUNT_TOLERANCE = Decimal("0.20")
KEY_WORDS = 4


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
_TOKEN_SPLIT = re.compile(r"[\s*#/]+")


def payee_key(name: str | None) -> str:
    """The name a run is grouped by: no word with a digit in it, then its first `KEY_WORDS` words of letters."""
    words = [token for token in _TOKEN_SPLIT.split((name or "").lower()) if not any(c.isdigit() for c in token)]
    return " ".join(_NON_LETTERS.sub(" ", " ".join(words)).split()[:KEY_WORDS])


def _direction(amount: Decimal) -> str:
    return DIRECTION_OUT if amount > 0 else DIRECTION_IN


def suggestion_key(account_id: int, direction: str, key: str) -> str:
    """The id a suggestion is dismissed by."""
    return f"{account_id}:{direction}:{key}"


def _run_for(period: Period, dates: list[date], amounts: dict) -> list[date]:
    """
    The occurrences that fit `period`, walking back from the latest: each one a
    period before the last one kept, with a similar amount. Closer ones that do
    not fit are stepped over; the run ends at the first longer gap.
    """
    latest = amounts[dates[-1]]
    tolerance = abs(latest) * AMOUNT_TOLERANCE
    run = [dates[-1]]
    for day in reversed(dates[:-1]):
        gap = (run[0] - day).days
        if gap > period.days + period.tolerance:
            break
        if gap >= period.days - period.tolerance and abs(amounts[day] - latest) <= tolerance:
            run.insert(0, day)
    return run


def _latest_run(dates: list[date], amounts: dict) -> tuple[Period, list[date]] | None:
    """The period with the longest latest run (the shorter period on a tie), if that run is long enough."""
    best = None
    for period in PERIODS:
        run = _run_for(period, dates, amounts)
        if len(run) >= MIN_OCCURRENCES and (best is None or len(run) > len(best[1])):
            best = (period, run)
    return best


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
    account_latest = {}
    for tx in rows:
        account_latest[tx.account_id] = max(account_latest.get(tx.account_id, tx.posted_date), tx.posted_date)
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
        found = _latest_run(dates, {day: tx.amount for day, tx in by_day.items()})
        if found is None:
            continue
        period, run = found
        # Stopped: the account has moved on by more than a period since the last one.
        if (account_latest[account_id] - run[-1]).days > period.days + period.tolerance:
            continue
        candidates.append((account_id, direction, key, period, run, by_day[run[-1]]))

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
