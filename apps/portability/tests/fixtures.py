"""
Hand-built row dicts covering the awkward corners named in
`docs/export-import-plan.md` §7 Phase 1: a void entry, an archived line, a
reconciled transfer (one entry, two feed-account lines, one of them the
synthetic mirror), a goal with allocations including a negative one (a
withdrawal), a system account, a $0.00 entry, and two accounts sharing a name
across different types.

Built as plain data, not through a live database -- `schema.py`/`read.py`/
`write.py` are pure and Phase 1 has nothing that queries a team yet (that is
`export.py`, Phase 2). One deliberate omission: an *empty* account group has
no row of its own in `accounts.csv` (§2.1 denormalises groups onto the
accounts that use them), so it cannot be represented at this layer -- it is a
fact about what `export.py` counts into `omitted`, not about what a row here
looks like, and belongs to that phase's tests instead.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def account(account_id: int, name: str, account_type: str, group_name: str, **overrides) -> dict:
    row = {
        "account_id": account_id,
        "name": name,
        "account_type": account_type,
        "group_name": group_name,
        "group_description": "",
        "group_is_system": False,
        "group_sort_order": 0,
        "group_is_archived": False,
        "group_archived_at": None,
        "institution": None,
        "institution_is_archived": None,
        "institution_archived_at": None,
        "has_feed": False,
        "is_system": False,
        "sort_order": 0,
        "is_archived": False,
        "archived_at": None,
        "goal_name": None,
        "goal_description": "",
        "goal_target_amount": None,
        "goal_target_date": None,
        "goal_is_complete": None,
        "goal_is_archived": None,
        "goal_archived_at": None,
        "goal_closed_at": None,
        "goal_order": None,
    }
    row.update(overrides)
    return row


def journal_row(**overrides) -> dict:
    row = {
        "entry_id": None,
        "entry_date": None,
        "payee": None,
        "description": "",
        "source": "",
        "status": "posted",
        "account_id": None,
        "account_name": "",
        "entry_is_archived": False,
        "entry_archived_at": None,
        "dr_amount": Decimal("0.00"),
        "cr_amount": Decimal("0.00"),
        "is_cleared": False,
        "is_reconciled": False,
        "is_archived": False,
        "archived_at": None,
        "reconciliation_id": None,
        "feed_source": None,
        "feed_amount": None,
        "feed_posted_date": None,
        "feed_description": "",
        "feed_merchant": None,
        "feed_is_mirror": False,
        "feed_is_archived": False,
        "feed_archived_at": None,
    }
    row.update(overrides)
    return row


def budget_row(**overrides) -> dict:
    row = {
        "kind": "budget",
        "month": date(2026, 1, 1),
        "account_id": None,
        "account_name": "",
        "amount": Decimal("0.00"),
        "notes": "",
        "is_archived": False,
        "archived_at": None,
    }
    row.update(overrides)
    return row


def build_fixture_tables() -> tuple[list[dict], list[dict], list[dict]]:
    """One team's worth of every corner named above. Returns (accounts, journal_rows, budget_rows)."""

    accounts = [
        account(1, "Chequing", "asset", "Chequing", has_feed=True),
        account(2, "Credit Card", "liability", "Credit Cards", has_feed=True),
        account(
            3,
            "Reconciliation Adjustments",
            "goal",
            "Equity Adjustments",
            is_system=True,
        ),
        account(4, "Groceries", "expense", "Household"),
        account(5, "Paycheck", "income", "Employment Income"),
        account(
            6,
            "Goal: New Deck",
            "goal",
            "Goals",
            goal_name="New Deck",
            goal_description="",
            goal_target_amount=Decimal("5000.00"),
            goal_target_date=date(2027, 6, 1),
            goal_is_complete=False,
            goal_is_archived=False,
            goal_order=0,
        ),
        # Two accounts sharing a name across different types (§2.2 -- Account
        # has no name-uniqueness constraint, unlike AccountGroup/Institution/
        # Payee, so the format must key by account_id, never by name).
        account(10, "Misc", "expense", "Household"),
        account(11, "Misc", "income", "Other Income"),
    ]

    journal_rows = [
        # An ordinary categorised transaction, feed row on the bank leg only.
        journal_row(
            entry_id=100,
            entry_date=date(2026, 1, 5),
            payee="FreshCo",
            description="Groceries",
            source="bank_match",
            status="posted",
            account_id=4,
            account_name="Groceries",
            dr_amount=Decimal("84.12"),
            cr_amount=Decimal("0.00"),
            is_cleared=True,
        ),
        journal_row(
            entry_id=100,
            entry_date=date(2026, 1, 5),
            payee="FreshCo",
            description="Groceries",
            source="bank_match",
            status="posted",
            account_id=1,
            account_name="Chequing",
            dr_amount=Decimal("0.00"),
            cr_amount=Decimal("84.12"),
            is_cleared=True,
            feed_source="csv",
            feed_amount=Decimal("84.12"),
            feed_posted_date=date(2026, 1, 5),
            feed_description="FRESHCO #4417",
            feed_merchant="FreshCo",
        ),
        # A reconciled transfer: two feed-account lines on one entry, one of
        # them the synthetic mirror leg (feed_is_mirror), the reconciled flag
        # on the primary side (`transfer_mirror.linked_legs` treats either
        # side's reconciled state as reconciling the transfer).
        journal_row(
            entry_id=200,
            entry_date=date(2026, 1, 10),
            payee=None,
            description="Credit card payment",
            source="manual",
            status="posted",
            account_id=2,
            account_name="Credit Card",
            dr_amount=Decimal("50.00"),
            cr_amount=Decimal("0.00"),
            is_cleared=True,
            is_reconciled=True,
            feed_source="system",
            feed_amount=Decimal("50.00"),
            feed_posted_date=date(2026, 1, 10),
            feed_description="Credit card payment",
            feed_is_mirror=True,
        ),
        journal_row(
            entry_id=200,
            entry_date=date(2026, 1, 10),
            payee=None,
            description="Credit card payment",
            source="manual",
            status="posted",
            account_id=1,
            account_name="Chequing",
            dr_amount=Decimal("0.00"),
            cr_amount=Decimal("50.00"),
            is_cleared=True,
            feed_source="csv",
            feed_amount=Decimal("50.00"),
            feed_posted_date=date(2026, 1, 10),
            feed_description="ONLINE XFER",
            feed_merchant=None,
        ),
        # A void entry -- excluded from every balance, but kept as evidence
        # (D6): a miscategorised transaction the user voided rather than
        # deleted.
        journal_row(
            entry_id=300,
            entry_date=date(2026, 1, 12),
            payee=None,
            description="Entered in error",
            source="manual",
            status="void",
            account_id=1,
            account_name="Chequing",
            dr_amount=Decimal("20.00"),
            cr_amount=Decimal("0.00"),
        ),
        journal_row(
            entry_id=300,
            entry_date=date(2026, 1, 12),
            payee=None,
            description="Entered in error",
            source="manual",
            status="void",
            account_id=4,
            account_name="Groceries",
            dr_amount=Decimal("0.00"),
            cr_amount=Decimal("20.00"),
        ),
        # An entry with one archived line (JournalLine.is_archived -- distinct
        # from feed_is_archived on the same row, and from entry_is_archived).
        journal_row(
            entry_id=400,
            entry_date=date(2026, 1, 15),
            payee="FreshCo",
            description="Groceries",
            source="bank_match",
            status="posted",
            account_id=4,
            account_name="Groceries",
            dr_amount=Decimal("15.00"),
            cr_amount=Decimal("0.00"),
            is_archived=True,
        ),
        journal_row(
            entry_id=400,
            entry_date=date(2026, 1, 15),
            payee="FreshCo",
            description="Groceries",
            source="bank_match",
            status="posted",
            account_id=1,
            account_name="Chequing",
            dr_amount=Decimal("0.00"),
            cr_amount=Decimal("15.00"),
            feed_source="csv",
            feed_amount=Decimal("15.00"),
            feed_posted_date=date(2026, 1, 15),
            feed_description="FRESHCO #4501",
            feed_merchant="FreshCo",
        ),
        # A $0.00 entry -- both lines zero, balances trivially (0 == 0). See
        # §2.6: real data can contain one, since the bulk-insert paths skip
        # `full_clean`'s "must be non-zero" check.
        journal_row(
            entry_id=500,
            entry_date=date(2026, 1, 20),
            payee=None,
            description="Zero-amount correction",
            source="manual",
            status="posted",
            account_id=1,
            account_name="Chequing",
            dr_amount=Decimal("0.00"),
            cr_amount=Decimal("0.00"),
        ),
        journal_row(
            entry_id=500,
            entry_date=date(2026, 1, 20),
            payee=None,
            description="Zero-amount correction",
            source="manual",
            status="posted",
            account_id=4,
            account_name="Groceries",
            dr_amount=Decimal("0.00"),
            cr_amount=Decimal("0.00"),
        ),
        # A split: one bank line carrying the total, one counter line per leg
        # (`apps/bank_feed/services/splits.py`). Three lines on one entry, so
        # every place this format groups lines by entry has to cope with more
        # than two -- and the legs carry *opposite* signs (a +100.00 purchase
        # with a -20.00 refund against an +80.00 total), which is the mixed
        # case that service calls out and the one a naive "debit leg, credit
        # leg" reading gets wrong.
        journal_row(
            entry_id=700,
            entry_date=date(2026, 1, 18),
            description="Costco run",
            source="bank_match",
            status="posted",
            account_id=4,
            account_name="Groceries",
            dr_amount=Decimal("100.00"),
            cr_amount=Decimal("0.00"),
        ),
        journal_row(
            entry_id=700,
            entry_date=date(2026, 1, 18),
            description="Costco run",
            source="bank_match",
            status="posted",
            account_id=10,
            account_name="Misc",
            dr_amount=Decimal("0.00"),
            cr_amount=Decimal("20.00"),
        ),
        journal_row(
            entry_id=700,
            entry_date=date(2026, 1, 18),
            description="Costco run",
            source="bank_match",
            status="posted",
            account_id=1,
            account_name="Chequing",
            dr_amount=Decimal("0.00"),
            cr_amount=Decimal("80.00"),
            is_cleared=True,
            feed_source="csv",
            feed_amount=Decimal("80.00"),
            feed_posted_date=date(2026, 1, 18),
            feed_description="COSTCO WHOLESALE",
            feed_merchant="Costco",
        ),
        # An uncategorized bank-feed row -- no entry at all (§2.4).
        journal_row(
            status="uncategorized",
            account_id=1,
            account_name="Chequing",
            feed_source="plaid",
            feed_amount=Decimal("12.50"),
            feed_posted_date=date(2026, 1, 22),
            feed_description="COFFEE SHOP",
        ),
    ]

    budget_rows = [
        budget_row(
            kind="budget", month=date(2026, 1, 1), account_id=4, account_name="Groceries", amount=Decimal("400.00")
        ),
        budget_row(
            kind="budget", month=date(2026, 1, 1), account_id=5, account_name="Paycheck", amount=Decimal("2000.00")
        ),
        # A goal contribution, and a withdrawal the same month range (§D of
        # the plan -- GoalAllocation.amount may be negative).
        budget_row(
            kind="goal",
            month=date(2026, 1, 1),
            account_id=6,
            account_name="Goal: New Deck",
            amount=Decimal("300.00"),
            notes="paycheck transfer",
        ),
        budget_row(
            kind="goal",
            month=date(2026, 2, 1),
            account_id=6,
            account_name="Goal: New Deck",
            amount=Decimal("-100.00"),
            notes="withdrew for repair",
        ),
    ]

    return accounts, journal_rows, budget_rows
