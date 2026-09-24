from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EQUITY, Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry, JournalLine
from apps.monthly_review.services.health import (
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

    def test_earlier_months_unreconciled_backlog_raises_no_flag(self):
        account = self._account("Chequing")
        other = Account.objects.create(team=self.team, name="Misc", account_group=self.equity_group)
        # An unreconciled entry from an earlier month opens a gap as of month end,
        # but it is not this month's problem: no flag.
        entry = JournalEntry.objects.create(
            team=self.team, entry_date=date(2026, 7, 3), description="Manual", status="posted"
        )
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=account, dr_amount=Decimal("50"))
        JournalLine.objects.create(team=self.team, journal_entry=entry, account=other, cr_amount=Decimal("50"))

        # A clean transaction this month, so no other flag fires either.
        txn = BankTransaction.objects.create(
            team=self.team, account=account, amount=Decimal("1.00"), posted_date=date(2026, 8, 25), description="x"
        )
        self._categorize(txn, other, reconciled=True)

        health = account_health(self.team, self.month)
        row = health["accounts"][0]
        self.assertEqual(row["balance_gap"], Decimal("50"))
        self.assertEqual(row["flags"], [])
        self.assertTrue(health["all_clear"])

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

    def test_archived_categorized_transaction_does_not_create_balance_gap(self):
        # Matches the Inbox: an archived row's journal entry is excluded from the
        # categorized balance, so it must not surface as a gap to the reconciled one.
        account = self._account("Chequing")
        category = Account.objects.create(team=self.team, name="Groceries", account_group=self.equity_group)
        live = BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal("10.00"),
            posted_date=date(2026, 8, 25),
            description="Coffee",
        )
        self._categorize(live, category, reconciled=True)
        archived = BankTransaction.objects.create(
            team=self.team,
            account=account,
            amount=Decimal("500.00"),
            posted_date=date(2026, 8, 20),
            description="Archived duplicate",
        )
        self._categorize(archived, category)
        archived.is_archived = True
        archived.save()

        health = account_health(self.team, self.month)
        row = health["accounts"][0]
        self.assertEqual(row["balance"], row["reconciled_balance"])
        self.assertEqual(row["balance_gap"], Decimal("0"))
        self.assertEqual(row["flags"], [])

    def test_transactions_after_the_month_are_not_flagged(self):
        # Reviewing August: September's uncategorized/unreconciled activity is not
        # August's problem, and must not open a gap in August's balances either.
        account = self._account("Chequing")
        category = Account.objects.create(team=self.team, name="Groceries", account_group=self.equity_group)
        august = BankTransaction.objects.create(
            team=self.team, account=account, amount=Decimal("10.00"), posted_date=date(2026, 8, 25), description="Aug"
        )
        self._categorize(august, category, reconciled=True)
        september = BankTransaction.objects.create(
            team=self.team, account=account, amount=Decimal("99.00"), posted_date=date(2026, 9, 2), description="Sep"
        )
        self._categorize(september, category)  # categorized, not reconciled
        BankTransaction.objects.create(
            team=self.team, account=account, amount=Decimal("5.00"), posted_date=date(2026, 9, 3), description="New"
        )  # uncategorized

        row = account_health(self.team, self.month)["accounts"][0]
        self.assertEqual(row["uncategorized_count"], 0)
        self.assertEqual(row["unreconciled_count"], 0)
        self.assertEqual(row["balance_gap"], Decimal("0"))
        self.assertEqual(row["flags"], [])

        september_row = account_health(self.team, date(2026, 9, 1))["accounts"][0]
        self.assertEqual(september_row["uncategorized_count"], 1)
        self.assertEqual(september_row["unreconciled_count"], 1)

    def test_counts_cover_only_the_month_and_unreconciled_never_exceeds_transactions(self):
        account = self._account("Chequing")
        category = Account.objects.create(team=self.team, name="Groceries", account_group=self.equity_group)
        # Backlog: unreconciled in July -- not August's transactions.
        for day in (2, 9, 16):
            july = BankTransaction.objects.create(
                team=self.team, account=account, amount=Decimal("5.00"), posted_date=date(2026, 7, day), description="J"
            )
            self._categorize(july, category)
        august = BankTransaction.objects.create(
            team=self.team, account=account, amount=Decimal("5.00"), posted_date=date(2026, 8, 4), description="A"
        )
        self._categorize(august, category)
        BankTransaction.objects.create(
            team=self.team, account=account, amount=Decimal("5.00"), posted_date=date(2026, 8, 6), description="New"
        )  # uncategorized: a transaction, not an unreconciled one
        # A manual entry with no feed row still counts.
        manual = JournalEntry.objects.create(
            team=self.team, entry_date=date(2026, 8, 8), description="Manual", status="posted"
        )
        JournalLine.objects.create(
            team=self.team, journal_entry=manual, account=account, dr_amount=Decimal("1"), is_reconciled=True
        )
        JournalLine.objects.create(team=self.team, journal_entry=manual, account=category, cr_amount=Decimal("1"))

        row = account_health(self.team, self.month)["accounts"][0]
        self.assertEqual(row["transaction_count"], 3)
        self.assertEqual(row["unreconciled_count"], 1)

    def test_balance_change_is_movement_within_the_month(self):
        account = self._account("Chequing")
        category = Account.objects.create(team=self.team, name="Groceries", account_group=self.equity_group)
        july = BankTransaction.objects.create(
            team=self.team, account=account, amount=Decimal("100.00"), posted_date=date(2026, 7, 15), description="Jul"
        )
        self._categorize(july, category, reconciled=True)
        august = BankTransaction.objects.create(
            team=self.team, account=account, amount=Decimal("30.00"), posted_date=date(2026, 8, 10), description="Aug"
        )
        self._categorize(august, category, reconciled=True)

        row = account_health(self.team, self.month)["accounts"][0]
        # July's $100 spend sets the opening balance at -100; August's own $30
        # spend is the only thing that happened in the reviewed month, so
        # balance_change must read -30 regardless of what came before it.
        self.assertEqual(row["balance"], Decimal("-130.00"))
        self.assertEqual(row["balance_change"], Decimal("-30.00"))
        self.assertEqual(row["account_type"], ACCOUNT_TYPE_ASSET)
        self.assertIsNone(row["institution"])

    def test_institution_name_is_reported(self):
        from apps.accounts.models import Institution

        account = self._account("Chequing")
        account.institution = Institution.objects.create(team=self.team, name="Maple Bank")
        account.save()
        row = account_health(self.team, self.month)["accounts"][0]
        self.assertEqual(row["institution"], "Maple Bank")
