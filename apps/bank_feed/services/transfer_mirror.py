"""
Transfer mirror legs.

A transfer between two of the user's own *feed* accounts (e.g. checking ->
credit card) is one journal entry with two lines, but the bank feed shows one
row per BankTransaction and a plain categorization only creates the originating
account's row. To make a transfer visible — and independently reconcilable — in
*both* account feeds, we keep a linked "mirror" BankTransaction in the
counterpart account pointing at the same journal entry.

Both legs share one entry: the ledger is never double-counted, reconciliation is
per-line (independent), and re-pointing *either* leg's category moves the
counterpart leg to follow (fully transversable mirrors). Amounts stay in
lockstep (one balanced entry), but each leg owns its display fields — date,
payee, description — so editing them on one side never rewrites the other.
They are only copied once, as defaults, when the mirror is first created.
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
    """
    return bool(edited_tx.is_transfer_mirror and not is_transfer_target(new_category_account))


def _counterpart_account(entry, primary_account):
    """The account on the entry's other line (the non-primary side), or None."""
    for line in entry.lines.all():
        if line.account_id != primary_account.id:
            return line.account
    return None


def sync_transfer(edited_tx):
    """
    Reconcile a transfer's counterpart leg with the edited leg.

    Idempotent and symmetric — safe to call after any change to either leg. Based
    on the edited leg's current entry:

      - if the counterpart account is a transfer target, ensure a counterpart leg
        lives there (create the mirror the first time, or move the existing leg to
        follow). Only account and amount are kept in lockstep; date, payee and
        description belong to each leg and are seeded from the edited leg only
        when the mirror is first created;
      - otherwise it is no longer a transfer, so drop the mirror leg. The real
        (non-mirror) leg is never deleted here — :func:`would_orphan_primary`
        guards the only path that could strand it.
    """
    if edited_tx.journal_entry_id is None:
        return

    entry = edited_tx.journal_entry
    counterpart_account = _counterpart_account(entry, edited_tx.account)
    counterpart_tx = BankTransaction.objects.filter(journal_entry=entry).exclude(id=edited_tx.id).first()

    if counterpart_account is not None and is_transfer_target(counterpart_account):
        if counterpart_tx is None:
            counterpart_tx = BankTransaction(
                team=edited_tx.team,
                journal_entry=entry,
                is_transfer_mirror=True,
                source=BankTransaction.SOURCE_SYSTEM,
                # Initial defaults only — after creation each leg owns these.
                posted_date=edited_tx.posted_date,
                description=edited_tx.description,
                merchant_name=edited_tx.merchant_name,
            )
        counterpart_tx.account = counterpart_account
        counterpart_tx.amount = -edited_tx.amount  # opposite direction
        counterpart_tx.save()
    elif counterpart_tx is not None and counterpart_tx.is_transfer_mirror:
        counterpart_tx.delete()
