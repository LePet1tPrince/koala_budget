"""
Tests for transfer mirror legs.

When a bank transaction is categorized as a transfer to another feed account, a
linked "mirror" leg is created in that account so the transfer shows up in both
feeds, reconciles independently, and stays in lockstep when edited — all backed
by a single shared journal entry (no double-counting).
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.transfer_detection import find_transfer_candidates
from apps.journal.models import JournalEntry
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class TransferMirrorTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Bank Accounts", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.liability_group = AccountGroup.objects.create(
            team=cls.team, name="Credit Cards", account_type=ACCOUNT_TYPE_LIABILITY
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.checking = Account.objects.create(
            team=cls.team, name="Checking", account_group=cls.asset_group, has_feed=True
        )
        cls.credit_card = Account.objects.create(
            team=cls.team, name="Credit Card", account_group=cls.liability_group, has_feed=True
        )
        cls.groceries = Account.objects.create(
            team=cls.team, name="Groceries", account_group=cls.expense_group, has_feed=False
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # --- helpers ---------------------------------------------------------

    def _tx(self, account, amount, **kwargs):
        return BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal(amount),
            posted_date=kwargs.pop("posted_date", date(2026, 6, 1)),
            description=kwargs.pop("description", "Payment"),
            source=BankTransaction.SOURCE_CSV,
            **kwargs,
        )

    def _categorize(self, tx, category_account):
        url = f"/a/{self.team.slug}/bankfeed/api/feed/categorize/"
        with current_team(self.team):
            return self.client.post(url, {"rows": [{"id": tx.id}], "category_id": category_account.id}, format="json")

    def _mirror_of(self, entry):
        return BankTransaction.objects.filter(journal_entry=entry, is_transfer_mirror=True).first()

    # --- tests -----------------------------------------------------------

    def test_categorizing_transfer_creates_mirror_leg(self):
        tx = self._tx(self.checking, "100.00")  # money out of checking
        resp = self._categorize(tx, self.credit_card)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)
        self.assertIsNotNone(mirror)
        self.assertEqual(mirror.account_id, self.credit_card.id)
        self.assertEqual(mirror.amount, Decimal("-100.00"))  # opposite direction
        self.assertEqual(mirror.journal_entry_id, tx.journal_entry_id)  # same entry
        self.assertEqual(mirror.posted_date, tx.posted_date)

    def test_mirror_shows_in_counterpart_feed(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        url = f"/a/{self.team.slug}/bankfeed/api/feed/?account={self.credit_card.id}"
        with current_team(self.team):
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data["results"]
        self.assertEqual(len(rows), 1)
        # Counterpart feed shows the leg with the other account as its category.
        self.assertEqual(rows[0]["account"]["id"], self.credit_card.id)
        self.assertEqual(rows[0]["category"]["id"], self.checking.id)

    def test_no_double_count_single_entry(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        # Exactly one (non-void) journal entry books the movement.
        self.assertEqual(JournalEntry.objects.filter(team=self.team).count(), 1)
        self.checking.refresh_from_db()
        self.credit_card.refresh_from_db()
        self.assertEqual(self.checking.balance, Decimal("-100.00"))  # cr asset
        self.assertEqual(self.credit_card.balance, Decimal("100.00"))  # dr liability

    def test_expense_category_creates_no_mirror(self):
        tx = self._tx(self.checking, "40.00")
        self._categorize(tx, self.groceries)
        tx.refresh_from_db()
        self.assertIsNone(self._mirror_of(tx.journal_entry))
        # No extra BankTransaction was created.
        self.assertEqual(BankTransaction.objects.filter(team=self.team).count(), 1)

    def test_legs_reconcile_independently(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_reconcile/"
        with current_team(self.team):
            resp = self.client.post(url, {"ids": [mirror.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        entry = tx.journal_entry
        cc_line = entry.lines.get(account=self.credit_card)
        chk_line = entry.lines.get(account=self.checking)
        self.assertTrue(cc_line.is_reconciled)  # the leg we reconciled
        self.assertFalse(chk_line.is_reconciled)  # the other leg, untouched

    def test_editing_primary_syncs_mirror(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()

        url = f"/a/{self.team.slug}/bankfeed/api/feed/{tx.id}/"
        with current_team(self.team):
            resp = self.client.put(
                url,
                {
                    "date": "2026-06-09",
                    "category": self.credit_card.id,
                    "outflow": "150.00",
                    "account": self.checking.id,
                    "description": "Updated payment",
                },
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        mirror = self._mirror_of(tx.journal_entry)
        self.assertEqual(mirror.posted_date, date(2026, 6, 9))
        self.assertEqual(mirror.amount, Decimal("-150.00"))
        self.assertEqual(mirror.description, "Updated payment")

    def test_recategorizing_to_expense_removes_mirror(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        entry = tx.journal_entry
        self.assertIsNotNone(self._mirror_of(entry))

        # Re-categorize the same transaction to an expense via batch_edit.
        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_edit/"
        with current_team(self.team):
            resp = self.client.patch(url, {"ids": [tx.id], "category_id": self.groceries.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNone(self._mirror_of(entry))

    def test_deleting_one_leg_removes_both_and_entry(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        entry_id = tx.journal_entry_id
        mirror = self._mirror_of(tx.journal_entry)

        # Archive then delete the primary leg.
        tx.is_archived = True
        tx.save(update_fields=["is_archived"])
        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_delete/"
        with current_team(self.team):
            resp = self.client.post(url, {"ids": [tx.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(BankTransaction.objects.filter(id=tx.id).exists())
        self.assertFalse(BankTransaction.objects.filter(id=mirror.id).exists())
        self.assertFalse(JournalEntry.objects.filter(id=entry_id).exists())

    def test_detector_does_not_flag_the_two_legs(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        # The primary and its mirror share one entry; they must not look like a
        # cross-account duplicate.
        with current_team(self.team):
            self.assertEqual(find_transfer_candidates(self.team), [])
