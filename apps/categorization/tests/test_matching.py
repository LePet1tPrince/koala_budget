"""The rule matcher: pure, so tested against plain objects."""

from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.categorization.matching import RuleConditionError, compile_rule, first_match
from apps.categorization.models import CategorizationRule


def rule(**fields):
    return CategorizationRule(**fields)


def row(description="", merchant=None, amount="10.00", account_id=1):
    return SimpleNamespace(
        description=description, merchant_name=merchant, amount=Decimal(amount), account_id=account_id
    )


class TextConditionTest(SimpleTestCase):
    def test_equals_ignores_case_and_punctuation(self):
        compiled = compile_rule(rule(payee_match="equals", payee_value="Blue Bottle Coffee"))
        self.assertTrue(compiled.matches(row(merchant="BLUE-BOTTLE coffee")))
        self.assertFalse(compiled.matches(row(merchant="Blue Bottle Coffee Roasters")))
        self.assertFalse(compiled.matches(row(merchant=None)))

    def test_contains_matches_on_word_boundaries(self):
        compiled = compile_rule(rule(description_match="contains", description_value="bottle"))
        self.assertTrue(compiled.matches(row("SQ *BLUE BOTTLE 4417")))
        self.assertFalse(compiled.matches(row("SQ *BLUE BOTTLES")))
        compiled = compile_rule(rule(description_match="contains", description_value="blue bottle"))
        self.assertTrue(compiled.matches(row("sq*blue  bottle#9920")))

    def test_words_ignores_numbers_and_boilerplate(self):
        compiled = compile_rule(rule(description_match="words", description_value="SQ *BLUE BOTTLE 4417"))
        self.assertTrue(compiled.matches(row("POS PURCHASE BOTTLE BLUE 9920")))
        self.assertFalse(compiled.matches(row("BLUE APRON")))

    def test_words_with_nothing_distinctive_is_refused(self):
        with self.assertRaises(RuleConditionError):
            compile_rule(rule(description_match="words", description_value="POS 1234 card"))

    def test_blank_text_is_refused(self):
        with self.assertRaises(RuleConditionError):
            compile_rule(rule(payee_match="equals", payee_value="  ..  "))

    def test_payee_and_description_are_both_required_when_both_set(self):
        compiled = compile_rule(
            rule(payee_match="equals", payee_value="Shell", description_match="contains", description_value="gas")
        )
        self.assertTrue(compiled.matches(row("SHELL GAS 22", merchant="Shell")))
        self.assertFalse(compiled.matches(row("SHELL OIL DIVIDEND", merchant="Shell")))


class AmountDirectionAccountTest(SimpleTestCase):
    def test_exact_amount_matches_either_direction_by_size(self):
        compiled = compile_rule(rule(amount_min=Decimal("15.99"), amount_max=Decimal("15.99")))
        self.assertTrue(compiled.matches(row(amount="15.99")))
        self.assertTrue(compiled.matches(row(amount="-15.99")))
        self.assertFalse(compiled.matches(row(amount="16.00")))

    def test_open_and_closed_ranges(self):
        at_least = compile_rule(rule(amount_min=Decimal("100")))
        self.assertTrue(at_least.matches(row(amount="250")))
        self.assertFalse(at_least.matches(row(amount="99.99")))
        between = compile_rule(rule(amount_min=Decimal("10"), amount_max=Decimal("20")))
        self.assertTrue(between.matches(row(amount="-20")))
        self.assertFalse(between.matches(row(amount="20.01")))

    def test_direction(self):
        out = compile_rule(rule(description_match="contains", description_value="refund", direction="outflow"))
        into = compile_rule(rule(description_match="contains", description_value="refund", direction="inflow"))
        self.assertTrue(out.matches(row("refund", amount="5")))
        self.assertFalse(out.matches(row("refund", amount="-5")))
        self.assertTrue(into.matches(row("refund", amount="-5")))
        self.assertFalse(into.matches(row("refund", amount="5")))

    def test_account(self):
        compiled = compile_rule(rule(description_match="contains", description_value="fee", account_id=7))
        self.assertTrue(compiled.matches(row("monthly fee", account_id=7)))
        self.assertFalse(compiled.matches(row("monthly fee", account_id=8)))

    def test_a_rule_must_match_on_something(self):
        with self.assertRaises(RuleConditionError):
            compile_rule(rule(direction="outflow", account_id=7))
        with self.assertRaises(RuleConditionError):
            compile_rule(rule(amount_min=Decimal("20"), amount_max=Decimal("10")))
        with self.assertRaises(RuleConditionError):
            compile_rule(rule(amount_min=Decimal("-5")))


class PriorityTest(SimpleTestCase):
    def test_first_match_wins_in_the_order_given(self):
        broad = compile_rule(rule(name="broad", description_match="contains", description_value="coffee"))
        narrow = compile_rule(rule(name="narrow", description_match="contains", description_value="blue bottle coffee"))
        tx = row("BLUE BOTTLE COFFEE")
        self.assertEqual(first_match([narrow, broad], tx).rule.name, "narrow")
        self.assertEqual(first_match([broad, narrow], tx).rule.name, "broad")
        self.assertIsNone(first_match([narrow], row("TIM HORTONS")))
