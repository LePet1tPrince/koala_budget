from decimal import Decimal

from django.test import SimpleTestCase

from apps.utils.amounts import evaluate_amount


class EvaluateAmountTest(SimpleTestCase):
    """The server twin of common/amount.js: plain amounts and simple arithmetic."""

    def test_formulas(self):
        for raw, expected in (
            ("45.20+12.80", "58.00"),
            ("3*19.99", "59.97"),
            ("3x19.99", "59.97"),
            ("3 × 19.99", "59.97"),
            ("120/4", "30.00"),
            ("120÷4", "30.00"),
            ("1,200 - 85.50", "1114.50"),
            ("$10+$5", "15.00"),
            ("10+5*2", "20.00"),
            ("(10+5)*2", "30.00"),
            ("10*-2", "-20.00"),
            ("-5+3", "-2.00"),
            ("10−3", "7.00"),
            ("1/3", "0.33"),
            ("2.01/2", "1.01"),
            (".5+.5", "1.00"),
            ("5-5", "0.00"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(evaluate_amount(raw), Decimal(expected))

    def test_plain_numbers(self):
        for raw, expected in (("12", "12.00"), ("(45)", "-45.00"), ("-5", "-5.00"), ("$1,234.56", "1234.56")):
            with self.subTest(raw=raw):
                self.assertEqual(evaluate_amount(raw), Decimal(expected))

    def test_rejects_what_does_not_evaluate(self):
        for raw in ("", None, "abc", "5/0", "5+", "10+(2", "1.2.3", "NaN", "2**3", "9" * 100 + "*" + "9" * 90):
            with self.subTest(raw=raw):
                self.assertIsNone(evaluate_amount(raw))

    def test_negative_zero_is_zero(self):
        self.assertEqual(str(evaluate_amount("-0.001*1")), "0.00")
