"""
A real, database-backed team covering every corner `fixtures.py` covers at
the row-dict level, plus the ones only visible at the ORM layer: an empty
account group, an unused institution, an unused payee, and a dismissed
transfer pair. Built through the same services production code uses
(`transfer_mirror.sync_transfer` for the reconciled transfer's mirror leg)
rather than hand-rolled, so Phase 2's export is tested against what the app
actually writes, not an approximation of it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.accounts.models import Account, AccountGroup, Institution, Payee
from apps.bank_feed.models import BankTransaction, TransferMatchDismissal
from apps.bank_feed.services.splits import apply_splits
from apps.bank_feed.services.transfer_mirror import sync_transfer
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


def make_team(name: str, slug: str):
    team = Team.objects.create(name=name, slug=slug)
    user = CustomUser.objects.create_user(username=f"{slug}-owner", password="pass")
    team.members.add(user, through_defaults={"role": ROLE_ADMIN})
    return team, user


def build_db_fixture_team(name: str = "Fixture Team", slug: str = "fixture-team"):
    """Returns (team, user, handles) -- handles is a dict of named account ids for assertions."""
    team, user = make_team(name, slug)
    book = team.default_book

    chequing_group = AccountGroup.objects.create(book=book, name="Chequing", account_type="asset")
    credit_group = AccountGroup.objects.create(book=book, name="Credit Cards", account_type="liability")
    equity_group = AccountGroup.objects.create(
        book=book, name="Equity Adjustments", account_type="goal", is_system=True
    )
    household_group = AccountGroup.objects.create(book=book, name="Household", account_type="expense")
    income_group = AccountGroup.objects.create(book=book, name="Employment Income", account_type="income")
    other_income_group = AccountGroup.objects.create(book=book, name="Other Income", account_type="income")
    # The empty-group corner: created, never given an account.
    AccountGroup.objects.create(book=book, name="Vacation", account_type="expense")

    tangerine = Institution.objects.create(book=book, name="Tangerine")
    # The unused-institution corner: created, never attached to an account.
    Institution.objects.create(book=book, name="Unused Bank")

    freshco = Payee.objects.create(book=book, name="FreshCo")
    # The unused-payee corner: created, never used on an entry.
    Payee.objects.create(book=book, name="Never Used Co")

    chequing = Account.objects.create(
        book=book, name="Chequing", account_group=chequing_group, institution=tangerine, has_feed=True
    )
    credit_card = Account.objects.create(book=book, name="Credit Card", account_group=credit_group, has_feed=True)
    reconciliation = Account.objects.create(
        book=book,
        name="Reconciliation Adjustments",
        account_group=equity_group,
        is_system=True,
    )
    groceries = Account.objects.create(book=book, name="Groceries", account_group=household_group)
    paycheck = Account.objects.create(book=book, name="Paycheck", account_group=income_group)
    # Two accounts sharing a name across different types (§2.2).
    misc_expense = Account.objects.create(book=book, name="Misc", account_group=household_group)
    misc_income = Account.objects.create(book=book, name="Misc", account_group=other_income_group)

    goal = Goal.objects.create(
        book=book,
        name="New Deck",
        target_amount=Decimal("5000.00"),
        target_date=date(2027, 6, 1),
    )
    goal_account = goal.account

    # An ordinary categorised transaction with a feed row.
    entry1 = JournalEntry.objects.create(
        book=book,
        entry_date=date(2026, 1, 5),
        payee=freshco,
        description="Groceries",
        source=JournalEntry.SOURCE_BANK_MATCH,
        status=JournalEntry.STATUS_POSTED,
    )
    JournalLine.objects.create(book=book, journal_entry=entry1, account=groceries, dr_amount=Decimal("84.12"))
    JournalLine.objects.create(
        book=book, journal_entry=entry1, account=chequing, cr_amount=Decimal("84.12"), is_cleared=True
    )
    BankTransaction.objects.create(
        book=book,
        account=chequing,
        journal_entry=entry1,
        amount=Decimal("84.12"),
        posted_date=date(2026, 1, 5),
        description="FRESHCO #4417",
        merchant_name="FreshCo",
        source=BankTransaction.SOURCE_CSV,
    )

    # A reconciled transfer -- built through the real mirroring service so the
    # mirror leg is exactly what production would create.
    entry2 = JournalEntry.objects.create(
        book=book,
        entry_date=date(2026, 1, 10),
        description="Credit card payment",
        source=JournalEntry.SOURCE_MANUAL,
        status=JournalEntry.STATUS_POSTED,
    )
    JournalLine.objects.create(
        book=book, journal_entry=entry2, account=credit_card, dr_amount=Decimal("50.00"), is_reconciled=True
    )
    JournalLine.objects.create(book=book, journal_entry=entry2, account=chequing, cr_amount=Decimal("50.00"))
    primary_tx = BankTransaction.objects.create(
        book=book,
        account=chequing,
        journal_entry=entry2,
        amount=Decimal("50.00"),
        posted_date=date(2026, 1, 10),
        description="ONLINE XFER",
        source=BankTransaction.SOURCE_CSV,
    )
    sync_transfer(primary_tx)  # creates the mirror leg on credit_card

    # A dismissed transfer-duplicate pair (two unrelated categorised
    # transactions the user told the reviewer are not the same movement).
    entry3 = JournalEntry.objects.create(
        book=book,
        entry_date=date(2026, 1, 11),
        description="Unrelated #1",
        source=JournalEntry.SOURCE_MANUAL,
        status=JournalEntry.STATUS_POSTED,
    )
    JournalLine.objects.create(book=book, journal_entry=entry3, account=groceries, dr_amount=Decimal("30.00"))
    JournalLine.objects.create(book=book, journal_entry=entry3, account=chequing, cr_amount=Decimal("30.00"))
    dismiss_a = BankTransaction.objects.create(
        book=book,
        account=chequing,
        journal_entry=entry3,
        amount=Decimal("30.00"),
        posted_date=date(2026, 1, 11),
        description="Unrelated #1",
        source=BankTransaction.SOURCE_CSV,
    )
    entry4 = JournalEntry.objects.create(
        book=book,
        entry_date=date(2026, 1, 11),
        description="Unrelated #2",
        source=JournalEntry.SOURCE_MANUAL,
        status=JournalEntry.STATUS_POSTED,
    )
    JournalLine.objects.create(book=book, journal_entry=entry4, account=groceries, dr_amount=Decimal("30.00"))
    JournalLine.objects.create(book=book, journal_entry=entry4, account=credit_card, cr_amount=Decimal("30.00"))
    dismiss_b = BankTransaction.objects.create(
        book=book,
        account=credit_card,
        journal_entry=entry4,
        amount=Decimal("30.00"),
        posted_date=date(2026, 1, 11),
        description="Unrelated #2",
        source=BankTransaction.SOURCE_CSV,
    )
    low, high = sorted([dismiss_a, dismiss_b], key=lambda tx: tx.id)
    TransferMatchDismissal.objects.create(book=book, transaction_low=low, transaction_high=high)

    # A void entry -- kept as evidence (D6), excluded from every balance.
    entry5 = JournalEntry.objects.create(
        book=book,
        entry_date=date(2026, 1, 12),
        description="Entered in error",
        source=JournalEntry.SOURCE_MANUAL,
        status=JournalEntry.STATUS_VOID,
    )
    JournalLine.objects.create(book=book, journal_entry=entry5, account=chequing, dr_amount=Decimal("20.00"))
    JournalLine.objects.create(book=book, journal_entry=entry5, account=groceries, cr_amount=Decimal("20.00"))

    # An entry with one archived line.
    entry6 = JournalEntry.objects.create(
        book=book,
        entry_date=date(2026, 1, 15),
        payee=freshco,
        description="Groceries",
        source=JournalEntry.SOURCE_BANK_MATCH,
        status=JournalEntry.STATUS_POSTED,
    )
    JournalLine.objects.create(
        book=book, journal_entry=entry6, account=groceries, dr_amount=Decimal("15.00"), is_archived=True
    )
    JournalLine.objects.create(book=book, journal_entry=entry6, account=chequing, cr_amount=Decimal("15.00"))
    BankTransaction.objects.create(
        book=book,
        account=chequing,
        journal_entry=entry6,
        amount=Decimal("15.00"),
        posted_date=date(2026, 1, 15),
        description="FRESHCO #4501",
        merchant_name="FreshCo",
        source=BankTransaction.SOURCE_CSV,
    )

    # A $0.00 entry.
    entry7 = JournalEntry.objects.create(
        book=book,
        entry_date=date(2026, 1, 20),
        description="Zero-amount correction",
        source=JournalEntry.SOURCE_MANUAL,
        status=JournalEntry.STATUS_POSTED,
    )
    JournalLine.objects.create(book=book, journal_entry=entry7, account=chequing, dr_amount=Decimal("0.00"))
    JournalLine.objects.create(book=book, journal_entry=entry7, account=groceries, cr_amount=Decimal("0.00"))

    # A split, written through the real service rather than hand-rolled, so
    # what this fixture holds is exactly what the UI produces
    # (`apps/bank_feed/services/splits.py`). One bank line carrying the total
    # and one counter line per leg -- three lines on one entry, and the legs
    # carry opposite signs (+100.00 spent, -20.00 refunded, against an +80.00
    # total), which is the mixed case that service calls out.
    split_entry = JournalEntry.objects.create(
        book=book,
        entry_date=date(2026, 1, 18),
        description="Costco run",
        source=JournalEntry.SOURCE_BANK_MATCH,
        status=JournalEntry.STATUS_POSTED,
    )
    JournalLine.objects.create(book=book, journal_entry=split_entry, account=groceries, dr_amount=Decimal("80.00"))
    JournalLine.objects.create(
        book=book, journal_entry=split_entry, account=chequing, cr_amount=Decimal("80.00"), is_cleared=True
    )
    split_tx = BankTransaction.objects.create(
        book=book,
        account=chequing,
        journal_entry=split_entry,
        amount=Decimal("80.00"),
        posted_date=date(2026, 1, 18),
        description="COSTCO WHOLESALE",
        merchant_name="Costco",
        source=BankTransaction.SOURCE_CSV,
    )
    apply_splits(
        split_tx,
        [(groceries, Decimal("100.00")), (misc_expense, Decimal("-20.00"))],
        total=Decimal("80.00"),
    )

    # An uncategorized feed row.
    BankTransaction.objects.create(
        book=book,
        account=chequing,
        journal_entry=None,
        amount=Decimal("12.50"),
        posted_date=date(2026, 1, 22),
        description="COFFEE SHOP",
        source=BankTransaction.SOURCE_PLAID,
    )

    # Budgets and a goal contribution/withdrawal.
    Budget.objects.create(book=book, month=date(2026, 1, 1), category=groceries, budget_amount=Decimal("400.00"))
    Budget.objects.create(book=book, month=date(2026, 1, 1), category=paycheck, budget_amount=Decimal("2000.00"))
    GoalAllocation.objects.create(
        book=book, goal=goal, month=date(2026, 1, 1), amount=Decimal("300.00"), notes="paycheck transfer"
    )
    GoalAllocation.objects.create(
        book=book, goal=goal, month=date(2026, 2, 1), amount=Decimal("-100.00"), notes="withdrew for repair"
    )

    handles = {
        "chequing": chequing.id,
        "credit_card": credit_card.id,
        "reconciliation": reconciliation.id,
        "groceries": groceries.id,
        "paycheck": paycheck.id,
        "misc_expense": misc_expense.id,
        "misc_income": misc_income.id,
        "goal_account": goal_account.id,
    }
    return team, user, handles
