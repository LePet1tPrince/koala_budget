"""
Tests for transfer duplicate detection and resolution.

A transfer between two of the user's own accounts is reported by both banks, so
it appears in the feed twice. These tests cover the detector that flags those
pairs and the endpoints that list and dismiss (not a duplicate) a suggestion.
Matching a pair is covered by test_transfer_match.py.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import ACCOUNT_TYPE_ASSET, Account, AccountGroup
from apps.bank_feed.models import BankTransaction, TransferMatchDismissal
from apps.bank_feed.services.transfer_detection import find_transfer_candidates
from apps.bank_feed.services.transfer_mirror import sync_transfer
from apps.books.context import current_book
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class TransferTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            book=cls.book, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.checking = Account.objects.create(
            book=cls.book, name="Checking", account_group=cls.asset_group, has_feed=True
        )
        cls.savings = Account.objects.create(
            book=cls.book, name="Savings", account_group=cls.asset_group, has_feed=True
        )
        cls.credit_card = Account.objects.create(
            book=cls.book, name="Credit Card", account_group=cls.asset_group, has_feed=True
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # --- helpers ---------------------------------------------------------

    def _tx(self, account, amount, posted_date=None, **kwargs):
        """Create a BankTransaction (Plaid convention: + = outflow, - = inflow)."""
        return BankTransaction.objects.create(
            book=self.book,
            account=account,
            amount=Decimal(amount),
            posted_date=posted_date or date(2026, 6, 1),
            description=kwargs.pop("description", "Transfer"),
            source=BankTransaction.SOURCE_CSV,
            **kwargs,
        )

    def _categorize_as_transfer(self, bank_tx, category_account):
        """Mirror the view's transfer categorization: one balanced 2-line entry."""
        entry = JournalEntry.objects.create(
            book=self.book,
            entry_date=bank_tx.posted_date,
            description=bank_tx.description,
            source=JournalEntry.SOURCE_IMPORT,
            status=JournalEntry.STATUS_POSTED,
        )
        amount = abs(bank_tx.amount)
        is_inflow = bank_tx.amount < 0
        if is_inflow:
            JournalLine.objects.create(
                journal_entry=entry,
                book=self.book,
                account=bank_tx.account,
                dr_amount=amount,
                cr_amount=Decimal("0"),
            )
            JournalLine.objects.create(
                journal_entry=entry,
                book=self.book,
                account=category_account,
                dr_amount=Decimal("0"),
                cr_amount=amount,
            )
        else:
            JournalLine.objects.create(
                journal_entry=entry,
                book=self.book,
                account=bank_tx.account,
                dr_amount=Decimal("0"),
                cr_amount=amount,
            )
            JournalLine.objects.create(
                journal_entry=entry,
                book=self.book,
                account=category_account,
                dr_amount=amount,
                cr_amount=Decimal("0"),
            )
        bank_tx.journal_entry = entry
        bank_tx.save(update_fields=["journal_entry"])
        return entry

    def candidates(self):
        with current_book(self.book):
            return find_transfer_candidates(self.book)


