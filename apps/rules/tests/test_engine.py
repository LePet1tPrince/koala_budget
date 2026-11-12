"""The matcher: pure, so table-driven over plain objects."""

from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.rules.services import engine


def row(description="", payee=None, amount="10", account_id=1):
    return SimpleNamespace(description=description, merchant_name=payee, amount=Decimal(amount), account_id=account_id)


def rule(conditions, direction="any", accounts=(), match="all", priority=0, pk=1):
    return engine.compile_rule(
        SimpleNamespace(pk=pk, priority=priority, direction=direction, match=match, conditions=conditions),
        account_ids=accounts,
    )


def cond(field, op, value):
    return {"field": field, "op": op, "value": value}


class ConditionTest(SimpleTestCase):
    def test_text_operations(self):
        cases = [
            (cond("description", "contains", "insurance"), row("STATE FARM INSURANCE 4471"), True),
            (cond("description", "contains", "INSURANCE"), row("state-farm insurance"), True),
            (cond("description", "contains", "farm ins"), row("STATE*FARM   INS."), True),
            (cond("description", "contains", "insurance"), row("Groceries"), False),
            (cond("description", "not_contains", "refund"), row("Insurance payment"), True),
            (cond("description", "not_contains", "refund"), row("Insurance REFUND"), False),
            (cond("description", "equals", "netflix com"), row("NETFLIX.COM"), True),
            (cond("description", "equals", "netflix"), row("NETFLIX.COM"), False),
            (cond("payee", "contains", "amazon"), row("x", payee="Amazon Mktp"), True),
            (cond("payee", "contains", "amazon"), row("amazon", payee=None), False),
            (cond("payee", "not_contains", "amazon"), row("x", payee=None), True),
        ]
        for raw, tx, expected in cases:
            with self.subTest(condition=raw, tx=tx.description):
                self.assertIs(engine.condition_holds(tx, engine.compile_condition(raw)), expected)

    def test_amount_operations_compare_the_absolute_amount(self):
        cases = [
            (cond("amount", "gt", "120"), "120.01", True),
            (cond("amount", "gt", "120"), "120.00", False),
            (cond("amount", "gt", "120"), "-150.00", True),
            (cond("amount", "lt", "20"), "19.99", True),
            (cond("amount", "equals", "15.99"), "-15.99", True),
            (cond("amount", "between", ["10", "20"]), "10.00", True),
            (cond("amount", "between", ["10", "20"]), "20.00", True),
            (cond("amount", "between", ["20", "10"]), "15.00", True),
            (cond("amount", "between", ["10", "20"]), "20.01", False),
        ]
        for raw, amount, expected in cases:
            with self.subTest(condition=raw, amount=amount):
                self.assertIs(engine.condition_holds(row(amount=amount), engine.compile_condition(raw)), expected)

    def test_bad_conditions_are_refused(self):
        for raw in (
            cond("memo", "contains", "x"),
            cond("description", "gt", "x"),
            cond("description", "contains", "  ***  "),
            cond("amount", "gt", "lots"),
            cond("amount", "between", ["1"]),
            "not a dict",
        ):
            with self.subTest(raw=raw), self.assertRaises(engine.ConditionError):
                engine.compile_condition(raw)


class RuleMatchingTest(SimpleTestCase):
    def test_direction(self):
        out = row("x", amount="5")
        money_in = row("x", amount="-5")
        self.assertTrue(engine.matches(out, rule([], direction="out")))
        self.assertFalse(engine.matches(money_in, rule([], direction="out")))
        self.assertTrue(engine.matches(money_in, rule([], direction="in")))

    def test_accounts(self):
        self.assertTrue(engine.matches(row(account_id=1), rule([], accounts=[1, 2])))
        self.assertFalse(engine.matches(row(account_id=3), rule([], accounts=[1, 2])))
        self.assertTrue(engine.matches(row(account_id=3), rule([], direction="out")))

    def test_all_and_any(self):
        conditions = [cond("description", "contains", "insurance"), cond("amount", "gt", "120")]
        self.assertFalse(engine.matches(row("insurance", amount="100"), rule(conditions)))
        self.assertTrue(engine.matches(row("insurance", amount="130"), rule(conditions)))
        self.assertTrue(engine.matches(row("insurance", amount="100"), rule(conditions, match="any")))
        self.assertFalse(engine.matches(row("food", amount="100"), rule(conditions, match="any")))

    def test_the_example_rule(self):
        """Money out, more than $120, description contains INSURANCE."""
        example = rule([cond("amount", "gt", "120"), cond("description", "contains", "INSURANCE")], direction="out")
        self.assertTrue(engine.matches(row("ACME INSURANCE CO", amount="145.20"), example))
        self.assertFalse(engine.matches(row("ACME INSURANCE CO", amount="-145.20"), example))
        self.assertFalse(engine.matches(row("ACME INSURANCE CO", amount="99"), example))

    def test_lower_priority_value_wins_then_id(self):
        a = rule([cond("description", "contains", "shop")], priority=1, pk=10)
        b = rule([cond("description", "contains", "shop")], priority=0, pk=20)
        c = rule([cond("description", "contains", "shop")], priority=0, pk=5)
        self.assertEqual(engine.first_match(row("shop"), engine.ordered([a, b, c])).id, 5)

    def test_explain_names_the_failing_condition(self):
        r = rule([cond("description", "contains", "insurance"), cond("amount", "gt", "120")], direction="out")
        result = engine.explain(row("insurance", amount="100"), r)
        self.assertFalse(result["matched"])
        self.assertEqual([c["passed"] for c in result["conditions"]], [True, False])
        self.assertTrue(result["direction"]["passed"])

    def test_specificity(self):
        self.assertEqual(engine.specificity([], [], "any"), 0)
        self.assertEqual(engine.specificity([cond("description", "contains", "x")], [1], "out"), 3)
