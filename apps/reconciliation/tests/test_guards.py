"""
Phase 0: a reconciled line stays reconciled.

The first three tests reproduce defects that returned HTTP 200 on the code this
feature started from (docs/statement-reconciliation-plan.md §3).
"""

from datetime import date
from decimal import Decimal

from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry
from apps.reconciliation.models import Reconciliation

from .base import ReconciliationTestCase


class TransferCounterpartTests(ReconciliationTestCase):
    def _transfer(self):
        """Chequing pays $100 to the card; the card side is reconciled."""
        tx = self.feed_tx(self.chequing, "100.00", on=date(2026, 8, 10), description="Card payment")
        resp = self.api("post", "bankfeed/api/feed/categorize/", {"rows": [{"id": tx.id}], "category_id": self.card.id})
        self.assertEqual(resp.status_code, 204)
        tx.refresh_from_db()
        tx.journal_entry.lines.filter(account=self.card).update(is_reconciled=True)
        return tx

    def _put(self, tx, **overrides):
        body = {
            "date": "2026-08-10",
            "category": self.card.id,
            "outflow": "100.00",
            "account": self.chequing.id,
            "description": "Card payment",
        }
        body.update(overrides)
        return self.api("put", f"bankfeed/api/feed/{tx.id}/", body)

    def test_editing_one_side_keeps_the_other_side_reconciled(self):
        tx = self._transfer()
        resp = self._put(tx, description="Renamed only")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(tx.journal_entry.lines.get(account=self.card).is_reconciled)

    def test_editing_the_mirror_keeps_the_primary_reconciled(self):
        tx = self._transfer()
        tx.journal_entry.lines.update(is_reconciled=False)
        tx.journal_entry.lines.filter(account=self.chequing).update(is_reconciled=True)
        mirror = BankTransaction.objects.get(journal_entry=tx.journal_entry, is_transfer_mirror=True)
        resp = self.api(
            "put",
            f"bankfeed/api/feed/{mirror.id}/",
            {
                "date": "2026-08-10",
                "category": self.chequing.id,
                "inflow": "100.00",
                "account": self.card.id,
                "description": "Payment received",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(tx.journal_entry.lines.get(account=self.chequing).is_reconciled)

    def test_repointing_a_transfer_with_a_reconciled_other_side_is_refused(self):
        tx = self._transfer()
        resp = self._put(tx, category=self.savings.id)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("other side of this transfer", resp.json()["error"])
        self.assertTrue(tx.journal_entry.lines.get(account=self.card).is_reconciled)

    def test_changing_the_amount_of_a_transfer_with_a_reconciled_other_side_is_refused(self):
        tx = self._transfer()
        resp = self._put(tx, outflow="120.00")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(tx.journal_entry.lines.get(account=self.card).cr_amount, Decimal("0"))
        self.assertEqual(tx.journal_entry.lines.get(account=self.card).dr_amount, Decimal("100.00"))

    def test_bulk_recategorizing_a_reconciled_other_side_is_refused(self):
        tx = self._transfer()
        resp = self.api(
            "post", "bankfeed/api/feed/categorize/", {"rows": [{"id": tx.id}], "category_id": self.groceries.id}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(tx.journal_entry.lines.filter(account=self.card, is_reconciled=True).exists())

    def test_batch_edit_category_is_all_or_nothing(self):
        tx = self._transfer()
        other = self.feed_tx(self.chequing, "5.00", description="Other")
        resp = self.api(
            "patch", "bankfeed/api/feed/batch_edit/", {"ids": [other.id, tx.id], "category_id": self.groceries.id}
        )
        self.assertEqual(resp.status_code, 400)
        other.refresh_from_db()
        self.assertIsNone(other.journal_entry_id)

    def test_decategorizing_a_transfer_with_a_reconciled_other_side_is_refused(self):
        tx = self._transfer()
        resp = self._put(tx, category=None)
        self.assertEqual(resp.status_code, 400)
        tx.refresh_from_db()
        self.assertIsNotNone(tx.journal_entry_id)


class MoveAndRedateTests(ReconciliationTestCase):
    def _reconciled_row(self, statement=None):
        line = self.entry(self.chequing, self.groceries, "-40.00", on=date(2026, 8, 20), reconciled=True, feed=True)
        if statement is not None:
            line.reconciliation = statement
            line.save()
        return BankTransaction.objects.get(journal_entry=line.journal_entry)

    def _statement(self):
        return Reconciliation.objects.create(
            team=self.team,
            account=self.chequing,
            statement_date=date(2026, 8, 31),
            statement_balance=Decimal("-40.00"),
            status=Reconciliation.STATUS_COMPLETED,
            cleared_total=Decimal("-40.00"),
        )

    def _put(self, tx, **overrides):
        body = {
            "date": "2026-08-20",
            "category": self.groceries.id,
            "outflow": "40.00",
            "account": self.chequing.id,
            "description": "Tx",
        }
        body.update(overrides)
        return self.api("put", f"bankfeed/api/feed/{tx.id}/", body)

    def test_moving_a_reconciled_row_to_another_account_is_refused(self):
        tx = self._reconciled_row()
        resp = self._put(tx, account=self.savings.id)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("another account", resp.json()["error"])
        self.assertTrue(tx.journal_entry.lines.filter(account=self.chequing, is_reconciled=True).exists())
        self.assertFalse(tx.journal_entry.lines.filter(account=self.savings).exists())

    def test_redating_past_the_statement_is_refused(self):
        tx = self._reconciled_row(self._statement())
        resp = self._put(tx, date="2026-09-02")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("2026-08-31", resp.json()["error"])
        self.assertEqual(JournalEntry.objects.get(pk=tx.journal_entry_id).entry_date, date(2026, 8, 20))

    def test_redating_within_the_statement_period_is_allowed(self):
        tx = self._reconciled_row(self._statement())
        self.assertEqual(self._put(tx, date="2026-08-25").status_code, 200)

    def test_redating_a_line_reconciled_before_statements_existed_is_allowed(self):
        tx = self._reconciled_row()
        self.assertEqual(self._put(tx, date="2026-09-02").status_code, 200)

    def test_batch_edit_redating_past_the_statement_is_refused(self):
        tx = self._reconciled_row(self._statement())
        resp = self.api("patch", "bankfeed/api/feed/batch_edit/", {"ids": [tx.id], "date": "2026-09-05"})
        self.assertEqual(resp.status_code, 400)
        tx.refresh_from_db()
        self.assertEqual(tx.posted_date, date(2026, 8, 20))


class JournalApiTests(ReconciliationTestCase):
    def test_voiding_a_reconciled_entry_is_refused(self):
        line = self.entry(self.chequing, self.groceries, "-40.00", reconciled=True)
        resp = self.api("post", f"journal/api/journal-entries/{line.journal_entry_id}/void_entry/")
        self.assertEqual(resp.status_code, 400)
        line.journal_entry.refresh_from_db()
        self.assertEqual(line.journal_entry.status, JournalEntry.STATUS_POSTED)

    def test_voiding_an_unreconciled_entry_still_works(self):
        line = self.entry(self.chequing, self.groceries, "-40.00")
        resp = self.api("post", f"journal/api/journal-entries/{line.journal_entry_id}/void_entry/")
        self.assertEqual(resp.status_code, 200)

    def test_replacing_the_lines_of_a_reconciled_entry_is_refused(self):
        line = self.entry(self.chequing, self.groceries, "-40.00", reconciled=True)
        resp = self.api(
            "patch",
            f"journal/api/journal-entries/{line.journal_entry_id}/",
            {
                "lines": [
                    {"account": self.chequing.id, "dr_amount": "0", "cr_amount": "40.00"},
                    {"account": self.coffee.id, "dr_amount": "40.00", "cr_amount": "0"},
                ]
            },
        )
        self.assertEqual(resp.status_code, 400)
        line.refresh_from_db()
        self.assertTrue(line.is_reconciled)

    def test_quick_reconcile_endpoint_is_gone(self):
        resp = self.api("post", "bankfeed/api/feed/batch_reconcile/", {"ids": []})
        self.assertIn(resp.status_code, (404, 405))
