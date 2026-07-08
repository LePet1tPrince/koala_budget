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
        cls.savings = Account.objects.create(
            team=cls.team, name="Savings", account_group=cls.asset_group, has_feed=True
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

    def test_csv_auto_categorize_creates_mirror(self):
        # Categorizing a transfer during CSV import must also create the mirror leg.
        from apps.bank_feed.services.csv_upload import create_transactions

        with current_team(self.team):
            result = create_transactions(
                transactions=[
                    {
                        "date": date(2026, 6, 1),
                        "description": "Card payment",
                        "payee": "",
                        "amount": Decimal("100.00"),
                        "category_id": self.credit_card.id,
                    }
                ],
                team=self.team,
                account_id=self.checking.id,
            )
        self.assertEqual(result["created_count"], 1)
        primary = BankTransaction.objects.get(account=self.checking, is_transfer_mirror=False)
        mirror = self._mirror_of(primary.journal_entry)
        self.assertIsNotNone(mirror)
        self.assertEqual(mirror.account_id, self.credit_card.id)
        self.assertEqual(mirror.amount, Decimal("-100.00"))

    def test_editing_primary_category_moves_mirror(self):
        # Re-pointing the primary's transfer destination moves the mirror leg.
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_edit/"
        with current_team(self.team):
            resp = self.client.patch(url, {"ids": [tx.id], "category_id": self.savings.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        mirror.refresh_from_db()
        self.assertEqual(mirror.account_id, self.savings.id)  # mirror followed

    def test_editing_mirror_category_moves_primary(self):
        # The new feature: re-pointing the mirror's category moves the primary leg.
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_edit/"
        with current_team(self.team):
            resp = self.client.patch(url, {"ids": [mirror.id], "category_id": self.savings.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        tx.refresh_from_db()
        self.assertEqual(tx.account_id, self.savings.id)  # the primary moved
        mirror.refresh_from_db()
        self.assertEqual(mirror.account_id, self.credit_card.id)  # mirror stayed put
        # Still one entry, both legs intact.
        self.assertEqual(JournalEntry.objects.filter(team=self.team).count(), 1)

    def test_pointing_mirror_at_non_feed_category_is_rejected(self):
        # Pointing the mirror at an expense would orphan the real primary -> blocked.
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_edit/"
        with current_team(self.team):
            resp = self.client.patch(url, {"ids": [mirror.id], "category_id": self.groceries.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        # Nothing changed: the primary still sits in checking, both legs intact.
        tx.refresh_from_db()
        self.assertEqual(tx.account_id, self.checking.id)
        self.assertTrue(BankTransaction.objects.filter(id=mirror.id).exists())

    def test_archiving_primary_archives_mirror(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_archive/"
        with current_team(self.team):
            resp = self.client.post(url, {"ids": [tx.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        tx.refresh_from_db()
        mirror.refresh_from_db()
        self.assertTrue(tx.is_archived)
        self.assertTrue(mirror.is_archived)

    def test_archiving_mirror_archives_primary(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_archive/"
        with current_team(self.team):
            resp = self.client.post(url, {"ids": [mirror.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        tx.refresh_from_db()
        mirror.refresh_from_db()
        self.assertTrue(tx.is_archived)
        self.assertTrue(mirror.is_archived)

    def test_unarchiving_one_leg_unarchives_the_other(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)
        tx.is_archived = True
        tx.save(update_fields=["is_archived"])
        mirror.is_archived = True
        mirror.save(update_fields=["is_archived"])

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_unarchive/"
        with current_team(self.team):
            resp = self.client.post(url, {"ids": [mirror.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        tx.refresh_from_db()
        mirror.refresh_from_db()
        self.assertFalse(tx.is_archived)
        self.assertFalse(mirror.is_archived)

    def test_archiving_primary_with_reconciled_mirror_is_rejected(self):
        # The two legs archive together and a reconciled leg must never be
        # archived — so archiving the primary while the mirror is reconciled is
        # refused outright (instead of archiving one leg and stranding the other).
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)
        cc_line = tx.journal_entry.lines.get(account=self.credit_card)
        cc_line.is_reconciled = True
        cc_line.save(update_fields=["is_reconciled"])

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_archive/"
        with current_team(self.team):
            resp = self.client.post(url, {"ids": [tx.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reconciled", resp.json()["error"])

        tx.refresh_from_db()
        mirror.refresh_from_db()
        self.assertFalse(tx.is_archived)
        self.assertFalse(mirror.is_archived)

    def test_archiving_reconciled_leg_of_transfer_is_rejected(self):
        # Archiving the reconciled leg itself is refused with an explicit error
        # (not silently skipped) so the user knows to unreconcile first.
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        tx.refresh_from_db()
        mirror = self._mirror_of(tx.journal_entry)
        checking_line = tx.journal_entry.lines.get(account=self.checking)
        checking_line.is_reconciled = True
        checking_line.save(update_fields=["is_reconciled"])

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_archive/"
        with current_team(self.team):
            resp = self.client.post(url, {"ids": [tx.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reconciled", resp.json()["error"])

        tx.refresh_from_db()
        mirror.refresh_from_db()
        self.assertFalse(tx.is_archived)
        self.assertFalse(mirror.is_archived)

    def test_blocked_transfer_rejects_whole_batch(self):
        # A batch containing a blocked transfer archives nothing — all-or-nothing
        # so the user isn't left guessing which rows went through.
        blocked = self._tx(self.checking, "100.00")
        self._categorize(blocked, self.credit_card)
        blocked.refresh_from_db()
        cc_line = blocked.journal_entry.lines.get(account=self.credit_card)
        cc_line.is_reconciled = True
        cc_line.save(update_fields=["is_reconciled"])

        plain = self._tx(self.checking, "25.00")

        url = f"/a/{self.team.slug}/bankfeed/api/feed/batch_archive/"
        with current_team(self.team):
            resp = self.client.post(url, {"ids": [plain.id, blocked.id]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        plain.refresh_from_db()
        blocked.refresh_from_db()
        self.assertFalse(plain.is_archived)
        self.assertFalse(blocked.is_archived)

    def test_detector_does_not_flag_the_two_legs(self):
        tx = self._tx(self.checking, "100.00")
        self._categorize(tx, self.credit_card)
        # The primary and its mirror share one entry; they must not look like a
        # cross-account duplicate.
        with current_team(self.team):
            self.assertEqual(find_transfer_candidates(self.team), [])