class TransferDetectionTest(TransferTestBase):
    def test_detects_opposite_equal_cross_account_pair(self):
        out_tx = self._tx(self.checking, "100.00")  # money out of checking
        in_tx = self._tx(self.savings, "-100.00")  # money into savings
        pairs = self.candidates()
        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertEqual(pair["outflow"].id, out_tx.id)
        self.assertEqual(pair["inflow"].id, in_tx.id)
        self.assertEqual(pair["amount"], Decimal("100.00"))
        self.assertEqual(pair["date_gap_days"], 0)

    def test_ignores_same_account(self):
        self._tx(self.checking, "100.00")
        self._tx(self.checking, "-100.00")
        self.assertEqual(self.candidates(), [])

    def test_ignores_unequal_amounts(self):
        self._tx(self.checking, "100.00")
        self._tx(self.savings, "-99.00")
        self.assertEqual(self.candidates(), [])

    def test_ignores_same_direction(self):
        # Two outflows of equal magnitude are not a transfer pair.
        self._tx(self.checking, "100.00")
        self._tx(self.savings, "100.00")
        self.assertEqual(self.candidates(), [])

    def test_ignores_out_of_window(self):
        self._tx(self.checking, "100.00", posted_date=date(2026, 6, 1))
        self._tx(self.savings, "-100.00", posted_date=date(2026, 6, 20))
        self.assertEqual(self.candidates(), [])

    def test_matches_within_window(self):
        self._tx(self.checking, "100.00", posted_date=date(2026, 6, 1))
        self._tx(self.savings, "-100.00", posted_date=date(2026, 6, 4))
        pairs = self.candidates()
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["date_gap_days"], 3)

    def test_ignores_void(self):
        self._tx(self.checking, "100.00")
        self._tx(self.savings, "-100.00", is_void=True)
        self.assertEqual(self.candidates(), [])

    def test_includes_already_categorized_pairs(self):
        # Existing double-counted history must still surface for cleanup.
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(out_tx, self.savings)
        self._categorize_as_transfer(in_tx, self.checking)
        self.assertEqual(len(self.candidates()), 1)

    def test_ignores_voided_entry_leg(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        entry = self._categorize_as_transfer(in_tx, self.checking)
        entry.status = JournalEntry.STATUS_VOID
        entry.save()
        # in_tx's entry is void, so the pair should no longer be suggested.
        self.assertEqual(self.candidates(), [])
        self.assertTrue(out_tx)  # out_tx alone has no counterpart

    def test_ignores_dismissed_pairs(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        TransferMatchDismissal.record(self.book, out_tx.id, in_tx.id)
        self.assertEqual(self.candidates(), [])

    def test_each_transaction_paired_once(self):
        # One outflow, two candidate inflows -> only one pair, closest date wins.
        out_tx = self._tx(self.checking, "100.00", posted_date=date(2026, 6, 5))
        near = self._tx(self.savings, "-100.00", posted_date=date(2026, 6, 6))
        self._tx(self.savings, "-100.00", posted_date=date(2026, 6, 1))
        pairs = self.candidates()
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["inflow"].id, near.id)
        self.assertEqual(pairs[0]["outflow"].id, out_tx.id)

    def test_ignores_transfer_mirror_legs(self):
        # A real transfer, checking -> savings, gets categorized. That creates a
        # synthetic mirror leg in savings (linked to the same journal entry as the
        # real checking outflow). The bank also separately reported the real
        # duplicate leg in savings (uncategorized) -- that's the one real pair to
        # suggest. An unrelated real transaction in a third account, which happens
        # to share the same amount/date, must not get spuriously paired with the
        # synthetic mirror leg.
        out_tx = self._tx(self.checking, "100.00")
        real_dup = self._tx(self.savings, "-100.00")
        self._categorize_as_transfer(out_tx, self.savings)
        sync_transfer(out_tx)  # creates the mirror leg in savings

        unrelated = self._tx(self.credit_card, "100.00")  # unrelated real outflow, same amount/date

        pairs = self.candidates()
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["outflow"].id, out_tx.id)
        self.assertEqual(pairs[0]["inflow"].id, real_dup.id)
        self.assertTrue(unrelated)  # left unmatched, not spuriously paired with the mirror leg


class TransferSuggestionsEndpointTest(TransferTestBase):
    def setUp(self):
        super().setUp()
        self.url = f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/transfers/"

    def test_lists_suggestions(self):
        self._tx(self.checking, "100.00")
        self._tx(self.savings, "-100.00")
        with current_book(self.book):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        row = resp.data[0]
        self.assertIn("outflow", row)
        self.assertIn("inflow", row)
        self.assertEqual(Decimal(str(row["amount"])), Decimal("100.00"))
        self.assertEqual(row["outflow"]["account"]["id"], self.checking.id)
        self.assertEqual(row["inflow"]["account"]["id"], self.savings.id)

    def test_requires_team_membership(self):
        other_user = CustomUser.objects.create_user(username="outsider", password="pass")
        self.client.force_authenticate(user=other_user)
        with current_book(self.book):
            resp = self.client.get(self.url)
        self.assertIn(resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))


class TransferDismissEndpointTest(TransferTestBase):
    def setUp(self):
        super().setUp()
        self.url = f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/transfers/dismiss/"

    def test_dismiss_persists_and_hides_suggestion(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        with current_book(self.book):
            resp = self.client.post(self.url, {"transaction_a": out_tx.id, "transaction_b": in_tx.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(TransferMatchDismissal.objects.filter(book=self.book).exists())
        self.assertEqual(self.candidates(), [])

    def test_dismiss_is_idempotent_order_independent(self):
        out_tx = self._tx(self.checking, "100.00")
        in_tx = self._tx(self.savings, "-100.00")
        with current_book(self.book):
            self.client.post(self.url, {"transaction_a": out_tx.id, "transaction_b": in_tx.id}, format="json")
            self.client.post(self.url, {"transaction_a": in_tx.id, "transaction_b": out_tx.id}, format="json")
        self.assertEqual(TransferMatchDismissal.objects.filter(book=self.book).count(), 1)

    def test_dismiss_missing_transaction_returns_404(self):
        out_tx = self._tx(self.checking, "100.00")
        with current_book(self.book):
            resp = self.client.post(self.url, {"transaction_a": out_tx.id, "transaction_b": 999999}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
