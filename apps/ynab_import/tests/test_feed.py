"""
The import's bank-feed rows (docs/ynab-feed-rows-plan.md).

Every register row on an account with a feed arrives in that account's Inbox feed,
linked to the entry the import writes. A transfer is written once and shows on the
other side through the feed's own mirror rule; rows YNAB never categorised wait in
the Inbox; nothing is reconciled; and anything the transfer detector would pair
across the import is recorded as "not a transfer".
"""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Account, AccountGroup
from apps.bank_feed.models import BankTransaction, TransferMatchDismissal
from apps.bank_feed.services.transfer_detection import find_transfer_candidates
from apps.bank_feed.services.transfer_mirror import sync_transfer
from apps.journal.models import JournalLine
from apps.ynab_import.services.analyse import analyse, suggested_feed
from apps.ynab_import.services.apply import apply_plan, can_import
from apps.ynab_import.services.build import build, parse_choices
from apps.ynab_import.services.parse import parse_plan, parse_register
from apps.ynab_import.services.reconcile import check_balances

from .fixtures import register_csv, sample_analysis
from .test_apply import make_team

# account, date, payee, group, category, memo, outflow, inflow, cleared
FEED_ROWS = [
    ("Chequing", "01-01-2024", "Starting Balance", "Inflow", "Ready to Assign", "", "0.00", "1000.00", "Reconciled"),
    # A card payment: a transfer between two feed accounts.
    ("Chequing", "05-01-2024", "Transfer : Visa", "", "", "Card payment", "200.00", "0.00", "Reconciled"),
    ("Visa", "05-01-2024", "Transfer : Chequing", "", "", "Card payment", "0.00", "200.00", "Cleared"),
    # A split whose second leg is a transfer to the card.
    ("Chequing", "06-01-2024", "Grocer", "Monthly", "Groceries", "Split (1/2) Big shop", "60.00", "0.00", "Cleared"),
    ("Chequing", "06-01-2024", "Transfer : Visa", "", "", "Split (2/2)", "40.00", "0.00", "Cleared"),
    ("Visa", "06-01-2024", "Transfer : Chequing", "", "", "", "0.00", "40.00", "Cleared"),
    # Never categorised in YNAB.
    ("Chequing", "07-01-2024", "Mystery", "", "", "What was this", "25.00", "0.00", "Cleared"),
    # Same amount, opposite direction, a day apart, on two accounts: not a transfer.
    ("Visa", "08-01-2024", "Cafe", "Monthly", "Groceries", "", "30.00", "0.00", "Reconciled"),
    ("Chequing", "09-01-2024", "Employer", "Inflow", "Ready to Assign", "Refund", "0.00", "30.00", "Reconciled"),
]

FEED_PLAN = """\
"Month","Category Group/Category","Category Group","Category","Assigned","Activity","Available"
"Jan 2024","Credit Card Payments: Visa","Credit Card Payments","Visa",0.00$,0.00$,0.00$
"Jan 2024","Monthly: Groceries","Monthly","Groceries",100.00$,-90.00$,10.00$
"""


def feed_analysis():
    return analyse(parse_register(register_csv(FEED_ROWS).encode()), parse_plan(FEED_PLAN.encode()))


class FeedBuildTest(SimpleTestCase):
    def setUp(self):
        self.analysis = feed_analysis()
        self.plan = build(self.analysis)

    def test_uncategorised_row_waits_in_the_inbox(self):
        (row,) = self.plan.inbox_rows
        self.assertEqual((row.account[1], row.amount, row.description), ("Chequing", Decimal("25.00"), "What was this"))
        self.assertFalse(any(entry.description == "What was this" for entry in self.plan.entries))

    def test_balances_gate_counts_the_inbox(self):
        self.assertTrue(check_balances(self.analysis, self.plan).passed)

    def test_a_transfer_has_one_planned_feed_row(self):
        entry = next(e for e in self.plan.entries if e.description == "Card payment")
        self.assertEqual((entry.feed.account[1], entry.feed.amount), ("Chequing", Decimal("200.00")))

    def test_a_split_has_one_planned_feed_row_for_its_total(self):
        entry = next(e for e in self.plan.entries if e.description == "Big shop")
        self.assertEqual((entry.feed.account[1], entry.feed.amount), ("Chequing", Decimal("100.00")))

    def test_feed_row_count_includes_mirrors_and_the_inbox(self):
        # Chequing: payment, split, refund, mystery (inbox). Visa: two mirrors, cafe.
        self.assertEqual(self.plan.stats["feed_rows"], 7)
        self.assertEqual(self.plan.stats["inbox_rows"], 1)

    def test_turning_the_feed_off_keeps_an_account_out_of_the_inbox(self):
        choices = parse_choices(self.analysis, {"accounts": {"Visa": {"has_feed": False}}})
        plan = build(self.analysis, choices)
        self.assertFalse(any(e.feed and e.feed.account[1] == "Visa" for e in plan.entries))
        self.assertFalse(next(a for a in plan.accounts if a.name == "Visa").has_feed)


