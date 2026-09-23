from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account, AccountGroup
from apps.journal.models import JournalEntry, JournalLine
from apps.monthly_review.services.review import build_review
from apps.teams.models import Team

TOP_LEVEL_KEYS = {
    "month",
    "month_label",
    "prev_label",
    "is_current_month",
    "health",
    "current",
    "baselines",
    "baseline_order",
    "default_baseline",
    "budget",
    "biggest",
    "cat_txns",
    "net_worth",
    "insights",
    "notes",
}

CURRENT_KEYS = {"income", "spend", "net", "saved", "savings_rate", "transaction_count"}


class BuildReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Review Team", slug="review-team")
        cls.asset_group = AccountGroup.objects.create(team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET)
        cls.income_group = AccountGroup.objects.create(team=cls.team, name="Pay", account_type=ACCOUNT_TYPE_INCOME)
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Everyday", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.chequing = Account.objects.create(
            team=cls.team, name="Chequing", account_group=cls.asset_group, has_feed=True
        )
        cls.salary = Account.objects.create(team=cls.team, name="Salary", account_group=cls.income_group)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=cls.expense_group)

    def _entry(self, day, category, amount, *, dr_category=True, status=JournalEntry.STATUS_POSTED):
        entry = JournalEntry.objects.create(team=self.team, entry_date=day, description="test", status=status)
        if dr_category:
            JournalLine.objects.create(team=self.team, journal_entry=entry, account=category, dr_amount=amount)
            JournalLine.objects.create(team=self.team, journal_entry=entry, account=self.chequing, cr_amount=amount)
        else:
            JournalLine.objects.create(team=self.team, journal_entry=entry, account=category, cr_amount=amount)
            JournalLine.objects.create(team=self.team, journal_entry=entry, account=self.chequing, dr_amount=amount)
        return entry

    def test_payload_top_level_keys(self):
        review = build_review(self.team, date(2026, 8, 1))
        self.assertEqual(set(review.keys()), TOP_LEVEL_KEYS)
        self.assertEqual(set(review["current"].keys()), CURRENT_KEYS)

    def test_month_before_first_activity_returns_empty_state(self):
        self._entry(date(2026, 8, 10), self.salary, Decimal("1000"), dr_category=False)
        review = build_review(self.team, date(2025, 1, 1))
        self.assertEqual(review["baselines"], {})
        self.assertIsNone(review["default_baseline"])
        self.assertEqual(review["current"]["income"], Decimal("0"))
        self.assertEqual(review["current"]["transaction_count"], 0)

    def test_current_month_figures_tie_to_ledger(self):
        self._entry(date(2026, 8, 10), self.salary, Decimal("1000"), dr_category=False)
        self._entry(date(2026, 8, 12), self.groceries, Decimal("150"))
        review = build_review(self.team, date(2026, 8, 1))
        self.assertEqual(review["current"]["income"], Decimal("1000"))
        self.assertEqual(review["current"]["spend"], Decimal("150"))
        self.assertEqual(review["current"]["net"], Decimal("850"))

    def test_voided_entries_excluded_from_current_figures(self):
        self._entry(date(2026, 8, 10), self.salary, Decimal("1000"), dr_category=False)
        self._entry(date(2026, 8, 12), self.groceries, Decimal("150"), status=JournalEntry.STATUS_VOID)
        review = build_review(self.team, date(2026, 8, 1))
        self.assertEqual(review["current"]["spend"], Decimal("0"))
        group_names = [g["name"] for g in review["budget"]["groups"]]
        self.assertNotIn("Everyday", group_names)  # the voided Groceries spend must not appear
        self.assertNotIn(self.groceries.pk, review["cat_txns"])
        self.assertEqual(review["biggest"], [])

    def test_voided_entries_excluded_from_health_balances(self):
        self._entry(date(2026, 8, 10), self.salary, Decimal("1000"), dr_category=False, status=JournalEntry.STATUS_VOID)
        review = build_review(self.team, date(2026, 8, 1))
        chequing_row = next(r for r in review["health"]["accounts"] if r["account"] == self.chequing)
        self.assertEqual(chequing_row["balance"], Decimal("0"))

    def test_cat_txns_reconcile_to_spent_figure(self):
        self._entry(date(2026, 8, 1), self.groceries, Decimal("40"))
        self._entry(date(2026, 8, 15), self.groceries, Decimal("60"))
        review = build_review(self.team, date(2026, 8, 1))
        groceries_group = next(g for g in review["budget"]["groups"] if g["name"] == "Everyday")
        groceries_row = next(c for c in groceries_group["categories"] if c["name"] == "Groceries")
        total_from_txns = sum(tx["amount"] for tx in review["cat_txns"][self.groceries.pk])
        self.assertEqual(total_from_txns, groceries_row["spent"])
        self.assertEqual(groceries_row["spent"], Decimal("100"))

    def test_no_history_at_all_yields_no_baselines(self):
        review = build_review(self.team, date(2026, 8, 1))
        self.assertEqual(review["baselines"], {})
        self.assertIsNone(review["default_baseline"])
        self.assertEqual(review["baseline_order"], [])

    def test_all_time_baseline_and_net_worth_span_back_to_first_activity(self):
        # 2+ years of history: longer than the 12-month baseline.
        self._entry(date(2024, 3, 5), self.salary, Decimal("1000"), dr_category=False)
        self._entry(date(2026, 6, 10), self.salary, Decimal("500"), dr_category=False)
        self._entry(date(2026, 8, 10), self.groceries, Decimal("100"))
        review = build_review(self.team, date(2026, 8, 1))

        self.assertEqual(review["baseline_order"][-1], "all")
        self.assertEqual(review["baselines"]["all"]["keys"][0], "2024-03-01")
        self.assertEqual(review["net_worth"]["series"][0]["key"], "2024-03-01")
        self.assertEqual(review["net_worth"]["series"][-1]["key"], "2026-08-01")

        # Change is measured from the end of the baseline's first month.
        chequing = next(r for r in review["net_worth"]["by_account"] if r["name"] == "Chequing")
        self.assertEqual(chequing["balance"], Decimal("1400"))
        self.assertEqual(chequing["changes"]["1m"], Decimal("-100"))  # since end of Jul 2026
        self.assertEqual(chequing["changes"]["3m"], Decimal("400"))  # since end of May 2026
        self.assertEqual(chequing["changes"]["all"], Decimal("400"))  # since end of Mar 2024

    def test_net_worth_bands_combine_feed_accounts_and_keep_other_groups(self):
        liability_group = AccountGroup.objects.create(team=self.team, name="Cards", account_type="liability")
        loan_group = AccountGroup.objects.create(team=self.team, name="Loans", account_type="liability")
        card = Account.objects.create(team=self.team, name="Visa", account_group=liability_group, has_feed=True)
        loan = Account.objects.create(team=self.team, name="Car loan", account_group=loan_group)

        def post(day, dr, cr, amount):
            entry = JournalEntry.objects.create(team=self.team, entry_date=day, description="t", status="posted")
            JournalLine.objects.create(team=self.team, journal_entry=entry, account=dr, dr_amount=amount)
            JournalLine.objects.create(team=self.team, journal_entry=entry, account=cr, cr_amount=amount)

        self._entry(date(2026, 7, 10), self.salary, Decimal("1000"), dr_category=False)  # chequing +1000
        post(date(2026, 8, 5), self.groceries, card, Decimal("80"))  # card owes 80
        post(date(2026, 8, 6), self.chequing, loan, Decimal("500"))  # borrowed 500 into chequing

        stack = build_review(self.team, date(2026, 8, 1))["net_worth"]["stack"]
        bands = {band["bucket"]: band for band in stack}

        # Chequing (feed) and the Visa (feed) are one band, net of each other.
        self.assertEqual(bands["Bank accounts & credit cards"]["type"], "cash")
        self.assertEqual(bands["Bank accounts & credit cards"]["values"][-1], 1000 + 500 - 80)
        # The loan is not on a feed: its own liability band, signed negative.
        self.assertEqual(bands["Loans"]["type"], "liability")
        self.assertEqual(bands["Loans"]["values"][-1], -500)
        self.assertNotIn("Cards", bands)
        # Bands sum to net worth.
        self.assertEqual(sum(band["values"][-1] for band in stack), 1000 - 80)
