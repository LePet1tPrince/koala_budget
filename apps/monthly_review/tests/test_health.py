from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EQUITY, Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry, JournalLine
from apps.monthly_review.services.health import (
    BALANCE_GAP,
    NO_TRANSACTIONS,
    STALE_ACCOUNT,
    UNCATEGORIZED,
    UNRECONCILED,
    account_health,
)
from apps.teams.models import Team


class AccountHealthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Health Team", slug="health-team")
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.equity_group = AccountGroup.objects.create(team=cls.team, name="Equity", account_type=ACCOUNT_TYPE_EQUITY)
        cls.month = date(2026, 8, 1)

    def _account(self, name):
        return Account.objects.create(team=self.team, name=name, account_group=self.asset_group, has_feed=True)

    def _categorize(self, bank_txn, category, *, reconciled=False):
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=bank_txn.posted_date, description=bank_txn.description, status="posted"
        )
        JournalLine.objects.create(
            team=self.team,
            journal_entry=entry,
            account=bank_txn.account,
            cr_amount=bank_txn.amount,
            is_reconciled=reconciled,
        )
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=category, dr_amount=bank_txn.amount)
        bank_txn.journal_entry = entry
        bank_txn.save()
        return entry

    def test_no_transactions_flag(self):
        account = self._account("Chequing")
        health = account_health(self.team, self.month)
        row = health["accounts"][0]
        self.assertEqual(row["account"], account)
        self.assertEqual(row["transaction_count"], 0)
        self.assertEqual([f["kind"] for f in row["flags"]], [NO_TRANSACTIONS])
        self.assertFalse(health["all_clear"])

    def test_stale_account_flag(self):
        # A transaction lands early in the month, then the feed goes quiet --
        # transaction_count is non-zero, but the last-ever transaction is well
        # more than the stale window before month end.
        account = self._account("Savings")
        category = Account.objects.create(team=self.team, name="Misc", account_group=self.equity_group)
        txn = BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal("10.00"),
            posted_date=date(2026, 8, 1),
            description="Early in the month",
        )
        self._categorize(txn, category, reconciled=True)
        health = account_health(self.team, self.month)
        row = health["accounts"][0]
        kinds = [f["kind"] for f in row["flags"]]
        self.assertIn(STALE_ACCOUNT, kinds)
        self.assertNotIn(NO_TRANSACTIONS, kinds)

    def test_no_flag_for_recent_transaction_within_stale_window(self):
        account = self._account("Chequing")
        category = Account.objects.create(team=self.team, name="Misc", account_group=self.equity_group)
        txn = BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal("10.00"),
            posted_date=date(2026, 8, 25),
            description="Coffee",
        )
        self._categorize(txn, category, reconciled=True)
        health = account_health(self.team, self.month)
        row = health["accounts"][0]
        self.assertEqual(row["flags"], [])

    def test_uncategorized_flag(self):
        account = self._account("Chequing")
        BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal("10.00"),
            posted_date=date(2026, 8, 5),
            description="Coffee",
        )
        health = account_health(self.team, self.month)
        row = health["accounts"][0]
        kinds = {f["kind"]: f for f in row["flags"]}
        self.assertIn(UNCATEGORIZED, kinds)
        self.assertEqual(kinds[UNCATEGORIZED]["count"], 1)

    def test_unreconciled_flag(self):
        account = self._account("Chequing")
        category = Account.objects.create(team=self.team, name="Groceries", account_group=self.equity_group)
        txn = BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal("10.00"),
            posted_date=date(2026, 8, 5),
            description="Coffee",
        )
        self._categorize(txn, category, reconciled=False)
        health = account_health(self.team, self.month)
        row = health["accounts"][0]
        kinds = {f["kind"]: f for f in row["flags"]}
        self.assertIn(UNRECONCILED, kinds)
        self.assertEqual(kinds[UNRECONCILED]["count"], 1)
        self.assertNotIn(UNCATEGORIZED, kinds)

    def test_balance_gap_flag_without_bank_feed_activity(self):
        account = self._account("Chequing")
        other = Account.objects.create(team=self.team, name="Misc", account_group=self.equity_group)
        # A manual journal entry not tied to any bank transaction still moves the
        # balance without moving the reconciled balance.
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2026, 8, 3), description="Manual", status="posted"
        )
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=account, dr_amount=Decimal("50"))
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=other, cr_amount=Decimal("50"))

        # Give the account a transaction this month so no_transactions doesn't fire.
        BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal("1.00"),
            posted_date=date(2026, 8, 5),
            description="Unrelated",
            journal_entry=None,
        )

        health = account_health(self.team, self.month)
        row = health["accounts"][0]
        kinds = {f["kind"]: f for f in row["flags"]}
        self.assertIn(BALANCE_GAP, kinds)
        self.assertEqual(kinds[BALANCE_GAP]["gap"], Decimal("50"))

    def test_all_clear(self):
        account = self._account("Chequing")
        category = Account.objects.create(team=self.team, name="Groceries", account_group=self.equity_group)
        txn = BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal("10.00"),
            posted_date=date(2026, 8, 25),
            description="Coffee",
        )
        self._categorize(txn, category, reconciled=True)
        health = account_health(self.team, self.month)
        self.assertEqual(health["accounts"][0]["flags"], [])
        self.assertTrue(health["all_clear"])

    def test_non_feed_accounts_excluded(self):
        Account.objects.create(
            team=self.team, name="Not a feed account", account_group=self.asset_group, has_feed=False
        )
        health = account_health(self.team, self.month)
        self.assertEqual(health["accounts"], [])
        self.assertTrue(health["all_clear"])

    def test_system_accounts_excluded(self):
        Account.objects.create(
            team=self.team, name="System", account_group=self.asset_group, has_feed=True, is_system=True
        )
        health = account_health(self.team, self.month)
        self.assertEqual(health["accounts"], [])

    def test_archived_transactions_ignored(self):
        account = self._account("Chequing")
        BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal("10.00"),
            posted_date=date(2026, 8, 5),
            description="Archived",
            is_archived=True,
        )
        health = account_health(self.team, self.month)
        row = health["accounts"][0]
        self.assertEqual(row["transaction_count"], 0)
        self.assertIn(NO_TRANSACTIONS, [f["kind"] for f in row["flags"]])
