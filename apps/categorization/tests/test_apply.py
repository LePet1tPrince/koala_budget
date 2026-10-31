"""Filing rows from rules: through the bank feed's write path, row by row, traceably."""

from decimal import Decimal
from unittest.mock import patch

from apps.audit.models import AuditEvent, AuditLog
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.categorize import categorize_single
from apps.categorization import apply as rule_apply
from apps.categorization.models import MODE_SUGGEST, CategorizationDecision
from apps.categorization.providers.rules import suggestion_for
from apps.categorization.summary import decision_summary
from apps.journal.services import voiding

from .base import RuleTestCase


class ApplyRuleTest(RuleTestCase):
    def test_files_every_matching_uncategorized_row(self):
        rule = self.rule()
        a = self.row("SQ *BLUE BOTTLE 4417")
        b = self.row("SQ *BLUE BOTTLE 9920", account=self.visa)
        other = self.row("TIM HORTONS 12")

        result = rule_apply.apply_rule(rule, user=self.admin)

        self.assertEqual(result.categorized_count, 2)
        self.assertEqual(self.category_of(a), self.coffee)
        self.assertEqual(self.category_of(b), self.coffee)
        self.assertIsNone(self.category_of(other))

    def test_never_touches_categorized_void_mirror_or_split_rows(self):
        rule = self.rule()
        categorized = self.row("BLUE BOTTLE 1")
        categorize_single(categorized, self.groceries)
        void = self.row("BLUE BOTTLE 2")
        voiding.void(rows=[void])
        transfer = self.row("BLUE BOTTLE 3")
        categorize_single(transfer, self.savings)
        mirror = BankTransaction.objects.get(is_transfer_mirror=True)
        self.assertIn("BLUE BOTTLE", mirror.description)  # it would match, if mirrors were eligible

        result = rule_apply.apply_rule(rule)

        self.assertEqual(result.categorized_count, 0)
        self.assertEqual(self.category_of(categorized), self.groceries)
        void.refresh_from_db()
        self.assertIsNone(void.journal_entry_id)
        self.assertFalse(CategorizationDecision.objects.filter(bank_transaction=mirror).exists())
        self.assertEqual(self.category_of(transfer), self.savings)

    def test_a_split_is_never_refiled(self):
        rule = self.rule()
        split = self.row("BLUE BOTTLE SPLIT", amount="10.00")
        entry = categorize_single(split, self.groceries)
        entry.lines.exclude(account=self.chequing).delete()
        entry.lines.create(book=self.book, account=self.groceries, dr_amount=Decimal("6"), cr_amount=Decimal("0"))
        entry.lines.create(book=self.book, account=self.coffee, dr_amount=Decimal("4"), cr_amount=Decimal("0"))
        self.assertEqual(rule_apply.apply_rule(rule).categorized_count, 0)
        self.assertEqual(entry.lines.count(), 3)

    def test_a_row_in_the_rules_own_category_account_is_skipped(self):
        rule = self.rule(category=self.savings)
        in_savings = self.row("BLUE BOTTLE", account=self.savings)
        self.assertEqual(rule_apply.apply_rule(rule).categorized_count, 0)
        self.assertIsNone(self.category_of(in_savings))

    def test_a_transfer_target_creates_the_mirror(self):
        rule = self.rule(category=self.savings, description_match="contains", description_value="to savings")
        row = self.row("TRANSFER TO SAVINGS", amount="200.00")

        rule_apply.apply_rule(rule)

        row.refresh_from_db()
        mirror = BankTransaction.objects.get(account=self.savings, is_transfer_mirror=True)
        self.assertEqual(mirror.journal_entry_id, row.journal_entry_id)
        self.assertEqual(mirror.amount, Decimal("-200.00"))

    def test_renames_payee_and_description(self):
        rule = self.rule(set_payee="Blue Bottle", set_description="Coffee")
        row = self.row("SQ *BLUE BOTTLE 4417", merchant="SQ BLUE BTL")

        rule_apply.apply_rule(rule)

        row.refresh_from_db()
        self.assertEqual(row.merchant_name, "Blue Bottle")
        self.assertEqual(row.description, "Coffee")
        self.assertEqual(row.journal_entry.description, "Coffee")
        self.assertEqual(row.journal_entry.payee.name, "Blue Bottle")
        decision = row.categorization_decision
        self.assertEqual(decision.original_payee, "SQ BLUE BTL")
        self.assertEqual(decision.original_description, "SQ *BLUE BOTTLE 4417")

    def test_a_refusal_is_reported_for_that_row_and_the_rest_are_filed(self):
        rule = self.rule()
        refused = self.row("BLUE BOTTLE 1")
        filed = self.row("BLUE BOTTLE 2")

        def flaky(row, category):
            if row.pk == refused.pk:
                raise ValueError("This period is locked.")
            return categorize_single(row, category)

        with patch("apps.categorization.apply.categorize_single", side_effect=flaky):
            result = rule_apply.apply_rule(rule)

        self.assertEqual(result.categorized_count, 1)
        self.assertEqual(result.refused, [{"id": refused.pk, "error": "This period is locked."}])
        self.assertIsNone(self.category_of(refused))
        self.assertEqual(self.category_of(filed), self.coffee)
        self.assertFalse(CategorizationDecision.objects.filter(bank_transaction=refused).exists())

    def test_a_rename_is_rolled_back_with_its_refused_row(self):
        rule = self.rule(set_payee="Blue Bottle")
        row = self.row("BLUE BOTTLE", merchant="original")
        with patch("apps.categorization.apply.categorize_single", side_effect=ValueError("no")):
            rule_apply.apply_rule(rule)
        row.refresh_from_db()
        self.assertEqual(row.merchant_name, "original")

    def test_an_archived_category_is_refused_per_row(self):
        rule = self.rule()
        row = self.row("BLUE BOTTLE")
        self.coffee.is_archived = True
        self.coffee.save()
        try:
            result = rule_apply.apply_suggestions(self.book, [(row, suggestion_for(rule))], trigger="test")
        finally:
            self.coffee.is_archived = False
            self.coffee.save()
        self.assertEqual(result.categorized_count, 0)
        self.assertEqual(len(result.refused), 1)


