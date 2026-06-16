"""
Transfer mirror legs.

A transfer between two of the user's own *feed* accounts (e.g. checking ->
credit card) is one journal entry with two lines, but the bank feed shows one
row per BankTransaction and a plain categorization only creates the originating
account's row. To make a transfer visible — and independently reconcilable — in
*both* account feeds, we create a linked "mirror" BankTransaction in the
counterpart account pointing at the same journal entry.

Both legs therefore share one entry: the ledger is never double-counted,
reconciliation is per-line (independent), and editing one leg's date/amount is
propagated to the other so they stay in lockstep.
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


def _counterpart_account(entry, primary_account):
    """The account on the entry's other line (the non-primary side), or None."""
    for line in entry.lines.all():
        if line.account_id != primary_account.id:
            return line.account
    return None


def ensure_mirror_for(primary_tx):
    """
    Create, update, or remove the mirror leg for a categorized primary tx.

    Idempotent — safe to call after any change to the primary. If the counterpart
    account is a transfer target, a mirror exists in that account linked to the
    same entry with display fields derived from the primary; otherwise any stale
    mirror is removed. No-op for mirror rows themselves and uncategorized rows.
    """
    if primary_tx.is_transfer_mirror or primary_tx.journal_entry_id is None:
        return None

    entry = primary_tx.journal_entry
    counterpart = _counterpart_account(entry, primary_tx.account)
    existing = BankTransaction.objects.filter(journal_entry=entry, is_transfer_mirror=True).first()

    if counterpart is None or not is_transfer_target(counterpart):
        # Not (or no longer) a transfer between feed accounts: drop any mirror.
        if existing:
            existing.delete()
        return None

    if existing is None:
        existing = BankTransaction(
            team=primary_tx.team,
            journal_entry=entry,
            is_transfer_mirror=True,
            source=BankTransaction.SOURCE_SYSTEM,
        )

    existing.account = counterpart
    existing.amount = -primary_tx.amount  # opposite direction (out of one, into the other)
    existing.posted_date = primary_tx.posted_date
    existing.description = primary_tx.description
    existing.merchant_name = primary_tx.merchant_name
    existing.save()
    return existing


def sync_counterpart_display(edited_tx):
    """
    Propagate display fields (date/amount/description/payee) from an edited leg to
    its counterpart so both stay in lockstep. Direction-agnostic: works whether
    the user edited the primary or the mirror. The shared journal entry already
    keeps the ledger consistent; this only aligns the per-row display fields.
    """
    if edited_tx.journal_entry_id is None:
        return
    counterpart = (
        BankTransaction.objects.filter(journal_entry_id=edited_tx.journal_entry_id).exclude(id=edited_tx.id).first()
    )
    if counterpart is None:
        return
    counterpart.amount = -edited_tx.amount
    counterpart.posted_date = edited_tx.posted_date
    counterpart.description = edited_tx.description
    counterpart.merchant_name = edited_tx.merchant_name
    counterpart.save()
