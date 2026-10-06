"""
Tests for matching a duplicate transfer: the rule that picks which leg is kept
(`propose`) and the endpoint that applies it (`transfers/match`).

A match must leave one journal entry with a line on each account, visible in both
feeds, and never void or move a reconciled line.
"""

from datetime import date
from decimal import Decimal

from rest_framework import status

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.bank_feed.models import BankTransaction, TransferMatchDismissal
from apps.bank_feed.services.transfer_match import propose
from apps.bank_feed.services.transfer_mirror import sync_transfer
from apps.books.context import current_book
from apps.journal.models import JournalEntry
from apps.teams.models import Team

from .test_transfers import TransferTestBase


class MatchTestBase(TransferTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        expense_group = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.misc = Account.objects.create(book=cls.book, name="Misc", account_group=expense_group)

    def _reconcile(self, tx, account=None):
        """Reconcile `tx`'s line on `account` (default: its own bank line)."""
        line = tx.journal_entry.lines.get(account=account or tx.account)
        line.is_reconciled = True
        line.save()
        return line

    def _split(self, tx, legs):
        """Give `tx` a split entry: its bank line plus one line per (account, amount)."""
        entry = self._categorize_as_transfer(tx, legs[0][0])
        entry.lines.exclude(account=tx.account).delete()
        for account, amount in legs:
            entry.lines.create(book=self.book, account=account, dr_amount=Decimal(amount), cr_amount=Decimal("0"))
        return entry

    def proposal(self, outflow, inflow):
        for tx in (outflow, inflow):
            tx.refresh_from_db()
        with current_book(self.book):
            return propose(outflow, inflow)


class ProposeTest(MatchTestBase):
    """One test per rule of `propose`, in order."""

    def test_split_leg_blocks(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._split(out_tx, [(self.misc, "60.00"), (self.savings, "40.00")])
        p = self.proposal(out_tx, in_tx)
        self.assertTrue(p.blocked)
        self.assertEqual(p.code, "split")

    def test_both_reconciled_blocks(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(out_tx, self.misc)
        self._categorize_as_transfer(in_tx, self.misc)
        self._reconcile(out_tx)
        self._reconcile(in_tx)
        p = self.proposal(out_tx, in_tx)
        self.assertTrue(p.blocked)
        self.assertEqual(p.code, "both_reconciled")

    def test_reconciled_leg_is_kept(self):
        for reconciled_side in ("out", "in"):
            with self.subTest(reconciled_side=reconciled_side):
                out_tx = self._tx(self.checking, "100.00")
                in_tx = self._tx(self.savings, "-100.00")
                self._categorize_as_transfer(out_tx, self.misc)
                self._categorize_as_transfer(in_tx, self.misc)
                reconciled, other = (out_tx, in_tx) if reconciled_side == "out" else (in_tx, out_tx)
                self._reconcile(reconciled)
                p = self.proposal(out_tx, in_tx)
                self.assertEqual((p.status, p.code), ("ready", "reconciled"))
                self.assertEqual((p.keep_id, p.archive_id), (reconciled.id, other.id))

    def test_reconciled_mirror_line_locks_its_leg(self):
        # in_tx is categorized as a transfer to checking; its mirror line in checking
        # is reconciled. Archiving in_tx would void that line, so in_tx is kept.
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(in_tx, self.checking)
        sync_transfer(in_tx)
        self._reconcile(in_tx, account=self.checking)
        p = self.proposal(out_tx, in_tx)
        self.assertEqual((p.keep_id, p.archive_id, p.code), (in_tx.id, out_tx.id, "reconciled"))

    def test_kept_leg_reconciled_as_transfer_elsewhere_blocks(self):
        # in_tx is a reconciled transfer to the credit card. Keeping it means moving
        # that reconciled line to checking, and archiving it means voiding it.
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(in_tx, self.credit_card)
        self._reconcile(in_tx, account=self.credit_card)
        p = self.proposal(out_tx, in_tx)
        self.assertTrue(p.blocked)
        self.assertEqual(p.code, "category_reconciled")

    def test_leg_already_a_transfer_to_the_other_account_is_kept(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(out_tx, self.misc)
        self._categorize_as_transfer(in_tx, self.checking)
        p = self.proposal(out_tx, in_tx)
        self.assertEqual((p.keep_id, p.code), (in_tx.id, "already_transfer"))

    def test_categorized_leg_is_kept_over_uncategorized(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(in_tx, self.misc)
        p = self.proposal(out_tx, in_tx)
        self.assertEqual((p.keep_id, p.code), (in_tx.id, "categorized"))

    def test_bank_connection_leg_is_kept_over_file_import(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        in_tx.source = BankTransaction.SOURCE_PLAID
        in_tx.save()
        p = self.proposal(out_tx, in_tx)
        self.assertEqual((p.keep_id, p.code), (in_tx.id, "source"))

    def test_tie_keeps_the_outflow(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        p = self.proposal(out_tx, in_tx)
        self.assertEqual((p.keep_id, p.archive_id, p.code), (out_tx.id, in_tx.id, "outflow"))


class TransferMatchEndpointTest(MatchTestBase):
    def setUp(self):
        super().setUp()
        self.url = f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/transfers/match/"

    def post(self, a, b, expected_archive_id):
        with current_book(self.book):
            return self.client.post(
                self.url,
                {"transaction_a": a.id, "transaction_b": b.id, "expected_archive_id": expected_archive_id.id},
                format="json",
            )

    def assert_one_transfer(self, kept, archived):
        """One posted entry books the movement once, in both accounts and both feeds."""
        kept.refresh_from_db()
        archived.refresh_from_db()
        self.assertFalse(kept.is_archived)
        self.assertTrue(archived.is_archived)
        entry = kept.journal_entry
        self.assertEqual(entry.status, JournalEntry.STATUS_POSTED)
        self.assertEqual({line.account_id for line in entry.lines.all()}, {kept.account_id, archived.account_id})
        mirror = BankTransaction.objects.get(journal_entry=entry, is_transfer_mirror=True)
        self.assertEqual(mirror.account_id, archived.account_id)
        self.assertFalse(mirror.is_archived)
        self.assertEqual(self.checking.balance, Decimal("-100.00"))
        self.assertEqual(self.savings.balance, Decimal("100.00"))

    def test_matches_two_uncategorized_legs(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        resp = self.post(out_tx, in_tx, expected_archive_id=in_tx)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.data["kept_id"], out_tx.id)
        self.assertEqual(resp.data["archived_id"], in_tx.id)
        self.assertIsNone(resp.data["voided_entry_id"])
        self.assertIsNone(resp.data["previous_category_id"])
        self.assert_one_transfer(out_tx, in_tx)
        self.assertEqual(resp.data["kept_journal_entry_id"], out_tx.journal_entry_id)

    def test_repoints_a_kept_leg_categorized_as_spending(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(out_tx, self.misc)
        resp = self.post(out_tx, in_tx, expected_archive_id=in_tx)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.data["previous_category_id"], self.misc.id)
        self.assert_one_transfer(out_tx, in_tx)
        self.assertEqual(self.misc.balance, Decimal("0"))

    def test_cross_categorized_pair_keeps_one_entry(self):
        # Both legs categorized as transfers to each other: each has its own entry
        # and mirror, so every balance is doubled.
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(out_tx, self.savings)
        sync_transfer(out_tx)
        in_entry = self._categorize_as_transfer(in_tx, self.checking)
        sync_transfer(in_tx)
        self.assertEqual(self.checking.balance, Decimal("-200.00"))

        resp = self.post(out_tx, in_tx, expected_archive_id=in_tx)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.data["voided_entry_id"], in_entry.id)
        in_entry.refresh_from_db()
        self.assertEqual(in_entry.status, JournalEntry.STATUS_VOID)
        # The archived leg's own mirror (in checking) goes with it.
        self.assertTrue(BankTransaction.objects.get(journal_entry=in_entry, is_transfer_mirror=True).is_archived)
        self.assert_one_transfer(out_tx, in_tx)

    def test_keeps_the_reconciled_leg_untouched(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(in_tx, self.misc)
        bank_line = self._reconcile(in_tx)

        resp = self.post(out_tx, in_tx, expected_archive_id=out_tx)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.data["kept_id"], in_tx.id)
        bank_line.refresh_from_db()
        self.assertTrue(bank_line.is_reconciled)
        self.assertEqual(in_tx.journal_entry.lines.get(account=self.savings).pk, bank_line.pk)
        self.assert_one_transfer(in_tx, out_tx)

    def test_stale_expected_leg_is_409_with_current_proposal(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        # The client was shown "archive the inflow" (the tie rule); the inflow has
        # since been reconciled, so the outflow is now the one to archive.
        self._categorize_as_transfer(in_tx, self.misc)
        self._reconcile(in_tx)
        resp = self.post(out_tx, in_tx, expected_archive_id=in_tx)
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["proposal"]["archive_id"], out_tx.id)
        out_tx.refresh_from_db()
        in_tx.refresh_from_db()
        self.assertFalse(out_tx.is_archived or in_tx.is_archived)

    def test_blocked_pair_is_400(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(out_tx, self.misc)
        self._categorize_as_transfer(in_tx, self.misc)
        self._reconcile(out_tx)
        self._reconcile(in_tx)
        resp = self.post(out_tx, in_tx, expected_archive_id=in_tx)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reconciled", resp.data["error"])

    def test_refuses_a_pair_that_is_not_a_transfer(self):
        cases = {
            "same account": lambda: (self._tx(self.checking, "100.00"), self._tx(self.checking, "-100.00")),
            "unequal": lambda: (self._tx(self.checking, "100.00"), self._tx(self.savings, "-99.00")),
            "same sign": lambda: (self._tx(self.checking, "100.00"), self._tx(self.savings, "100.00")),
            "archived": lambda: (
                self._tx(self.checking, "100.00"),
                self._tx(self.savings, "-100.00", is_archived=True),
            ),
            "too far apart": lambda: (
                self._tx(self.checking, "100.00", posted_date=date(2026, 6, 1)),
                self._tx(self.savings, "-100.00", posted_date=date(2026, 6, 30)),
            ),
        }
        for name, make in cases.items():
            with self.subTest(name):
                a, b = make()
                resp = self.post(a, b, expected_archive_id=b)
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                for tx in (a, b):
                    tx.refresh_from_db()
                    self.assertIsNone(tx.journal_entry_id)

    def test_refuses_a_mirror_leg(self):
        out_tx = self._tx(self.checking, "100.00")
        self._categorize_as_transfer(out_tx, self.savings)
        sync_transfer(out_tx)
        mirror = BankTransaction.objects.get(is_transfer_mirror=True)
        other = self._tx(self.credit_card, "100.00")  # hypothetical other leg: money out of the card
        resp = self.post(mirror, other, expected_archive_id=other)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refuses_a_dismissed_pair(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        TransferMatchDismissal.record(self.book, out_tx.id, in_tx.id)
        resp = self.post(out_tx, in_tx, expected_archive_id=in_tx)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_second_match_is_refused(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self.assertEqual(self.post(out_tx, in_tx, expected_archive_id=in_tx).status_code, status.HTTP_200_OK)
        self.assertEqual(self.post(out_tx, in_tx, expected_archive_id=in_tx).status_code, 400)
        self.assert_one_transfer(out_tx, in_tx)

    def test_other_books_transaction_is_404(self):
        other_book = Team.objects.create(name="Other", slug="other").default_book
        group = AccountGroup.objects.create(book=other_book, name="Bank", account_type=self.asset_group.account_type)
        account = Account.objects.create(book=other_book, name="Checking", account_group=group, has_feed=True)
        theirs = BankTransaction.objects.create(
            book=other_book,
            account=account,
            amount=Decimal("-100.00"),
            posted_date=date(2026, 6, 1),
            description="x",
            source=BankTransaction.SOURCE_CSV,
        )
        ours = self._tx(self.checking, "100.00")
        resp = self.post(ours, theirs, expected_archive_id=theirs)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_archived)

    def test_expected_leg_must_be_one_of_the_pair(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        stranger = self._tx(self.credit_card, "5.00")
        self.assertEqual(self.post(out_tx, in_tx, expected_archive_id=stranger).status_code, 400)

    def test_logs_audit_event(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self.post(out_tx, in_tx, expected_archive_id=in_tx)
        event = AuditEvent.objects.get(event_type=AuditEvent.TRANSFER_DUP_RESOLVED)
        self.assertEqual(event.metadata["mode"], "match")
        self.assertEqual(event.metadata["kept_id"], out_tx.id)
        self.assertEqual(event.metadata["archived_id"], in_tx.id)

    def test_matched_pair_is_no_longer_suggested(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self.post(out_tx, in_tx, expected_archive_id=in_tx)
        with current_book(self.book):
            self.assertEqual(self.candidates(), [])


class SuggestionProposalTest(MatchTestBase):
    def setUp(self):
        super().setUp()
        self.url = f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/transfers/"

    def test_suggestions_carry_the_proposal(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        with current_book(self.book):
            resp = self.client.get(self.url)
        proposal = resp.data[0]["proposal"]
        self.assertEqual(proposal["status"], "ready")
        self.assertEqual((proposal["keep_id"], proposal["archive_id"]), (out_tx.id, in_tx.id))
        self.assertTrue(proposal["message"])

    def test_account_filter_applies_after_pairing(self):
        self._tx(self.checking, "100.00")
        self._tx(self.savings, "-100.00")
        self._tx(self.credit_card, "50.00", posted_date=date(2026, 6, 2))
        self._tx(self.savings, "-50.00", posted_date=date(2026, 6, 2))
        with current_book(self.book):
            all_pairs = self.client.get(self.url).data
            checking = self.client.get(self.url, {"account": self.checking.id}).data
            savings = self.client.get(self.url, {"account": self.savings.id}).data
        self.assertEqual(len(all_pairs), 2)
        self.assertEqual(len(checking), 1)
        self.assertEqual(checking[0]["outflow"]["account"]["id"], self.checking.id)
        self.assertEqual(len(savings), 2)

    def test_bad_account_filter_is_400(self):
        with current_book(self.book):
            resp = self.client.get(self.url, {"account": "abc"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
