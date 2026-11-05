"""The provider pipeline: merge order, filtering, the auto policy, and the endpoint contract."""

from unittest.mock import patch

from django.test import override_settings

from apps.bank_feed.services.categorize import categorize_single
from apps.budget.buckets import budget_group
from apps.categorization import pipeline
from apps.categorization.models import MODE_SUGGEST
from apps.categorization.providers.ai import AIProvider
from apps.categorization.providers.base import CategorizationProvider

from .base import RuleTestCase
from .doubles import AI_PATH, FakeAIProvider

WITH_AI = [*pipeline.DEFAULT_PROVIDERS, AI_PATH]


class MergeTest(RuleTestCase):
    def setUp(self):
        super().setUp()
        FakeAIProvider.reset()

    def history(self, description, category, n=2):
        for i in range(n):
            categorize_single(self.row(f"{description} {i}"), category)

    def test_rules_then_history_deduped_with_history_evidence_folded_in(self):
        self.history("SQ *BLUE BOTTLE", self.coffee, n=3)
        self.history("SQ *BLUE BOTTLE", self.groceries, n=1)
        self.rule(name="Coffee shops")
        row = self.row("SQ *BLUE BOTTLE 9999")

        suggestions = pipeline.suggest(self.book, [row])[row.id]

        self.assertEqual([s.category_id for s in suggestions], [self.coffee.id, self.groceries.id])
        top = suggestions[0]
        self.assertEqual((top.source, top.rule_name, top.count), ("rule", "Coffee shops", 3))
        self.assertEqual(top.category_name, "Coffee")

    @override_settings(CATEGORIZATION_PROVIDERS=WITH_AI)
    def test_an_appended_provider_ranks_after_rules_and_history(self):
        self.history("BLUE BOTTLE", self.coffee)
        row = self.row("BLUE BOTTLE 7")
        FakeAIProvider.reset({row.id: [(self.groceries.id, 0.99), (self.coffee.id, 0.5)]})

        suggestions = pipeline.suggest(self.book, [row])[row.id]

        self.assertEqual([s.source for s in suggestions], ["history", "ai"])
        self.assertEqual(suggestions[1].category_id, self.groceries.id)
        self.assertEqual(suggestions[1].category_name, "Groceries")
        self.assertEqual(FakeAIProvider.calls[0]["row_ids"], [row.id])

    @override_settings(CATEGORIZATION_PROVIDERS=WITH_AI)
    def test_non_pickable_categories_and_the_rows_own_account_are_dropped(self):
        row = self.row("ANYTHING")
        bucket = budget_group(self.book).accounts.first()
        FakeAIProvider.reset({row.id: [(bucket.id, 0.9), (self.chequing.id, 0.9), (self.coffee.id, 0.8)]})
        suggestions = pipeline.suggest(self.book, [row])[row.id]
        self.assertEqual([s.category_id for s in suggestions], [self.coffee.id])

    @override_settings(
        CATEGORIZATION_PROVIDERS=[*pipeline.DEFAULT_PROVIDERS, "apps.categorization.tests.doubles.BrokenProvider"]
    )
    def test_a_failing_provider_takes_nothing_else_down(self):
        self.rule()
        row = self.row("BLUE BOTTLE")
        self.assertEqual(pipeline.suggest(self.book, [row])[row.id][0].source, "rule")

    def test_the_providers_honour_the_protocol(self):
        for provider in pipeline.get_providers():
            self.assertIsInstance(provider, CategorizationProvider)
        self.assertIsInstance(AIProvider(), CategorizationProvider)
        self.assertEqual(AIProvider().suggest(None, []), {})


@override_settings(CATEGORIZATION_PROVIDERS=WITH_AI)
class AutoPolicyTest(RuleTestCase):
    def setUp(self):
        super().setUp()
        FakeAIProvider.reset()

    def test_only_an_auto_rule_files_on_arrival(self):
        auto_row = self.row("BLUE BOTTLE")
        suggest_rule_row = self.row("TIM HORTONS")
        ai_row = self.row("MYSTERY SHOP")
        self.rule(name="auto")
        self.rule(name="suggest", mode=MODE_SUGGEST, description_value="tim hortons")
        FakeAIProvider.reset({ai_row.id: [(self.groceries.id, 0.99)]})

        result = pipeline.categorize_on_arrival(self.book, [auto_row, suggest_rule_row, ai_row], trigger="test")

        self.assertEqual([row_id for row_id, _s in result.categorized], [auto_row.id])
        self.assertIsNone(self.category_of(ai_row))
        # Providers that could only ever suggest are not even asked on arrival.
        self.assertEqual(FakeAIProvider.calls, [])

    def test_ai_files_only_once_the_book_allows_it_and_only_when_confident(self):
        sure = self.row("MYSTERY SHOP")
        unsure = self.row("ANOTHER SHOP")
        FakeAIProvider.reset({sure.id: [(self.groceries.id, 0.95)], unsure.id: [(self.groceries.id, 0.6)]})

        with patch("apps.categorization.policy.book_allows_auto", return_value=True):
            result = pipeline.categorize_on_arrival(self.book, [sure, unsure], trigger="test")

        self.assertEqual([row_id for row_id, _s in result.categorized], [sure.id])
        sure.refresh_from_db()
        decision = sure.categorization_decision
        self.assertEqual((decision.source, decision.provider), ("ai", "ai"))
        self.assertEqual(decision.reason, "The model thinks so")
        self.assertIsNone(self.category_of(unsure))

    def test_a_suggest_rule_above_an_auto_rule_wins(self):
        row = self.row("BLUE BOTTLE")
        self.rule(name="suggest first", mode=MODE_SUGGEST, priority=0, category=self.groceries)
        self.rule(name="auto second", priority=1)
        self.assertIsNone(pipeline.categorize_on_arrival(self.book, [row], trigger="test"))
        self.assertIsNone(self.category_of(row))


class EndpointTest(RuleTestCase):
    def test_similar_categories_keeps_its_contract_and_adds_the_rule(self):
        categorize_single(self.row("SQ *BLUE BOTTLE 1"), self.coffee)
        self.rule(name="Coffee shops", set_payee="Blue Bottle")
        row = self.row("SQ *BLUE BOTTLE 2")

        response = self.client.get(
            f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/similar_categories/", {"ids": str(row.id)}
        )

        self.assertEqual(response.status_code, 200)
        [item] = response.json()
        for key in ("transaction_id", "category_id", "category_name", "count", "match_type", "payee"):
            self.assertIn(key, item)
        self.assertEqual(item["match_type"], "rule")
        self.assertEqual(item["rule_name"], "Coffee shops")
        self.assertEqual(item["count"], 1)
        self.assertEqual(item["decisions"], {"payee": "Blue Bottle"})
        self.assertTrue(item["auto"])