class SuggestedFeedTest(SimpleTestCase):
    LATEST = date(2026, 9, 30)

    def test_everyday_accounts_and_debts_have_a_feed(self):
        self.assertTrue(suggested_feed("asset", True, Decimal("5"), date(2026, 9, 1), self.LATEST))
        self.assertTrue(suggested_feed("liability", False, Decimal("-5"), date(2026, 9, 1), self.LATEST))

    def test_tracking_accounts_do_not(self):
        self.assertFalse(suggested_feed("asset", False, Decimal("5"), date(2026, 9, 1), self.LATEST))

    def test_an_emptied_account_left_for_a_year_does_not(self):
        self.assertFalse(suggested_feed("asset", True, Decimal("0"), date(2025, 9, 1), self.LATEST))
        # Emptied but still in use, or idle but holding money: both keep a feed.
        self.assertTrue(suggested_feed("asset", True, Decimal("0"), date(2026, 1, 1), self.LATEST))
        self.assertTrue(suggested_feed("asset", True, Decimal("5"), date(2024, 1, 1), self.LATEST))


class FeedApplyTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("Feed", "feed")
        cls.book = cls.team.default_book
        cls.plan = build(feed_analysis())
        cls.result = apply_plan(cls.book, cls.plan, user=cls.user)

    def rows(self, name):
        return BankTransaction.objects.filter(book=self.book, account__name=name).order_by("posted_date", "id")

    def test_the_transfer_shows_once_in_each_feed(self):
        chequing = self.rows("Chequing").get(description="Card payment")
        visa = self.rows("Visa").get(journal_entry_id=chequing.journal_entry_id)
        self.assertFalse(chequing.is_transfer_mirror)
        self.assertEqual(chequing.source, BankTransaction.SOURCE_YNAB)
        self.assertEqual(chequing.raw, {"ynab": {"row": 1}})
        self.assertTrue(visa.is_transfer_mirror)
        self.assertEqual(visa.amount, Decimal("-200.00"))

    def test_the_split_shows_its_transfer_leg_in_the_other_feed(self):
        split = self.rows("Chequing").get(description="Big shop")
        self.assertEqual(split.amount, Decimal("100.00"))
        mirror = self.rows("Visa").get(journal_entry_id=split.journal_entry_id)
        self.assertTrue(mirror.is_transfer_mirror)
        self.assertEqual(mirror.amount, Decimal("-40.00"))

    def test_the_import_is_what_the_feed_itself_would_write(self):
        before = sorted(BankTransaction.objects.filter(book=self.book).values_list("id", "account_id", "amount"))
        for primary in BankTransaction.objects.filter(
            book=self.book, is_transfer_mirror=False, journal_entry__isnull=False
        ):
            sync_transfer(primary)
        after = sorted(BankTransaction.objects.filter(book=self.book).values_list("id", "account_id", "amount"))
        self.assertEqual(after, before)

    def test_uncategorised_row_is_in_the_inbox(self):
        row = self.rows("Chequing").get(description="What was this")
        self.assertIsNone(row.journal_entry_id)
        self.assertEqual(self.result.inbox_rows, 1)

    def test_nothing_is_reconciled(self):
        self.assertFalse(JournalLine.objects.filter(book=self.book, is_reconciled=True).exists())

    def test_look_alike_transfers_are_dismissed(self):
        self.assertEqual(self.result.dismissed_transfer_matches, 1)
        self.assertEqual(TransferMatchDismissal.objects.filter(book=self.book).count(), 1)
        self.assertEqual(find_transfer_candidates(self.book), [])

    def test_accounts_have_feeds(self):
        self.assertTrue(Account.objects.get(book=self.book, name="Chequing").has_feed)
        self.assertTrue(Account.objects.get(book=self.book, name="Visa").has_feed)

    def test_result_counts(self):
        self.assertEqual(self.result.feed_rows, self.plan.stats["feed_rows"])
        self.assertEqual(BankTransaction.objects.filter(book=self.book).count(), 7)


