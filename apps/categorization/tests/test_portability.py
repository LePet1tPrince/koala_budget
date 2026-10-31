"""Rules travel in the export (format v8); decisions don't; wipe_book clears both."""

from django.test import SimpleTestCase

from apps.books.helpers import create_book
from apps.categorization import apply as rule_apply
from apps.categorization.models import CategorizationDecision, CategorizationRule
from apps.portability.services import apply as portability_apply
from apps.portability.services import schema, upgrade
from apps.portability.services.wipe import wipe_book

from .base import RuleTestCase


class RoundTripTest(RuleTestCase):
    def test_rules_travel_with_their_accounts_remapped(self):
        self.rule(name="Coffee shops", account=self.visa, set_payee="Blue Bottle", priority=3, is_enabled=False)
        self.rule(name="Pay", category=self.salary, description_match="contains", description_value="payroll")
        rule_apply.apply_rule(CategorizationRule.objects.get(name="Pay"))

        archive = portability_apply.build_safety_archive(self.book)
        other = create_book(self.team, "Copy")
        portability_apply.apply_archive(other, archive)

        copied = {rule.name: rule for rule in CategorizationRule.objects.filter(book=other)}
        self.assertEqual(set(copied), {"Coffee shops", "Pay"})
        coffee = copied["Coffee shops"]
        self.assertEqual(coffee.category.book, other)
        self.assertEqual(coffee.category.name, "Coffee")
        self.assertEqual(coffee.account.name, "Visa")
        self.assertEqual(coffee.account.book, other)
        self.assertEqual((coffee.priority, coffee.is_enabled, coffee.set_payee), (3, False, "Blue Bottle"))
        # Provenance does not travel.
        self.assertFalse(CategorizationDecision.objects.filter(book=other).exists())

    def test_wipe_book_clears_rules_and_decisions_and_leaves_a_sibling_alone(self):
        rule = self.rule()
        self.row("BLUE BOTTLE")
        rule_apply.apply_rule(rule)
        sibling = create_book(self.team, "Sibling")
        sibling_rule = CategorizationRule.objects.create(
            book=sibling, name="Theirs", description_match="contains", description_value="x"
        )

        counts = wipe_book(self.book)

        self.assertEqual((counts.categorization_rules, counts.categorization_decisions), (1, 1))
        self.assertFalse(CategorizationRule.objects.filter(book=self.book).exists())
        self.assertTrue(CategorizationRule.objects.filter(pk=sibling_rule.pk).exists())


class FormatTest(SimpleTestCase):
    def test_an_older_archive_upgrades_to_no_rules(self):
        self.assertEqual(upgrade.upgrade_7_to_8({"accounts": []})["rules"], [])
        self.assertEqual(schema.FILES_ADDED_IN[schema.RULES_FILE], 8)

    def test_every_model_of_the_app_travels_or_is_a_documented_omission(self):
        from django.apps import apps

        exported = {field_map.model for field_map in schema.FIELD_MAPS}
        for model in apps.get_app_config("categorization").get_models():
            with self.subTest(model=model.__name__):
                self.assertTrue(model in exported or schema.UNEXPORTED_MODELS.get(model))
