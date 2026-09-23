"""The reconciliation session: signs, candidates, ticking, finishing, undoing, integrity."""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent, AuditLog
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry
from apps.reconciliation.models import Reconciliation
from apps.reconciliation.services import candidates, integrity, session
from apps.reconciliation.services.adjustment import OFFSET_ACCOUNT_NAME
from apps.reconciliation.services.session import ReconciliationError, StaleDifference
from apps.reconciliation.services.signs import to_ledger, to_statement

from .base import ReconciliationTestCase

D = Decimal


class SignTests(ReconciliationTestCase):
    def test_asset_statement_sign_is_ledger_sign(self):
        self.assertEqual(to_statement(self.chequing, D("4182.19")), D("4182.19"))
        self.assertEqual(to_ledger(self.chequing, D("-12.75")), D("-12.75"))

    def test_liability_statement_sign_is_amount_owed(self):
        self.assertEqual(to_statement(self.card, D("-1234.56")), D("1234.56"))
        self.assertEqual(to_ledger(self.card, D("1234.56")), D("-1234.56"))


class ChequingExampleTests(ReconciliationTestCase):
    """docs/statement-reconciliation-plan.md §6.1, chequing."""

    def setUp(self):
        super().setUp()
        # Opening: a Jul 31 statement at 3,904.11.
        self.july = self.entry(self.chequing, self.salary, "3904.11", on=date(2026, 7, 1), reconciled=True)
        self.previous = Reconciliation.objects.create(
            team=self.team,
            account=self.chequing,
            statement_date=date(2026, 7, 31),
            statement_balance=D("3904.11"),
            status=Reconciliation.STATUS_COMPLETED,
            cleared_total=D("3904.11"),
        )
        self.july.reconciliation = self.previous
        self.july.save()
        self.pay = self.entry(self.chequing, self.salary, "2450.00", on=date(2026, 8, 1), description="Paycheque")
        self.rent = self.entry(self.chequing, self.groceries, "-1800.00", on=date(2026, 8, 2), description="Rent")
        self.costco = self.entry(self.chequing, self.groceries, "-359.17", on=date(2026, 8, 12), description="Costco")
        self.latte = self.entry(self.chequing, self.coffee, "-12.75", on=date(2026, 8, 30), description="Coffee")
        self.dupe = self.entry(self.chequing, self.coffee, "-12.75", on=date(2026, 8, 30), description="Coffee")
        self.draft = session.start(self.chequing, date(2026, 8, 31), D("4182.19"), self.user)

    def _ids(self, *lines):
        return [line.id for line in lines]

    def test_opening_is_the_reconciled_balance(self):
        self.assertEqual(candidates.summary(self.draft).opening, D("3904.11"))

    def test_all_five_ticked_is_off_by_the_duplicate(self):
        session.tick(self.draft, self._ids(self.pay, self.rent, self.costco, self.latte, self.dupe), True)
        current = candidates.summary(self.draft)
        self.assertEqual(current.opening + current.ticked_total, D("4169.44"))
        self.assertEqual(current.difference, D("12.75"))

    def test_untick_the_duplicate_and_finish_at_zero(self):
        session.tick(self.draft, self._ids(self.pay, self.rent, self.costco, self.latte), True)
        self.assertEqual(candidates.summary(self.draft).difference, D("0"))
        rec = session.finish(self.draft, self.user)

        self.assertEqual(rec.status, Reconciliation.STATUS_COMPLETED)
        self.assertEqual(rec.cleared_total, D("2450.00") - D("1800.00") - D("359.17") - D("12.75"))
        self.assertEqual(rec.opening_balance, D("3904.11"))
        self.assertEqual(rec.adjustment_amount, D("0"))
        for line in (self.pay, self.rent, self.costco, self.latte):
            line.refresh_from_db()
            self.assertTrue(line.is_reconciled)
            self.assertEqual(line.reconciliation_id, rec.id)
        self.dupe.refresh_from_db()
        self.assertFalse(self.dupe.is_reconciled)
        self.assertEqual(candidates.reconciled_balance(self.chequing), D("4182.19"))
        self.assertTrue(integrity.is_intact(rec))
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.RECONCILIATION_COMPLETED).exists())

    def test_finishing_writes_an_audit_row_per_line(self):
        session.tick(self.draft, self._ids(self.pay, self.rent, self.costco, self.latte), True)
        before = AuditLog.objects.count()
        session.finish(self.draft, self.user)
        self.assertGreaterEqual(AuditLog.objects.count() - before, 4)

    def test_finish_with_a_difference_needs_an_explicit_adjustment(self):
        session.tick(self.draft, self._ids(self.pay, self.rent, self.costco, self.latte, self.dupe), True)
        with self.assertRaises(ReconciliationError):
            session.finish(self.draft, self.user)
        with self.assertRaises(StaleDifference):
            session.finish(self.draft, self.user, adjust=True, expected_difference=D("1.00"))

    def test_finish_with_adjustment_debits_the_asset(self):
        session.tick(self.draft, self._ids(self.pay, self.rent, self.costco, self.latte, self.dupe), True)
        rec = session.finish(self.draft, self.user, adjust=True, expected_difference=D("12.75"))
        entry = JournalEntry.objects.get(source=JournalEntry.SOURCE_RECONCILIATION)
        bank_line = entry.lines.get(account=self.chequing)
        self.assertEqual((bank_line.dr_amount, bank_line.cr_amount), (D("12.75"), D("0")))
        self.assertTrue(bank_line.is_reconciled)
        self.assertEqual(bank_line.reconciliation_id, rec.id)
        self.assertEqual(entry.lines.exclude(account=self.chequing).get().account.name, OFFSET_ACCOUNT_NAME)
        # Chequing has a feed, so the adjustment shows there.
        self.assertTrue(BankTransaction.objects.filter(journal_entry=entry, amount=D("-12.75")).exists())
        self.assertEqual(candidates.reconciled_balance(self.chequing), D("4182.19"))
        self.assertTrue(integrity.is_intact(rec))

    def test_statement_date_must_follow_the_last_statement(self):
        self.draft.delete()
        with self.assertRaises(ReconciliationError):
            session.start(self.chequing, date(2026, 7, 31), D("0"), self.user)

    def test_second_start_joins_the_open_draft(self):
        again = session.start(self.chequing, date(2026, 9, 30), D("1"), self.member)
        self.assertEqual(again.id, self.draft.id)
        self.assertEqual(again.statement_date, date(2026, 8, 31))

    def test_only_one_draft_per_account_at_database_level(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reconciliation.objects.create(
                team=self.team, account=self.chequing, statement_date=date(2026, 9, 30), statement_balance=D("0")
            )

    def test_tick_through_ticks_by_date(self):
        ids = session.tick_through(self.draft, date(2026, 8, 12))
        self.assertEqual(set(ids), set(self._ids(self.pay, self.rent, self.costco)))

    def test_tick_is_idempotent_and_untick_releases(self):
        session.tick(self.draft, [self.pay.id], True)
        session.tick(self.draft, [self.pay.id], True)
        self.assertEqual(candidates.summary(self.draft).ticked_count, 1)
        session.tick(self.draft, [self.pay.id], False)
        self.pay.refresh_from_db()
        self.assertIsNone(self.pay.reconciliation_id)

    def test_discard_releases_ticks(self):
        session.tick(self.draft, [self.pay.id], True)
        session.discard(self.draft)
        self.pay.refresh_from_db()
        self.assertIsNone(self.pay.reconciliation_id)

    def _finish_august(self):
        session.tick(self.draft, self._ids(self.pay, self.rent, self.costco, self.latte, self.dupe), True)
        return session.finish(self.draft, self.user, adjust=True, expected_difference=D("12.75"))

    def test_undo_unreconciles_keeps_links_and_voids_the_adjustment(self):
        rec = self._finish_august()
        session.undo(rec, self.user)
        rec.refresh_from_db()
        self.assertEqual(rec.status, Reconciliation.STATUS_UNDONE)
        self.pay.refresh_from_db()
        self.assertFalse(self.pay.is_reconciled)
        self.assertEqual(self.pay.reconciliation_id, rec.id)
        adjustment = JournalEntry.objects.get(source=JournalEntry.SOURCE_RECONCILIATION)
        self.assertEqual(adjustment.status, JournalEntry.STATUS_VOID)
        self.assertTrue(BankTransaction.objects.get(journal_entry=adjustment).is_archived)
        self.assertEqual(candidates.reconciled_balance(self.chequing), D("3904.11"))

    def test_any_statement_can_be_undone_not_only_the_latest(self):
        august = self._finish_august()
        self.entry(self.chequing, self.salary, "100.00", on=date(2026, 9, 5), description="Sept")
        september = session.start(self.chequing, date(2026, 9, 30), D("4282.19"), self.user)
        session.tick_through(september, date(2026, 9, 30))
        session.finish(september, self.user)

        session.undo(self.previous, self.user)  # the oldest one
        self.previous.refresh_from_db()
        self.assertEqual(self.previous.status, Reconciliation.STATUS_UNDONE)
        # Later statements' own lines are untouched, so they stay intact.
        self.assertTrue(integrity.is_intact(august))
        # The reconciled balance fell by what the undone statement locked, and drift names it.
        found = integrity.drift(self.chequing)
        self.assertEqual(found.amount, D("-3904.11"))
        self.assertEqual([line.id for line in found.lines], [self.july.id])

    def test_unreconciling_a_line_marks_its_statement_changed_and_drift_names_it(self):
        rec = self._finish_august()
        self.rent.refresh_from_db()
        self.rent.is_reconciled = False
        self.rent.save()
        self.assertFalse(integrity.is_intact(rec))
        self.assertEqual([line.id for line in integrity.moved_lines(rec)], [self.rent.id])
        found = integrity.drift(self.chequing)
        self.assertEqual(found.amount, D("1800.00"))
        self.assertEqual([line.id for line in found.lines], [self.rent.id])
        # It is a candidate again for the next statement.
        nxt = session.start(self.chequing, date(2026, 9, 30), D("4182.19"), self.user)
        self.assertIn(self.rent.id, set(candidates.candidate_lines(nxt).values_list("id", flat=True)))


class CandidateTests(ReconciliationTestCase):
    def setUp(self):
        super().setUp()
        self.draft = session.start(self.chequing, date(2026, 8, 31), D("0"), self.user)

    def _candidate_ids(self, **kwargs):
        return set(candidates.visible_lines(self.draft, **kwargs).values_list("id", flat=True))

    def test_exclusions(self):
        keep = self.entry(self.chequing, self.groceries, "-10.00")
        reconciled = self.entry(self.chequing, self.groceries, "-11.00", reconciled=True)
        other_account = self.entry(self.savings, self.groceries, "-12.00")
        voided = self.entry(self.chequing, self.groceries, "-13.00")
        JournalEntry.objects.filter(pk=voided.journal_entry_id).update(status=JournalEntry.STATUS_VOID)
        archived = self.entry(self.chequing, self.groceries, "-14.00", feed=True)
        BankTransaction.objects.filter(journal_entry=archived.journal_entry).update(is_archived=True)

        ids = self._candidate_ids()
        self.assertIn(keep.id, ids)
        for line in (reconciled, other_account, voided, archived):
            self.assertNotIn(line.id, ids)

    def test_later_lines_need_include_later(self):
        late = self.entry(self.chequing, self.groceries, "-10.00", on=date(2026, 9, 20))
        near = self.entry(self.chequing, self.groceries, "-10.00", on=date(2026, 9, 3))
        self.assertIn(near.id, self._candidate_ids())
        self.assertNotIn(late.id, self._candidate_ids())
        self.assertIn(late.id, self._candidate_ids(include_later=True))

    def test_ticking_a_non_candidate_is_refused(self):
        other = self.entry(self.savings, self.groceries, "-12.00")
        with self.assertRaises(ReconciliationError):
            session.tick(self.draft, [other.id], True)

    def test_uncategorized_feed_rows_are_reported_in_statement_sign(self):
        row = self.feed_tx(self.chequing, "25.00", on=date(2026, 8, 3))
        rows = list(candidates.uncategorized_rows(self.draft))
        self.assertEqual(rows, [row])
        self.assertEqual(candidates.feed_row_statement_amount(self.chequing, row), D("-25.00"))
        self.assertEqual(candidates.feed_row_statement_amount(self.card, row), D("25.00"))

    def test_opening_balance_lines_are_candidates(self):
        opening = self.entry(self.chequing, self.salary, "500.00", on=date(2026, 1, 1), description="Opening balance")
        self.assertIn(opening.id, self._candidate_ids())

    def test_income_and_system_accounts_cannot_be_reconciled(self):
        with self.assertRaises(ReconciliationError):
            session.start(self.salary, date(2026, 8, 31), D("0"), self.user)


class CreditCardExampleTests(ReconciliationTestCase):
    """docs/statement-reconciliation-plan.md §6.1, credit card."""

    def test_balance_owed_is_entered_as_printed(self):
        self.entry(self.card, self.groceries, "-1000.00", on=date(2026, 7, 5), reconciled=True)
        charge = self.entry(self.card, self.groceries, "-284.56", on=date(2026, 8, 5))
        payment = self.entry(self.card, self.chequing, "50.00", on=date(2026, 8, 20))
        draft = session.start(self.card, date(2026, 8, 31), D("1234.56"), self.user)
        session.tick(draft, [charge.id, payment.id], True)
        current = candidates.summary(draft)
        self.assertEqual(current.as_statement(self.card)["difference"], D("0"))
        self.assertEqual(current.as_statement(self.card)["opening"], D("1000.00"))
        session.finish(draft, self.user)

    def test_card_adjustment_credits_the_card(self):
        charge = self.entry(self.card, self.groceries, "-100.00", on=date(2026, 8, 5))
        # The statement says 112.75 owed: 12.75 more than Koala knows about.
        draft = session.start(self.card, date(2026, 8, 31), D("112.75"), self.user)
        session.tick(draft, [charge.id], True)
        self.assertEqual(candidates.summary(draft).as_statement(self.card)["difference"], D("12.75"))
        session.finish(draft, self.user, adjust=True, expected_difference=D("12.75"))
        line = JournalEntry.objects.get(source=JournalEntry.SOURCE_RECONCILIATION).lines.get(account=self.card)
        self.assertEqual((line.dr_amount, line.cr_amount), (D("0"), D("12.75")))
        self.assertEqual(to_statement(self.card, candidates.reconciled_balance(self.card)), D("112.75"))

    def test_non_feed_account_adjustment_creates_no_feed_row(self):
        line = self.entry(self.cash, self.groceries, "-20.00")
        draft = session.start(self.cash, date(2026, 8, 31), D("-25.00"), self.user)
        session.tick(draft, [line.id], True)
        session.finish(draft, self.user, adjust=True, expected_difference=D("-5.00"))
        entry = JournalEntry.objects.get(source=JournalEntry.SOURCE_RECONCILIATION)
        self.assertFalse(BankTransaction.objects.filter(journal_entry=entry).exists())