class CanImportTest(TestCase):
    def test_a_book_with_an_uploaded_statement_is_refused(self):
        team, _user = make_team("Uploaded", "uploaded")
        book = team.default_book
        self.assertTrue(can_import(book))
        group = AccountGroup.objects.create(book=book, name="Bank", account_type="asset")
        # An uncategorized row has no journal entry, but it is history in the book.
        BankTransaction.objects.create(
            book=book,
            account=Account.objects.create(book=book, name="Chequing", account_group=group, has_feed=True),
            amount=Decimal("10.00"),
            posted_date=date(2024, 1, 1),
            description="Uploaded",
            source=BankTransaction.SOURCE_CSV,
        )
        self.assertFalse(can_import(book))


class SampleFeedTest(TestCase):
    """The real export: 6,860 feed rows, 8 in the Inbox, no transfer suggestions left."""

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("Sample feed", "sample-feed")
        cls.book = cls.team.default_book
        cls.plan = build(sample_analysis())
        cls.result = apply_plan(cls.book, cls.plan, user=cls.user)

    def test_counts(self):
        self.assertEqual(BankTransaction.objects.filter(book=self.book).count(), 6860)
        self.assertEqual(self.result.feed_rows, 6860)
        self.assertEqual(BankTransaction.objects.filter(book=self.book, journal_entry__isnull=True).count(), 8)

    def test_every_transfer_between_feeds_is_one_row_and_one_mirror(self):
        mirrors = BankTransaction.objects.filter(book=self.book, is_transfer_mirror=True)
        self.assertTrue(mirrors.exists())
        for mirror in mirrors.select_related("journal_entry")[:100]:
            legs = BankTransaction.objects.filter(journal_entry_id=mirror.journal_entry_id)
            self.assertEqual(legs.filter(is_transfer_mirror=False).count(), 1)

    def test_dormant_accounts_have_no_feed(self):
        dormant = ("BBC A/R", "Bender Books (TG)", "WS Cash", "Viv's Invest (WS)")
        self.assertFalse(Account.objects.filter(book=self.book, name__in=dormant, has_feed=True).exists())
        self.assertFalse(BankTransaction.objects.filter(book=self.book, account__name__in=dormant).exists())

    def test_no_transfer_suggestions_remain(self):
        self.assertGreater(self.result.dismissed_transfer_matches, 0)
        self.assertEqual(find_transfer_candidates(self.book), [])

    def test_nothing_is_reconciled(self):
        self.assertFalse(JournalLine.objects.filter(book=self.book, is_reconciled=True).exists())


class FeedPortabilityTest(TestCase):
    """An imported book's feed -- `ynab` rows, mirrors, split mirrors, the Inbox -- exports and loads back."""

    def test_round_trip(self):
        from apps.portability.services import apply as portability_apply
        from apps.portability.tests.test_apply import export_bytes

        team, user = make_team("Feed source", "feed-source")
        source = team.default_book
        apply_plan(source, build(feed_analysis()), user=user)
        dest_team, dest_user = make_team("Feed dest", "feed-dest")
        dest = dest_team.default_book

        portability_apply.apply_archive(dest, export_bytes(source), user=dest_user)

        def shape(book):
            return sorted(
                (tx.account.name, tx.amount, tx.source, tx.is_transfer_mirror, tx.journal_entry_id is None)
                for tx in BankTransaction.objects.filter(book=book).select_related("account")
            )

        self.assertEqual(shape(dest), shape(source))
