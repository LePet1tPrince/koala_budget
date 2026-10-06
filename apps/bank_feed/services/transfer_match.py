"""
Match the two bank-reported legs of one transfer.

A transfer between two of the user's own accounts is reported by both banks, so it
lands in the feed twice (see transfer_detection.py). Matching keeps one leg,
archives the other, and categorizes the kept leg as a transfer to the archived
leg's account -- leaving one journal entry with a line on each account, shown in
both feeds (the second through its mirror row, see transfer_mirror.py).

Which leg is archived is decided here, never by the client: `propose` runs when the
suggestions are listed (so the UI can say what Match will do) and again inside
`match` (so a pair whose state moved in between is refused rather than applied
differently from what the user was shown).
"""

from dataclasses import asdict, dataclass

from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.guards import assert_category_allowed
from apps.journal.models import JournalEntry, JournalLine

from ..models import BankTransaction, TransferMatchDismissal
from .categorize import categorize_single
from .transfer_detection import get_window_days

# Higher wins a tie between two otherwise equal legs: a live bank connection is
# the most authoritative copy, a file import next, a hand-entered row last.
SOURCE_RANK = {
    BankTransaction.SOURCE_PLAID: 3,
    BankTransaction.SOURCE_CSV: 2,
    BankTransaction.SOURCE_YNAB: 2,
    BankTransaction.SOURCE_MANUAL: 1,
}


class MatchError(ValueError):
    """A pair that cannot be matched; the message is shown to the user."""


class ProposalChanged(MatchError):
    """The leg to archive is no longer the one the client was shown."""

    def __init__(self, proposal):
        super().__init__(_("Something changed since this was shown. Check the new outcome and match again."))
        self.proposal = proposal


@dataclass(frozen=True)
class Proposal:
    """What Match would do with a pair: keep one leg and archive the other, or nothing."""

    status: str  # "ready" | "blocked"
    code: str
    message: str
    keep_id: int | None = None
    archive_id: int | None = None

    @property
    def blocked(self):
        return self.status == "blocked"

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class _Leg:
    """The facts about one leg that decide which side is kept."""

    tx: BankTransaction
    lines: tuple  # JournalLines of its entry (empty when uncategorized)

    @property
    def locked(self):
        # Archiving a leg voids its whole entry, so any reconciled line on that
        # entry -- not just this row's own -- makes it unarchivable.
        return any(line.is_reconciled for line in self.lines)

    @property
    def is_split(self):
        return len(self.lines) > 2

    @property
    def category_line(self):
        """The entry's other line (None when uncategorized or split)."""
        if self.is_split:
            return None
        return next((line for line in self.lines if line.account_id != self.tx.account_id), None)

    def is_transfer_to(self, account_id):
        line = self.category_line
        return line is not None and line.account_id == account_id


def _lines_by_entry(transactions):
    entry_ids = {tx.journal_entry_id for tx in transactions if tx.journal_entry_id}
    grouped = {}
    for line in JournalLine.objects.filter(journal_entry_id__in=entry_ids).select_related("account").order_by("pk"):
        grouped.setdefault(line.journal_entry_id, []).append(line)
    return grouped


def _legs(outflow, inflow, lines_by_entry=None):
    if lines_by_entry is None:
        lines_by_entry = _lines_by_entry([outflow, inflow])
    return tuple(_Leg(tx, tuple(lines_by_entry.get(tx.journal_entry_id, ()))) for tx in (outflow, inflow))


def _blocked(code, message):
    return Proposal(status="blocked", code=code, message=message)


def _keep(keep, archive, code, message):
    # A kept leg that needs re-pointing can't have its category line reconciled:
    # that line is a transfer already confirmed against another account's statement.
    line = keep.category_line
    if line is not None and line.account_id != archive.tx.account_id and line.is_reconciled:
        return _blocked(
            "category_reconciled",
            _(
                "The one in %(keep)s is reconciled as a transfer to %(other)s. "
                "Unreconcile it there first, or mark this as not a match."
            )
            % {"keep": keep.tx.account.name, "other": line.account.name},
        )
    return Proposal(status="ready", code=code, message=message, keep_id=keep.tx.id, archive_id=archive.tx.id)


def propose(outflow, inflow, lines_by_entry=None):
    """
    Decide which leg of a pair Match keeps. First rule that decides wins:

      1. either leg is split            -> blocked
      2. both legs' entries reconciled  -> blocked
      3. one leg's entry reconciled     -> keep it
      4. one leg already categorized as a transfer to the other's account -> keep it
      5. one leg categorized, one not   -> keep the categorized one
      6. source rank (plaid > csv/ynab > manual) -> keep the higher
      7. otherwise                      -> keep the outflow (the transfer's origin)
    """
    out_leg, in_leg = _legs(outflow, inflow, lines_by_entry)
    pair = (out_leg, in_leg)

    if out_leg.is_split or in_leg.is_split:
        return _blocked(
            "split",
            _("One side is split across categories. Open it to change its categories, or mark this as not a match."),
        )

    if out_leg.locked and in_leg.locked:
        return _blocked("both_reconciled", _("Both sides are reconciled. Unreconcile one of them to match."))

    def decide(prefer, code, message):
        keep = prefer
        archive = in_leg if keep is out_leg else out_leg
        return _keep(keep, archive, code, message % {"keep": keep.tx.account.name})

    locked = [leg for leg in pair if leg.locked]
    if locked:
        return decide(locked[0], "reconciled", _("the one in %(keep)s is reconciled."))

    transfers = [leg for leg in pair if leg.is_transfer_to((in_leg if leg is out_leg else out_leg).tx.account_id)]
    if len(transfers) == 1:
        message = _("the one in %(keep)s is already categorized as this transfer.")
        return decide(transfers[0], "already_transfer", message)

    categorized = [leg for leg in pair if leg.lines]
    if len(categorized) == 1:
        return decide(categorized[0], "categorized", _("the one in %(keep)s is already categorized."))

    out_rank = SOURCE_RANK.get(outflow.source, 0)
    in_rank = SOURCE_RANK.get(inflow.source, 0)
    if out_rank != in_rank:
        keep = out_leg if out_rank > in_rank else in_leg
        if keep.tx.source == BankTransaction.SOURCE_PLAID:
            message = _("the one in %(keep)s came straight from your bank connection.")
        else:
            message = _("the one in %(keep)s was imported rather than entered by hand.")
        return decide(keep, "source", message)

    return decide(out_leg, "outflow", _("it is the side the money left from."))


