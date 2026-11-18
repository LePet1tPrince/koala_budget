"""`apply.run`: suggesting, auto-posting, priority, holds and re-evaluation."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from apps.bank_feed.models import BankTransaction
from apps.books.context import current_book
from apps.journal.services.lines import write_lines
from apps.rules import constants
from apps.rules.models import Rule, RuleMatch
from apps.rules.services import apply

from .base import TODAY, RulesTestCase


class SuggestTest(RulesTestCase):
    def test_a_suggest_rule_records_a_suggestion_and_writes_no_entry(self):
        self.rule()
        tx = self.tx("STATE FARM INSURANCE", "145.00")
        counts = apply.run(self.book, [tx])
        self.assertEqual(counts["suggested"], 1)
        match = RuleMatch.objects.get(transaction=tx)
        self.assertEqual(match.status, RuleMatch.STATUS_SUGGESTED)
        self.assertEqual(match.category, self.insurance)
        self.assertIsNone(self.category_of(tx))

    def test_no_rule_matches(self):
        self.rule()
        tx = self.tx("Groceries")
        self.assertEqual(apply.run(self.book, [tx])["suggested"], 0)
        self.assertFalse(RuleMatch.objects.filter(transaction=tx).exists())

    def test_inactive_and_broken_rules_are_skipped(self):
        self.rule(is_active=False)
        broken = self.rule(name="Broken")
        Rule.objects.filter(pk=broken.pk).update(category=None)
        tx = self.tx("insurance")
        apply.run(self.book, [tx])
        self.assertFalse(RuleMatch.objects.filter(transaction=tx).exists())


class AutoPostTest(RulesTestCase):
    def test_an_auto_post_rule_categorizes_on_the_spot(self):
        rule = self.rule(mode=Rule.MODE_AUTO_POST)
        tx = self.tx("insurance", "145.00")
        counts = apply.run(self.book, [tx])
        self.assertEqual(counts["auto_posted"], 1)
        self.assertEqual(self.category_of(tx), self.insurance)
        match = RuleMatch.objects.get(transaction=tx)
        self.assertEqual(match.status, RuleMatch.STATUS_AUTO_POSTED)
        self.assertTrue(match.was_auto_posted)
        rule.refresh_from_db()
        self.assertEqual(rule.times_applied, 1)
        self.assertIsNotNone(rule.last_matched_at)

    def test_a_split_rule_posts_percentages_that_sum_exactly(self):
        Rule.objects.create(
            book=self.book,
            name="Costco",
            conditions=[{"field": "description", "op": "contains", "value": "costco"}],
            action=Rule.ACTION_SPLIT,
            splits=[
                {"category": self.groceries.pk, "percent": "33.333"},
                {"category": self.dining.pk, "percent": "66.667"},
            ],
            mode=Rule.MODE_AUTO_POST,
        )
        tx = self.tx("COSTCO WHOLESALE", "100.01")
        apply.run(self.book, [tx])
        tx.refresh_from_db()
        lines = {line.account_id: line.dr_amount - line.cr_amount for line in tx.journal_entry.lines.all()}
        self.assertEqual(lines[self.groceries.pk] + lines[self.dining.pk], Decimal("100.01"))
        self.assertEqual(lines[self.groceries.pk], Decimal("33.34"))

    def test_renames_apply_to_the_row_and_the_entry(self):
        self.rule(
            conditions=[{"field": "description", "op": "contains", "value": "amzn mktp"}],
            category=self.groceries,
            payee_name="Amazon",
            mode=Rule.MODE_AUTO_POST,
        )
        tx = self.tx("AMZN MKTP US*2K4", "12.00")
        apply.run(self.book, [tx])
        tx.refresh_from_db()
        self.assertEqual(tx.merchant_name, "Amazon")
        self.assertEqual(tx.journal_entry.payee.name, "Amazon")
        self.assertEqual(RuleMatch.objects.get(transaction=tx).before["description"], "AMZN MKTP US*2K4")


class PriorityTest(RulesTestCase):
    def test_lower_priority_value_wins_and_reordering_flips_it(self):
        first = self.rule(name="Insurance", priority=0)
        second = self.rule(name="Also insurance", category=self.groceries, priority=1)
        tx = self.tx("insurance")
        apply.run(self.book, [tx])
        self.assertEqual(RuleMatch.objects.get(transaction=tx).rule, first)

        Rule.objects.filter(pk=first.pk).update(priority=2)
        apply.refresh(self.book)
        self.assertEqual(RuleMatch.objects.get(transaction=tx).rule, second)


class EligibilityAndHoldsTest(RulesTestCase):
    def setUp(self):
        super().setUp()
        self.auto = self.rule(mode=Rule.MODE_AUTO_POST)

    def test_closed_period_is_held(self):
        self.book.locked_through = TODAY
        self.book.save()
        tx = self.tx("insurance", posted_date=TODAY - timedelta(days=1))
        apply.run(self.book, [tx])
        match = RuleMatch.objects.get(transaction=tx)
        self.assertEqual((match.status, match.held_reason), (RuleMatch.STATUS_SUGGESTED, RuleMatch.HELD_CLOSED_PERIOD))
        self.assertIsNone(self.category_of(tx))

    def test_transfer_candidate_is_held(self):
        tx = self.tx("insurance", "200.00")
        with mock.patch("apps.bank_feed.services.feed_query.transfer_candidate_ids", return_value={tx.pk}):
            apply.run(self.book, [tx])
        self.assertEqual(RuleMatch.objects.get(transaction=tx).held_reason, RuleMatch.HELD_TRANSFER_CANDIDATE)

    def test_unusual_amount_is_held_once_there_are_enough_samples(self):
        for _ in range(constants.ANOMALY_MIN_SAMPLES):
            apply.run(self.book, [self.tx("insurance", "100.00")])
        big = self.tx("insurance", "301.00")
        apply.run(self.book, [big])
        self.assertEqual(RuleMatch.objects.get(transaction=big).held_reason, RuleMatch.HELD_UNUSUAL_AMOUNT)
        fine = self.tx("insurance", "299.00")
        apply.run(self.book, [fine])
        self.assertEqual(RuleMatch.objects.get(transaction=fine).status, RuleMatch.STATUS_AUTO_POSTED)

    def test_the_guard_is_off_below_the_sample_floor(self):
        apply.run(self.book, [self.tx("insurance", "10.00")])
        big = self.tx("insurance", "10000.00")
        apply.run(self.book, [big])
        self.assertEqual(RuleMatch.objects.get(transaction=big).status, RuleMatch.STATUS_AUTO_POSTED)

    def test_void_mirror_manual_and_revision_rows_are_never_touched(self):
        rows = [
            self.tx("insurance", is_void=True),
            self.tx("insurance", is_transfer_mirror=True),
            self.tx("insurance", source=BankTransaction.SOURCE_MANUAL),
            self.tx("insurance", source=BankTransaction.SOURCE_YNAB),
            self.tx("insurance", raw={"revision_of": 1}),
        ]
        apply.run(self.book, rows)
        self.assertFalse(RuleMatch.objects.filter(transaction__in=rows).exists())
        for row in rows:
            self.assertIsNone(self.category_of(row))

    def test_a_categorized_row_is_left_alone(self):
        tx = self.tx("insurance")
        with current_book(self.book):
            from apps.bank_feed.services.categorize import create_entry

            create_entry(tx, self.groceries)
        apply.run(self.book, [tx])
        self.assertEqual(self.category_of(tx), self.groceries)

    def test_a_refusal_becomes_a_held_suggestion_not_an_error(self):
        tx = self.tx("insurance")
        with mock.patch("apps.rules.services.actions.post", side_effect=ValueError("nope")):
            apply.run(self.book, [tx])
        match = RuleMatch.objects.get(transaction=tx)
        self.assertEqual((match.status, match.held_reason), (RuleMatch.STATUS_SUGGESTED, RuleMatch.HELD_REFUSED))

    def test_rule_edits_never_auto_post_retroactively(self):
        tx = self.tx("insurance")
        apply.refresh(self.book)
        self.assertEqual(RuleMatch.objects.get(transaction=tx).status, RuleMatch.STATUS_SUGGESTED)
        apply.run(self.book, auto_post_rule_ids={self.auto.pk})
        self.assertEqual(RuleMatch.objects.get(transaction=tx).status, RuleMatch.STATUS_AUTO_POSTED)


class ReEvaluationTest(RulesTestCase):
    def test_a_row_no_rule_wins_any_more_gets_its_names_back(self):
        rule = self.rule(payee_name="State Farm")
        tx = self.tx("STATE FARM INSURANCE", payee="SF*INS")
        apply.run(self.book, [tx])
        tx.refresh_from_db()
        self.assertEqual(tx.merchant_name, "State Farm")
        rule.delete()
        apply.refresh(self.book)
        tx.refresh_from_db()
        self.assertEqual(tx.merchant_name, "SF*INS")
        self.assertFalse(RuleMatch.objects.filter(transaction=tx).exists())

    def test_a_rename_does_not_change_which_rule_wins(self):
        self.rule(
            name="By payee",
            conditions=[{"field": "payee", "op": "contains", "value": "sf ins"}],
            payee_name="State Farm",
        )
        tx = self.tx("x", payee="SF INS")
        apply.run(self.book, [tx])
        apply.refresh(self.book)
        apply.refresh(self.book)
        self.assertEqual(RuleMatch.objects.get(transaction=tx).rule.name, "By payee")

    def test_settled_rows_stay_settled(self):
        self.rule()
        tx = self.tx("insurance")
        apply.run(self.book, [tx])
        RuleMatch.objects.filter(transaction=tx).update(status=RuleMatch.STATUS_DISMISSED)
        apply.refresh(self.book)
        self.assertEqual(RuleMatch.objects.get(transaction=tx).status, RuleMatch.STATUS_DISMISSED)


class IngestionTest(RulesTestCase):
    def test_csv_import_runs_rules_on_uncategorized_rows(self):
        self.rule(mode=Rule.MODE_AUTO_POST)
        response = self.api.post(
            self.url("bankfeed/api/feed/upload_confirm/"),
            {
                "account_id": self.chequing.pk,
                "transactions": [
                    {"date": TODAY.isoformat(), "description": "ACME INSURANCE", "payee": "", "amount": "145.00"},
                    {"date": TODAY.isoformat(), "description": "Bakery", "payee": "", "amount": "5.00"},
                ],
                "skip_duplicates": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["rules_auto_posted"], 1)
        row = BankTransaction.objects.get(description="ACME INSURANCE")
        self.assertEqual(self.category_of(row), self.insurance)

    def test_a_crash_in_the_rules_never_fails_the_import(self):
        self.rule()
        with mock.patch("apps.rules.services.apply.run", side_effect=RuntimeError("boom")):
            response = self.api.post(
                self.url("bankfeed/api/feed/upload_confirm/"),
                {
                    "account_id": self.chequing.pk,
                    "transactions": [
                        {"date": TODAY.isoformat(), "description": "insurance", "payee": "", "amount": "1"}
                    ],
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created_count"], 1)

    def test_plaid_sync_runs_rules_after_the_rows_commit(self):
        from apps.plaid.models import PlaidAccount, PlaidItem
        from apps.plaid.tasks import SyncUpdates, _sync_item

        self.rule(mode=Rule.MODE_AUTO_POST)
        item = PlaidItem.objects.create(
            book=self.book, plaid_item_id="item-1", access_token="tok", institution_name="Bank", cursor="c0"
        )
        PlaidAccount.objects.create(
            book=self.book,
            item=item,
            plaid_account_id="acc-1",
            account=self.chequing,
            name="Chq",
            subtype="checking",
            type="depository",
        )
        tx_data = {
            "transaction_id": "t-1",
            "account_id": "acc-1",
            "amount": 145.0,
            "date": TODAY,
            "name": "GEICO INSURANCE",
            "merchant_name": None,
            "pending": False,
        }
        updates = SyncUpdates(added=[tx_data], next_cursor="c1")
        with mock.patch("apps.plaid.tasks.fetch_updates", return_value=updates):
            result = _sync_item(item.pk)
        self.assertTrue(result["success"], result)
        row = BankTransaction.objects.get(description="GEICO INSURANCE")
        self.assertEqual(self.category_of(row), self.insurance)


class WriteDisciplineTest(RulesTestCase):
    def test_rules_never_write_journal_rows_directly(self):
        """Every write goes through apps.bank_feed.services (CLAUDE.md single-writer rules)."""
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1]
        pattern = re.compile(r"JournalLine\.objects\.(create|bulk_create)|JournalEntry\.objects\.create|write_lines\(")
        offenders = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if "tests" not in path.parts and pattern.search(path.read_text())
        ]
        self.assertEqual(offenders, [])
        self.assertTrue(callable(write_lines))
