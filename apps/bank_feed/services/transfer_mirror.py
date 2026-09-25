"""
Transfer mirror legs.

A transfer between two of the user's own *feed* accounts (e.g. checking ->
credit card) is one journal entry with two lines, but the bank feed shows one
row per BankTransaction and a plain categorization only creates the originating
account's row. To make a transfer visible — and independently reconcilable — in
*both* account feeds, we keep a linked "mirror" BankTransaction in the
counterpart account pointing at the same journal entry.

Both legs share one entry: the ledger is never double-counted, reconciliation is
per-line (independent), editing one leg's date/amount/description propagates to
the other, and re-pointing *either* leg's category moves the counterpart leg to
follow (fully transversable mirrors).
"""

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY

from ..models import BankTransaction


def is_transfer_target(account):
    """
    A categorization counts as a transfer (and gets a mirror leg) when the other
    side is one of the user's own feed-enabled asset/liability accounts. Expense
    and income categories — and untracked accounts without a feed — never mirror.
    """
    if account is None or not account.has_feed:
        return False
    group = account.account_group
    return bool(group and group.account_type in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY))


def would_orphan_primary(edited_tx, new_category_account):
    """
    True when re-pointing this leg's category would orphan a real transaction.

    Pointing the *mirror* leg at a non-feed category (e.g. an expense) would move
    the primary's ledger line away from the primary's home account, leaving the
    real imported transaction stranded. Callers reject that and tell the user to
    edit the original transaction instead.

    A split's own row is never a mirror, so this is False for it. A split's
    *mirror* (the transfer leg's row in the other account, see
    :func:`mirror_rows_for`) is one line of someone else's split: re-pointing it
    to anything would rewrite that split, so it is always refused.
    """
    if not edited_tx.is_transfer_mirror:
        return False
    if is_split_mirror(edited_tx):
        return True
    return not is_transfer_target(new_category_account)


def is_split_mirror(tx) -> bool:
    """True for the mirror row of a split's transfer leg -- not editable on its own."""
    return bool(tx.is_transfer_mirror and _is_split_entry(tx.journal_entry_id and tx.journal_entry))


def _is_split_entry(entry) -> bool:
    """
    True for a split entry -- one bank line plus several category legs.

    Mirrors the definition in :mod:`.splits` (kept local to avoid a cycle).
    """
    return bool(entry) and entry.lines.count() > 2


def linked_legs(tx):
    """
    The other BankTransaction leg(s) sharing this transfer's journal entry, if any.

    A transfer's two legs are archived/restored together — archiving one side of
    a transfer without the other would leave it half-hidden in one feed. A split
    with transfer legs has one row per feed account it touches; they go together too.
    """
    if tx.journal_entry_id is None:
        return BankTransaction.objects.none()
    return BankTransaction.objects.filter(journal_entry_id=tx.journal_entry_id).exclude(id=tx.id)


def mirror_rows_for(primary, lines) -> list[BankTransaction]:
    """
    The mirror rows `primary`'s entry should have, unsaved.

    One per line on another *feed* account: a plain transfer has one (for the
    whole amount), a split has one per leg that is a transfer (for that leg's
    amount -- never the split's total, which no bank on that side reported).
    Display fields come from the primary; the amount is the leg's line in the
    feed convention (positive = outflow), so the mirror is the money arriving on
    the other side.

    Pure, so the YNAB import can bulk-insert exactly what :func:`sync_transfer`
    would create. `lines` must carry `account.account_group`.
    """
    rows = []
    for line in lines:
        if line.account_id == primary.account_id or not is_transfer_target(line.account):
            continue
        rows.append(
            BankTransaction(
                book_id=primary.book_id,
                journal_entry_id=primary.journal_entry_id,
                account=line.account,
                amount=-(line.dr_amount - line.cr_amount),
                posted_date=primary.posted_date,
                description=primary.description,
                merchant_name=primary.merchant_name,
                is_transfer_mirror=True,
                source=BankTransaction.SOURCE_SYSTEM,
            )
        )
    return rows


MIRRORED_FIELDS = ("account_id", "amount", "posted_date", "description", "merchant_name")


def sync_transfer(edited_tx):
    """
    Reconcile a transfer's counterpart leg(s) with the edited leg.

    Idempotent and symmetric — safe to call after any change to either leg. Based
    on the edited leg's current entry:

      - if the counterpart account is a transfer target, ensure a counterpart leg
        lives there (create the mirror the first time, or move the existing leg to
        follow), with display fields mirrored from the edited leg;
      - otherwise it is no longer a transfer, so drop the mirror leg. The real
        (non-mirror) leg is never deleted here — :func:`would_orphan_primary`
        guards the only path that could strand it;
      - a split gets one mirror per leg on another feed account (see
        :func:`mirror_rows_for`), created, updated or dropped to match its legs.
    """
    if edited_tx.journal_entry_id is None:
        return

    entry = edited_tx.journal_entry
    lines = list(entry.lines.select_related("account__account_group"))
    others = list(BankTransaction.objects.filter(journal_entry=entry).exclude(id=edited_tx.id))

    if len(lines) > 2:
        _sync_split_mirrors(edited_tx, lines, others)
        return

    counterpart_account = next((line.account for line in lines if line.account_id != edited_tx.account_id), None)

    if counterpart_account is not None and is_transfer_target(counterpart_account):
        # Editing the mirror moves the primary to follow, so a real leg comes first;
        # otherwise the mirror already there (a former split can leave several).
        counterpart_tx = (
            next((tx for tx in others if not tx.is_transfer_mirror), None)
            or next((tx for tx in others if tx.account_id == counterpart_account.id), None)
            or (others[0] if others else None)
        )
        if counterpart_tx is None:
            counterpart_tx = BankTransaction(
                book=edited_tx.book,
                journal_entry=entry,
                is_transfer_mirror=True,
                source=BankTransaction.SOURCE_SYSTEM,
            )
        counterpart_tx.account = counterpart_account
        counterpart_tx.amount = -edited_tx.amount  # opposite direction
        counterpart_tx.posted_date = edited_tx.posted_date
        counterpart_tx.description = edited_tx.description
        counterpart_tx.merchant_name = edited_tx.merchant_name
        counterpart_tx.save()
        stale = [tx for tx in others if tx.is_transfer_mirror and tx.id != counterpart_tx.id]
    else:
        stale = [tx for tx in others if tx.is_transfer_mirror]

    for tx in stale:
        tx.delete()


def _sync_split_mirrors(edited_tx, lines, others):
    """
    Give a split one mirror per transfer leg, and nothing else.

    The primary is the split's own row (the one on the bank line). Editing a
    split's mirror is refused upstream, but should one arrive here it syncs from
    the primary rather than treating the mirror's account as the bank line.
    """
    legs = [edited_tx, *others]
    primary = next((tx for tx in legs if not tx.is_transfer_mirror), None)
    if primary is None:
        return

    mirrors = [tx for tx in legs if tx.is_transfer_mirror]
    # An account that already has a real row on this entry needs no mirror.
    real_accounts = {tx.account_id for tx in legs if not tx.is_transfer_mirror}

    for wanted in mirror_rows_for(primary, lines):
        if wanted.account_id in real_accounts:
            continue
        existing = next((tx for tx in mirrors if tx.account_id == wanted.account_id), None)
        if existing is None:
            wanted.save()
            continue
        mirrors.remove(existing)
        changed = [field for field in MIRRORED_FIELDS if getattr(existing, field) != getattr(wanted, field)]
        if changed:
            for field in changed:
                setattr(existing, field, getattr(wanted, field))
            existing.save()

    for tx in mirrors:
        tx.delete()