class TraceabilityTest(RuleTestCase):
    def test_a_decision_is_recorded_and_stands_until_refiled_by_hand(self):
        rule = self.rule(name="Coffee shops")
        row = self.row("BLUE BOTTLE")
        rule_apply.apply_rule(rule)
        row.refresh_from_db()

        summary = decision_summary(row, self.coffee.id)
        self.assertEqual(summary["source"], "rule")
        self.assertEqual(summary["rule_name"], "Coffee shops")
        self.assertEqual(summary["label"], "Rule")

        categorize_single(row, self.groceries)
        row.refresh_from_db()
        self.assertIsNone(decision_summary(row, self.groceries.id))

    def test_one_audit_event_per_rule_and_the_history_says_via_rule(self):
        rule = self.rule(name="Coffee shops")
        rows = [self.row("BLUE BOTTLE 1"), self.row("BLUE BOTTLE 2")]

        rule_apply.apply_rule(rule, user=self.admin)

        event = AuditEvent.objects.get(event_type=AuditEvent.AUTO_CATEGORIZED)
        self.assertEqual(event.metadata["count"], 2)
        self.assertEqual(event.metadata["rule_id"], rule.id)
        self.assertEqual(event.metadata["trigger"], "apply_existing")
        self.assertEqual(sorted(event.metadata["transaction_ids"]), sorted(r.id for r in rows))
        rows[0].refresh_from_db()
        logs = AuditLog.objects.filter(journal_entry_id=rows[0].journal_entry_id)
        self.assertTrue(logs.exists())
        self.assertTrue(all(log.event_id == event.id for log in logs))

        response = self.client.get(
            f"/a/{self.team.slug}/{self.book.slug}/journal/api/journal-entries/{rows[0].journal_entry_id}/audit/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("rule “Coffee shops”", {log["via"] for log in response.json()})

    def test_the_feed_row_carries_the_badge(self):
        rule = self.rule(name="Coffee shops")
        row = self.row("BLUE BOTTLE")
        rule_apply.apply_rule(rule)
        response = self.client.get(
            f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/", {"account": self.chequing.id}
        )
        feed_row = next(r for r in response.json()["results"] if r["id"] == str(row.id))
        self.assertEqual(feed_row["categorized_by"]["rule_name"], "Coffee shops")
        self.assertEqual(feed_row["categorized_by"]["source"], "rule")

    def test_decategorizing_removes_the_decision(self):
        rule = self.rule()
        row = self.row("BLUE BOTTLE")
        rule_apply.apply_rule(rule)
        row.refresh_from_db()
        row.journal_entry.delete()
        self.assertFalse(CategorizationDecision.objects.filter(bank_transaction=row).exists())


class PreviewTest(RuleTestCase):
    def test_counts_uncategorized_matches_and_checks_history(self):
        rule = self.rule(mode=MODE_SUGGEST)
        self.row("BLUE BOTTLE 1")
        self.row("BLUE BOTTLE 2")
        agree = self.row("BLUE BOTTLE 3")
        categorize_single(agree, self.coffee)
        disagree = self.row("BLUE BOTTLE 4")
        categorize_single(disagree, self.groceries)
        self.row("SOMETHING ELSE")

        result = rule_apply.preview(self.book, rule)

        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["sample"]), 2)
        self.assertEqual(result["categorized_count"], 2)
        self.assertEqual(result["agreeing_count"], 1)
