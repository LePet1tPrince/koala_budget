"""
Pending -> posted, amended and cancelled transactions.

Plaid reports a pending authorization settling as `removed` (the pending id)
plus `added` (the posted transaction, whose `pending_transaction_id` names the
pending one). These pin what that does to a row the user may already have
categorized or reconciled.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from apps.audit.models import AuditEvent
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.bank_revision import REVISION_OF, bank_amount
from apps.bank_feed.services.categorize import categorize_single
from apps.bank_feed.services.splits import apply_splits
from apps.journal.models import JournalEntry, JournalLine
from apps.plaid.models import PlaidAccount, PlaidTransaction
from apps.plaid.tasks import sync_plaid_transactions
from apps.reconciliation.models import Reconciliation

from .base import PlaidBookTestCase


def balance(account):
    lines = JournalLine.objects.filter(account=account).exclude(journal_entry__status=JournalEntry.STATUS_VOID)
    return sum((line.dr_amount - line.cr_amount for line in lines), Decimal("0"))


class PendingPostedTest(PlaidBookTestCase):
    def tx(self, tx_id, amount="50.00", day=1, pending=False, pending_id=None, name="THE KEG", **extra):
        return {
            "transaction_id": tx_id,
            "account_id": "acc-checking",
            "amount": Decimal(amount),
            "date": date(2026, 10, day),
            "name": name,
            "merchant_name": "The Keg",
            "pending": pending,
            "pending_transaction_id": pending_id,
            "iso_currency_code": "CAD",
            **extra,
        }

    def page(self, added=(), modified=(), removed=(), cursor="c1"):
        return {
            "added": list(added),
            "modified": list(modified),
            "removed": [{"transaction_id": tx_id} for tx_id in removed],
            "next_cursor": cursor,
            "has_more": False,
        }

    def sync(self, **page):
        with patch("apps.plaid.tasks.sync_transactions", return_value=self.page(**page)):
            return sync_plaid_transactions(self.item.id)

    def settle(self, amount="50.00", day=3, **extra):
        """The pending tx-p settles as posted tx-posted."""
        return self.sync(
            added=[self.tx("tx-posted", amount=amount, day=day, pending_id="tx-p", name="THE KEG #12", **extra)],
            removed=["tx-p"],
            cursor="c2",
        )

    def pending_row(self, amount="50.00"):
        self.sync(added=[self.tx("tx-p", amount=amount, pending=True)])
        return BankTransaction.objects.get(plaid_transaction__plaid_transaction_id="tx-p")

    def rows(self):
        return BankTransaction.objects.filter(book=self.book, account=self.checking)

    def reconcile(self, bank_tx, statement_date=None):
        line = bank_tx.journal_entry.lines.get(account=self.checking)
        rec = None
        if statement_date is not None:
            rec = Reconciliation.objects.create(
                book=self.book,
                account=self.checking,
                statement_date=statement_date,
                statement_balance=Decimal("0"),
                status=Reconciliation.STATUS_COMPLETED,
            )
        JournalLine.objects.filter(pk=line.pk).update(is_reconciled=True, reconciliation=rec)

    # --- uncategorized ---------------------------------------------------

    def test_pending_row_is_flagged_pending(self):
        row = self.pending_row()
        self.assertTrue(row.plaid_transaction.pending)

    def test_settling_carries_the_posted_transaction_onto_the_row(self):
        row = self.pending_row()
        result = self.settle(amount="58.00")

        self.assertTrue(result["success"])
        self.assertEqual(self.rows().count(), 1)
        row.refresh_from_db()
        self.assertEqual(row.amount, Decimal("58.00"))
        self.assertEqual(row.posted_date, date(2026, 10, 3))
        self.assertEqual(row.description, "THE KEG #12")
        detail = PlaidTransaction.objects.get(bank_transaction=row)
        self.assertEqual(detail.plaid_transaction_id, "tx-posted")
        self.assertFalse(detail.pending)
        self.assertEqual(detail.pending_transaction_id, "tx-p")

    def test_settlement_outcome_is_audited(self):
        self.pending_row()
        self.settle()
        event = AuditEvent.objects.filter(event_type=AuditEvent.PLAID_SYNC_COMPLETED).latest("id")
        self.assertEqual(event.metadata["outcomes"], {"settled": 1, "removed_skipped": 1})

    def test_settling_twice_is_idempotent(self):
        self.pending_row()
        self.settle()
        self.settle()
        self.assertEqual(self.rows().count(), 1)

    # --- categorized -----------------------------------------------------

    def test_a_categorized_pending_row_keeps_its_category_and_follows_the_amount(self):
        row = self.pending_row()
        categorize_single(row, self.dining)
        row.refresh_from_db()
        row.description = "Dinner with Sam"  # the user's own wording
        row.save()

        self.settle(amount="62.50")

        self.assertEqual(self.rows().count(), 1, "no second, uncategorized row for the posted transaction")
        row.refresh_from_db()
        self.assertEqual(row.amount, Decimal("62.50"))
        self.assertEqual(row.description, "Dinner with Sam")
        entry = row.journal_entry
        self.assertEqual(entry.entry_date, date(2026, 10, 3))
        self.assertEqual(balance(self.dining), Decimal("62.50"))
        self.assertEqual(balance(self.checking), Decimal("-62.50"))
        self.assertEqual(entry.lines.count(), 2)

    def test_same_amount_settlement_only_moves_the_date(self):
        row = self.pending_row()
        categorize_single(row, self.dining)
        entry_id = BankTransaction.objects.get(pk=row.pk).journal_entry_id
        self.settle(amount="50.00", day=4)
        row.refresh_from_db()
        self.assertEqual(row.journal_entry_id, entry_id)
        self.assertEqual(row.posted_date, date(2026, 10, 4))
        self.assertEqual(balance(self.dining), Decimal("50.00"))

    # --- reconciled ------------------------------------------------------

    def test_a_reconciled_row_keeps_its_amount_and_the_difference_arrives_as_its_own_row(self):
        row = self.pending_row()
        categorize_single(row, self.dining)
        row.refresh_from_db()
        self.reconcile(row)

        self.settle(amount="58.00")

        row.refresh_from_db()
        self.assertEqual(row.amount, Decimal("50.00"))
        self.assertTrue(row.journal_entry.lines.get(account=self.checking).is_reconciled)
        diff = BankTransaction.objects.get(**{f"raw__{REVISION_OF}": row.pk})
        self.assertEqual(diff.amount, Decimal("8.00"))
        self.assertIsNone(diff.journal_entry)
        self.assertIn("50.00", diff.description)
        self.assertEqual(bank_amount(row), Decimal("58.00"))

    def test_a_second_revision_adjusts_the_open_difference_row(self):
        row = self.pending_row()
        categorize_single(row, self.dining)
        row.refresh_from_db()
        self.reconcile(row)
        self.settle(amount="58.00")
        self.sync(modified=[self.tx("tx-posted", amount="60.00", day=3)], cursor="c3")

        diffs = BankTransaction.objects.filter(**{f"raw__{REVISION_OF}": row.pk})
        self.assertEqual(diffs.count(), 1)
        self.assertEqual(diffs.get().amount, Decimal("10.00"))

        # And back to the reconciled amount: the difference row goes away.
        self.sync(modified=[self.tx("tx-posted", amount="50.00", day=3)], cursor="c4")
        self.assertFalse(diffs.exists())

    def test_a_reconciled_row_is_not_redated_past_its_statement(self):
        row = self.pending_row()
        categorize_single(row, self.dining)
        row.refresh_from_db()
        self.reconcile(row, statement_date=date(2026, 10, 2))

        self.settle(amount="50.00", day=5)

        row.refresh_from_db()
        self.assertEqual(row.posted_date, date(2026, 10, 1))
        self.assertEqual(row.journal_entry.entry_date, date(2026, 10, 1))

    # --- splits and transfers -------------------------------------------

    def test_a_split_keeps_its_legs_and_the_difference_arrives_as_its_own_row(self):
        row = self.pending_row(amount="100.00")
        categorize_single(row, self.dining)
        row.refresh_from_db()
        apply_splits(row, [(self.dining, Decimal("60.00")), (self.groceries, Decimal("40.00"))], total=Decimal("100"))

        self.settle(amount="110.00")

        row.refresh_from_db()
        self.assertEqual(row.amount, Decimal("100.00"))
        self.assertEqual(balance(self.dining), Decimal("60.00"))
        self.assertEqual(balance(self.groceries), Decimal("40.00"))
        diff = BankTransaction.objects.get(**{f"raw__{REVISION_OF}": row.pk})
        self.assertEqual(diff.amount, Decimal("10.00"))

    def test_a_transfer_moves_its_mirror_leg_with_it(self):
        row = self.pending_row(amount="200.00")
        categorize_single(row, self.savings)  # checking -> savings, both feed accounts
        mirror = BankTransaction.objects.get(account=self.savings, is_transfer_mirror=True)
        self.assertEqual(mirror.amount, Decimal("-200.00"))

        self.settle(amount="250.00", day=2)

        mirror.refresh_from_db()
        self.assertEqual(mirror.amount, Decimal("-250.00"))
        self.assertEqual(mirror.posted_date, date(2026, 10, 2))
        self.assertEqual(balance(self.savings), Decimal("250.00"))
        self.assertEqual(balance(self.checking), Decimal("-250.00"))

    def test_a_transfer_whose_other_side_is_reconciled_carries_the_difference(self):
        row = self.pending_row(amount="200.00")
        categorize_single(row, self.savings)
        row.refresh_from_db()
        JournalLine.objects.filter(journal_entry=row.journal_entry, account=self.savings).update(is_reconciled=True)

        self.settle(amount="250.00")

        row.refresh_from_db()
        self.assertEqual(row.amount, Decimal("200.00"))
        self.assertEqual(balance(self.savings), Decimal("200.00"))
        diff = BankTransaction.objects.get(**{f"raw__{REVISION_OF}": row.pk})
        self.assertEqual(diff.amount, Decimal("50.00"))

    # --- modified --------------------------------------------------------

    def test_modified_carries_the_new_amount_onto_a_categorized_row(self):
        self.sync(added=[self.tx("tx-1", amount="12.50")])
        row = BankTransaction.objects.get(plaid_transaction__plaid_transaction_id="tx-1")
        categorize_single(row, self.groceries)

        self.sync(modified=[self.tx("tx-1", amount="15.00")], cursor="c2")

        row.refresh_from_db()
        self.assertEqual(row.amount, Decimal("15.00"))
        self.assertEqual(balance(self.groceries), Decimal("15.00"))

    # --- cancelled ------------------------------------------------------

    def test_a_cancelled_uncategorized_authorization_disappears(self):
        self.pending_row()
        self.sync(removed=["tx-p"], cursor="c2")
        self.assertFalse(self.rows().exists())

    def test_a_cancelled_categorized_authorization_is_voided(self):
        row = self.pending_row()
        categorize_single(row, self.dining)

        self.sync(removed=["tx-p"], cursor="c2")

        row.refresh_from_db()
        self.assertTrue(row.is_void)
        self.assertEqual(row.journal_entry.status, JournalEntry.STATUS_VOID)
        self.assertEqual(balance(self.dining), Decimal("0"))

    def test_a_cancelled_reconciled_authorization_is_kept(self):
        row = self.pending_row()
        categorize_single(row, self.dining)
        row.refresh_from_db()
        self.reconcile(row)

        with self.assertLogs("apps.plaid.tasks", level="WARNING"):
            self.sync(removed=["tx-p"], cursor="c2")

        row.refresh_from_db()
        self.assertFalse(row.is_void)

    def test_a_voided_pending_row_is_not_revived_by_its_settlement(self):
        """The user (or a cancellation) voided it; the posted transaction arrives as a new row."""
        row = self.pending_row()
        categorize_single(row, self.dining)
        self.sync(removed=["tx-p"], cursor="c2")

        self.sync(added=[self.tx("tx-posted", pending_id="tx-p")], cursor="c3")

        row.refresh_from_db()
        self.assertTrue(row.is_void)
        new_row = BankTransaction.objects.get(plaid_transaction__plaid_transaction_id="tx-posted")
        self.assertIsNone(new_row.journal_entry)
        self.assertFalse(new_row.is_void)

    def test_settlement_lands_even_when_the_removal_comes_first(self):
        """Plaid may order the lists either way; added is always applied first."""
        self.pending_row()
        with patch(
            "apps.plaid.tasks.sync_transactions",
            side_effect=[
                {**self.page(removed=["tx-p"]), "has_more": True},
                self.page(added=[self.tx("tx-posted", pending_id="tx-p")], cursor="c2"),
            ],
        ):
            sync_plaid_transactions(self.item.id)
        self.assertEqual(self.rows().count(), 1)
        self.assertEqual(
            self.rows().get().plaid_transaction.plaid_transaction_id,
            "tx-posted",
        )

    def test_another_items_pending_id_is_not_claimed(self):
        other_item = type(self.item).objects.create(
            book=self.book, plaid_item_id="item-2", access_token="t2", institution_name="TD"
        )
        PlaidAccount.objects.create(
            book=self.book, item=other_item, plaid_account_id="acc-x", name="x", subtype="checking", type="depository"
        )
        self.pending_row()
        with patch(
            "apps.plaid.tasks.sync_transactions",
            return_value=self.page(added=[{**self.tx("tx-posted", pending_id="tx-p"), "account_id": "acc-x"}]),
        ):
            sync_plaid_transactions(other_item.id)
        self.assertTrue(PlaidTransaction.objects.filter(plaid_transaction_id="tx-p").exists())
