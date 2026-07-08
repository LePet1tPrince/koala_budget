"""
Transfer duplicate detection.

A single real-world transfer between two of the user's own accounts is reported
by *both* banks, so it lands in the feed twice: an outflow in the source account
and an inflow in the destination account. If the user categorizes both legs they
get two journal entries and the movement is double-counted in every balance and
on the balance sheet.

This service finds those likely duplicate pairs so the UI can ask the user to
archive one leg (keeping a single entry) or dismiss the suggestion. It only
*suggests* — nothing is changed here, and a human confirms every pair.
"""

from django.conf import settings

from apps.journal.models import JournalEntry

from ..models import BankTransaction, TransferMatchDismissal

# How many days apart the two legs of a transfer may post and still be paired.
# ACH transfers commonly clear the two accounts a few business days apart.
DEFAULT_WINDOW_DAYS = 5


def get_window_days():
    return int(getattr(settings, "BANK_FEED_TRANSFER_WINDOW_DAYS", DEFAULT_WINDOW_DAYS))


def find_transfer_candidates(team, window_days=None):
    """
    Return a list of likely-duplicate transfer pairs for a team.

    Each item is a dict ``{"outflow": BankTransaction, "inflow": BankTransaction,
    "date_gap_days": int}``. A pair qualifies when the two transactions:

      - belong to different accounts,
      - have equal magnitude and opposite direction (one outflow, one inflow),
      - posted within ``window_days`` of each other,
      - are neither archived nor backed by a voided journal entry, and
      - have not been dismissed as "not a transfer".

    Matching is greedy and one-to-one: each transaction appears in at most one
    suggested pair, choosing the closest-dated counterpart first so identical
    repeated transfers pair up sensibly.
    """
    if window_days is None:
        window_days = get_window_days()

    # Mirror legs are synthetic counterparts auto-created when their primary leg
    # was categorized as a transfer to another feed account (see transfer_mirror.py) —
    # they were never independently reported by a bank, so they must not be treated
    # as a candidate duplicate for a *different* transaction. Without this exclusion
    # a mirror leg can pair with an unrelated real transaction, surfacing the same
    # underlying transfer as a second, spurious suggestion.
    transactions = list(
        BankTransaction.objects.filter(team=team, is_archived=False, is_transfer_mirror=False)
        .exclude(journal_entry__status=JournalEntry.STATUS_VOID)
        .select_related("account", "journal_entry")
        .order_by("posted_date", "id")
    )

    # Group by absolute amount; only equal-magnitude legs can pair.
    by_amount = {}
    for tx in transactions:
        by_amount.setdefault(abs(tx.amount), []).append(tx)

    dismissed = _dismissed_pairs(team)
    used = set()
    pairs = []

    for amount, group in by_amount.items():
        if amount == 0:
            continue
        # Plaid convention: positive amount = outflow, negative = inflow.
        outflows = [tx for tx in group if tx.amount > 0]
        inflows = [tx for tx in group if tx.amount < 0]
        if not outflows or not inflows:
            continue

        for out_tx in outflows:
            if out_tx.id in used:
                continue
            best = None
            best_gap = None
            for in_tx in inflows:
                if in_tx.id in used:
                    continue
                if in_tx.account_id == out_tx.account_id:
                    continue
                # The two legs of one transfer (a primary and its mirror) share a
                # journal entry — they're one movement, not a duplicate.
                if out_tx.journal_entry_id is not None and out_tx.journal_entry_id == in_tx.journal_entry_id:
                    continue
                if TransferMatchDismissal.normalize_pair(out_tx.id, in_tx.id) in dismissed:
                    continue
                gap = abs((out_tx.posted_date - in_tx.posted_date).days)
                if gap > window_days:
                    continue
                if best is None or gap < best_gap:
                    best = in_tx
                    best_gap = gap
            if best is not None:
                used.add(out_tx.id)
                used.add(best.id)
                pairs.append({"outflow": out_tx, "inflow": best, "amount": amount, "date_gap_days": best_gap})

    # Surface the most recent suggestions first.
    pairs.sort(key=lambda p: max(p["outflow"].posted_date, p["inflow"].posted_date), reverse=True)
    return pairs


def _dismissed_pairs(team):
    """Return a set of normalized (low_id, high_id) tuples the user has dismissed."""
    return {
        (low, high)
        for low, high in TransferMatchDismissal.objects.filter(team=team).values_list(
            "transaction_low_id", "transaction_high_id"
        )
    }
