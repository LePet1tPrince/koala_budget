"""
What a statement can be checked against, and what the numbers say.

Works on `JournalLine`s for the account, not on bank-feed rows: a YNAB import,
an opening balance and a manual entry all write lines with no feed row, and a
flow built on the feed could not reconcile any of them.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalLine, counted_entries

from ..models import Reconciliation
from .signs import to_statement

#: Banks and the ledger often disagree on a date by a day or two, so the list
#: reaches this far past the statement date unless asked for everything.
LATER_WINDOW_DAYS = 7

ZERO = Decimal("0")


def _ledger_sum(queryset) -> Decimal:
    totals = queryset.aggregate(dr=Coalesce(Sum("dr_amount"), ZERO), cr=Coalesce(Sum("cr_amount"), ZERO))
    return totals["dr"] - totals["cr"]


def reconciled_balance(account) -> Decimal:
    """Ledger-sign reconciled balance: the same figure `with_reconciled_balance()` gives."""
    return _ledger_sum(
        JournalLine.objects.filter(account=account, is_reconciled=True).filter(counted_entries("journal_entry__"))
    )


def candidate_lines(reconciliation):
    """
    Every line on the account this draft may tick, ticked or not, with no date window.

    Excludes reconciled lines, entries that count toward nothing (void, or
    behind an archived bank transaction -- `counted_entries`, the ledger-wide
    rule), and lines another draft holds (there is only ever one draft per
    account, so this is belt and braces).
    """
    return (
        JournalLine.objects.filter(team=reconciliation.team, account=reconciliation.account, is_reconciled=False)
        .filter(counted_entries("journal_entry__"))
        .exclude(Q(reconciliation__status=Reconciliation.STATUS_DRAFT) & ~Q(reconciliation_id=reconciliation.id))
    )


def ticked_lines(reconciliation):
    return candidate_lines(reconciliation).filter(reconciliation=reconciliation)


def visible_lines(reconciliation, *, include_later=False):
    """The list the page shows: candidates up to a week past the statement date, plus anything ticked."""
    queryset = candidate_lines(reconciliation)
    if not include_later:
        cutoff = reconciliation.statement_date + timedelta(days=LATER_WINDOW_DAYS)
        queryset = queryset.filter(Q(journal_entry__entry_date__lte=cutoff) | Q(reconciliation=reconciliation))
    return queryset.select_related("journal_entry", "journal_entry__payee").order_by(
        "journal_entry__entry_date", "journal_entry_id", "pk"
    )


@dataclass(frozen=True)
class Summary:
    """The draft's numbers, all in LEDGER sign; `as_statement()` converts for the API."""

    statement_balance: Decimal
    opening: Decimal
    ticked_total: Decimal
    ticked_count: int

    @property
    def difference(self) -> Decimal:
        return self.statement_balance - (self.opening + self.ticked_total)

    def as_statement(self, account) -> dict:
        return {
            "statement_balance": to_statement(account, self.statement_balance),
            "opening": to_statement(account, self.opening),
            "ticked_total": to_statement(account, self.ticked_total),
            "ticked_count": self.ticked_count,
            "difference": to_statement(account, self.difference),
        }


def summary(reconciliation) -> Summary:
    """Always recomputed from the database -- never taken from the client."""
    ticked = ticked_lines(reconciliation)
    return Summary(
        statement_balance=reconciliation.statement_balance,
        opening=reconciled_balance(reconciliation.account),
        ticked_total=_ledger_sum(ticked),
        ticked_count=ticked.count(),
    )


def uncategorized_rows(reconciliation):
    """Feed rows on or before the statement date with no journal entry: real money that cannot be ticked yet."""
    return BankTransaction.objects.filter(
        team=reconciliation.team,
        account=reconciliation.account,
        journal_entry__isnull=True,
        is_archived=False,
        posted_date__lte=reconciliation.statement_date,
    ).order_by("posted_date", "pk")


def feed_row_statement_amount(account, bank_tx) -> Decimal:
    """A feed row's effect on the statement balance (feed convention: positive is an outflow)."""
    return to_statement(account, -bank_tx.amount)


def line_statement_amount(account, line) -> Decimal:
    return to_statement(account, line.dr_amount - line.cr_amount)
