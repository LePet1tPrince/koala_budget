"""
Deleting a team's books (§4.2, §4.3 of `docs/export-import-plan.md`).

`wipe_team(team)` is the single most destructive operation in this feature,
and it never runs on its own -- it is always called from inside `apply.py`'s
one `transaction.atomic` block, alongside the safety export that makes it
recoverable. No `@transaction.atomic` here on purpose: that decorator belongs
to the caller, which also has to decide whether a check failure after the
wipe rolls the whole thing back (it does).

Two things this order exists to get right:

1. **`PROTECT` and `CASCADE` decide almost the whole order for us.** Once
   `PlaidAccount` (which `PROTECT`s `Account`) is out of the way, a single
   `Account.objects.filter(team=team).delete()` cascades `BankTransaction`,
   `PlaidTransaction`, `TransferMatchDismissal`, `Budget`, `Goal` and
   `GoalAllocation` in one call -- Django's collector resolves that graph,
   and re-deriving its topological order by hand here would just be a second
   implementation that could drift from the models' own `on_delete` values.
2. **The audit-signal trap only applies to `JournalLine`/`JournalEntry`.**
   Those two are the only models with `post_delete` receivers
   (`apps/audit/signals.py`), so they are the only ones deleted with
   `_raw_delete` -- a raw `DELETE`, no signals, no collector. That comes with
   a duty `.delete()` would have discharged for free: `_raw_delete` does not
   walk `on_delete=SET_NULL` relations, so `BankTransaction.journal_entry`
   has to be nulled out **explicitly**, before the entries it points to are
   raw-deleted, or the raw `DELETE FROM journal_journalentry` fails against
   a foreign key a nulling `.update()` would otherwise have cleared.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.accounts.models import Account, AccountGroup, Institution, Payee
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry, JournalLine
from apps.plaid.models import PlaidAccount, PlaidItem


@dataclass
class WipeCounts:
    lines: int = 0
    entries: int = 0
    bank_transactions: int = 0
    plaid_transactions: int = 0
    transfer_dismissals: int = 0
    budgets: int = 0
    goals: int = 0
    goal_allocations: int = 0
    plaid_accounts: int = 0
    plaid_items: int = 0
    accounts: int = 0
    account_groups: int = 0
    payees: int = 0
    institutions: int = 0

    def as_dict(self) -> dict:
        return {
            "lines": self.lines,
            "entries": self.entries,
            "bank_transactions": self.bank_transactions,
            "plaid_transactions": self.plaid_transactions,
            "transfer_dismissals": self.transfer_dismissals,
            "budgets": self.budgets,
            "goals": self.goals,
            "goal_allocations": self.goal_allocations,
            "plaid_accounts": self.plaid_accounts,
            "plaid_items": self.plaid_items,
            "accounts": self.accounts,
            "account_groups": self.account_groups,
            "payees": self.payees,
            "institutions": self.institutions,
        }


def wipe_team(team) -> WipeCounts:
    """Delete every row this feature exports for `team`. See module docstring for the order."""
    counts = WipeCounts()

    # Break the FK from feed rows to entries before the entries are
    # raw-deleted -- see point 2 above. A plain `.update()` fires no
    # post_save signal, so this costs nothing extra on the audit trail.
    BankTransaction.objects.filter(team=team, journal_entry__isnull=False).update(journal_entry=None)

    lines = JournalLine.objects.filter(team=team)
    counts.lines = lines._raw_delete(lines.db)

    entries = JournalEntry.objects.filter(team=team)
    counts.entries = entries._raw_delete(entries.db)

    # Releases the PROTECT that would otherwise block deleting Account below.
    plaid_accounts = PlaidAccount.objects.filter(team=team)
    counts.plaid_accounts = plaid_accounts.count()
    plaid_accounts.delete()
    plaid_items = PlaidItem.objects.filter(team=team)
    counts.plaid_items = plaid_items.count()
    plaid_items.delete()

    # One call, one cascade: BankTransaction (-> PlaidTransaction,
    # TransferMatchDismissal), Budget, Goal (-> GoalAllocation). The
    # collector's own breakdown is the "counted, not inferred" figure (§4.2).
    _total, breakdown = Account.objects.filter(team=team).delete()
    counts.accounts = breakdown.get("accounts.Account", 0)
    counts.bank_transactions = breakdown.get("bank_feed.BankTransaction", 0)
    counts.plaid_transactions = breakdown.get("plaid.PlaidTransaction", 0)
    counts.transfer_dismissals = breakdown.get("bank_feed.TransferMatchDismissal", 0)
    counts.budgets = breakdown.get("budget.Budget", 0)
    counts.goals = breakdown.get("budget.Goal", 0)
    counts.goal_allocations = breakdown.get("budget.GoalAllocation", 0)

    account_groups = AccountGroup.objects.filter(team=team)
    counts.account_groups = account_groups.count()
    account_groups.delete()

    payees = Payee.objects.filter(team=team)
    counts.payees = payees.count()
    payees.delete()

    institutions = Institution.objects.filter(team=team)
    counts.institutions = institutions.count()
    institutions.delete()

    return counts