def propose_pairs(pairs):
    """Attach a `proposal` dict to each pair from `find_transfer_candidates`, in two queries."""
    lines_by_entry = _lines_by_entry([tx for pair in pairs for tx in (pair["outflow"], pair["inflow"])])
    for pair in pairs:
        pair["proposal"] = propose(pair["outflow"], pair["inflow"], lines_by_entry).as_dict()
    return pairs


def validate_pair(a, b, book):
    """
    Refuse a pair that isn't two legs of one transfer, by the detector's own tests.

    Returns ``(outflow, inflow)``. The detector's greedy one-to-one choice is not
    re-run: a pair valid on its own is safe to match even when the detector would
    have paired one of its legs differently.
    """
    if a.account_id == b.account_id:
        raise MatchError(_("Both transactions are in the same account."))
    if a.amount == 0 or a.amount != -b.amount:
        raise MatchError(_("A transfer's two sides must be equal amounts in opposite directions."))
    for tx in (a, b):
        if tx.is_archived:
            raise MatchError(_("One of these transactions is archived."))
        if tx.is_transfer_mirror:
            raise MatchError(_("One of these is the other side of an existing transfer, not a bank transaction."))
        if tx.journal_entry_id and tx.journal_entry.status == JournalEntry.STATUS_VOID:
            raise MatchError(_("One of these transactions is void."))
    if a.journal_entry_id and a.journal_entry_id == b.journal_entry_id:
        raise MatchError(_("These two are already one transfer."))
    if abs((a.posted_date - b.posted_date).days) > get_window_days():
        raise MatchError(_("These transactions are too far apart to be one transfer."))
    low, high = TransferMatchDismissal.normalize_pair(a.id, b.id)
    if TransferMatchDismissal.objects.filter(book=book, transaction_low_id=low, transaction_high_id=high).exists():
        raise MatchError(_("This pair was marked as not a match."))
    return (a, b) if a.amount > 0 else (b, a)


def archive_duplicate(tx):
    """
    Archive a duplicate leg so it stops counting: void its entry, archive it, and
    archive any other leg sharing that entry (its mirror) so the voided transfer
    disappears from both feeds. The caller has checked nothing on the entry is
    reconciled.
    """
    entry = tx.journal_entry
    if entry and entry.status != JournalEntry.STATUS_VOID:
        entry.status = JournalEntry.STATUS_VOID
        entry.save(update_fields=["status", "updated_at"])
    tx.archive()
    if entry:
        for leg in BankTransaction.objects.filter(journal_entry=entry).exclude(id=tx.id):
            if not leg.is_archived:
                leg.archive()


@transaction.atomic
def match_transfer(book, transaction_a, transaction_b, *, expected_archive_id):
    """
    Match a pair: archive one leg, make the kept leg the transfer between both accounts.

    Raises `BankTransaction.DoesNotExist` when either id is outside `book`,
    `ProposalChanged` when the leg to archive is not `expected_archive_id`, and
    `MatchError` (a ValueError, as are the categorize guards) when the pair can't
    be matched. Returns a dict describing what was done.
    """
    ids = {transaction_a, transaction_b}
    # Lock both rows; a concurrent edit or second click waits, then sees the result.
    locked = list(BankTransaction.objects.select_for_update().filter(book=book, id__in=ids))
    if len(ids) != 2 or len(locked) != 2:
        raise BankTransaction.DoesNotExist
    rows = {tx.id: tx for tx in BankTransaction.objects.select_related("account", "journal_entry").filter(id__in=ids)}

    outflow, inflow = validate_pair(rows[transaction_a], rows[transaction_b], book)
    proposal = propose(outflow, inflow)
    if proposal.blocked:
        raise MatchError(proposal.message)
    if proposal.archive_id != expected_archive_id:
        raise ProposalChanged(proposal)

    keep = rows[proposal.keep_id]
    archive = rows[proposal.archive_id]
    keep_leg = _legs(keep, archive)[0]
    previous_category = keep_leg.category_line
    voided_entry_id = archive.journal_entry_id

    archive_duplicate(archive)
    if not keep_leg.is_transfer_to(archive.account_id):
        assert_category_allowed(archive.account)
        categorize_single(keep, archive.account)
    keep.refresh_from_db()

    return {
        "kept_id": keep.id,
        "archived_id": archive.id,
        "kept_journal_entry_id": keep.journal_entry_id,
        "previous_category_id": previous_category.account_id if previous_category else None,
        "voided_entry_id": voided_entry_id,
        "reason_code": proposal.code,
    }
