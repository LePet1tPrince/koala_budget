from decimal import Decimal

from django.test import SimpleTestCase

from apps.monthly_review.services.insights import generate


class _Named:
    """Duck-typed stand-in for Account/Goal: insights.py only reads `.name`."""

    def __init__(self, name):
        self.name = name


def _baseline(**overrides):
    base = {
        "id": "3m",
        "label": "3-month average",
        "short": "3-mo",
        "against": "the 3-month average",
        "span": "May – Jul 2026",
        "months": 3,
        "clamped": False,
        "keys": ["2026-05-01", "2026-06-01", "2026-07-01"],
        "avgs": {
            "income": Decimal("3000"),
            "spend": Decimal("2000"),
            "net": Decimal("1000"),
            "saved": Decimal("100"),
            "savings_rate": 3.3,
        },
        "streams": [],
        "cat_avg": {},
        "saving_rows": [],
    }
    base.update(overrides)
    return base


def _review(**overrides):
    base = {
        "month": "2026-08-01",
        "month_label": "August 2026",
        "prev_label": "July 2026",
        "is_current_month": False,
        "health": {"accounts": [], "flags": [], "all_clear": True},
        "current": {
            "income": Decimal("3000"),
            "spend": Decimal("2000"),
            "net": Decimal("1000"),
            "saved": Decimal("100"),
            "savings_rate": 3.3,
            "transaction_count": 10,
        },
        "baselines": {},
        "baseline_order": [],
        "default_baseline": None,
        "budget": {"groups": [], "totals": {}, "overspent": [], "over_assigned": []},
        "biggest": [],
        "cat_txns": {},
        "net_worth": {
            "series": [
                {
                    "key": "2026-08-01",
                    "label": "Aug 2026",
                    "net": Decimal("1000"),
                    "assets": Decimal("1000"),
                    "liabilities": Decimal("0"),
                }
            ],
            "stack": [],
            "now": {"net": Decimal("1000"), "assets": Decimal("1000"), "liabilities": Decimal("0")},
            "prev": {"net": Decimal("800"), "assets": Decimal("800"), "liabilities": Decimal("0")},
            "by_account": [],
        },
        "notes": [],
    }
    base.update(overrides)
    return base


class Step1HealthInsightTests(SimpleTestCase):
    def test_all_clear(self):
        insights = generate(_review())
        kinds = [i.kind for i in insights if i.step == 1]
        self.assertEqual(kinds, ["all_clear"])
        self.assertEqual(insights[0].severity, "good")

    def test_no_transactions_is_bad(self):
        flag = {"kind": "no_transactions", "account": _Named("Chequing"), "url": "/inbox/"}
        review = _review(health={"accounts": [], "flags": [flag], "all_clear": False})
        step1 = [i for i in generate(review) if i.step == 1]
        self.assertEqual(len(step1), 1)
        self.assertEqual(step1[0].kind, "no_transactions")
        self.assertEqual(step1[0].severity, "bad")
        self.assertIn("Chequing", step1[0].title)

    def test_stale_account_is_warn(self):
        flag = {"kind": "stale_account", "account": _Named("Savings"), "days": 20, "url": ""}
        review = _review(health={"accounts": [], "flags": [flag], "all_clear": False})
        step1 = [i for i in generate(review) if i.step == 1]
        self.assertEqual(step1[0].severity, "warn")

    def test_uncategorized_is_warn(self):
        flag = {"kind": "uncategorized", "account": _Named("Chequing"), "count": 3, "url": ""}
        review = _review(health={"accounts": [], "flags": [flag], "all_clear": False})
        step1 = [i for i in generate(review) if i.step == 1]
        self.assertEqual(step1[0].severity, "warn")
        self.assertEqual(step1[0].metric, Decimal("3"))

    def test_unreconciled_is_warn(self):
        flag = {"kind": "unreconciled", "account": _Named("Chequing"), "count": 2, "gap": Decimal("15"), "url": ""}
        review = _review(health={"accounts": [], "flags": [flag], "all_clear": False})
        step1 = [i for i in generate(review) if i.step == 1]
        self.assertEqual(step1[0].severity, "warn")
        self.assertEqual(step1[0].delta, Decimal("15"))

    def test_balance_gap_is_warn(self):
        flag = {"kind": "balance_gap", "account": _Named("Chequing"), "gap": Decimal("-5"), "url": ""}
        review = _review(health={"accounts": [], "flags": [flag], "all_clear": False})
        step1 = [i for i in generate(review) if i.step == 1]
        self.assertEqual(step1[0].severity, "warn")


class Step2GlanceInsightTests(SimpleTestCase):
    def test_net_positive_is_good(self):
        review = _review(current={**_review()["current"], "net": Decimal("500")})
        step2 = [i for i in generate(review) if i.step == 2][0]
        self.assertEqual(step2.severity, "good")

    def test_net_negative_is_bad(self):
        review = _review(current={**_review()["current"], "net": Decimal("-500")})
        step2 = [i for i in generate(review) if i.step == 2][0]
        self.assertEqual(step2.severity, "bad")

    def test_names_baseline_comparison_when_present(self):
        review = _review(baselines={"3m": _baseline()}, default_baseline="3m")
        step2 = [i for i in generate(review) if i.step == 2][0]
        self.assertIn("3-month average", step2.body)


class Step3IncomeInsightTests(SimpleTestCase):
    def test_income_down_over_threshold_is_warn(self):
        baseline = _baseline(avgs={**_baseline()["avgs"], "income": Decimal("1000")})
        review = _review(
            baselines={"3m": baseline},
            default_baseline="3m",
            current={**_review()["current"], "income": Decimal("800")},  # 20% down
        )
        income_down = [i for i in generate(review) if i.kind == "income_down"]
        self.assertEqual(len(income_down), 1)
        self.assertEqual(income_down[0].severity, "warn")

    def test_income_down_under_threshold_is_silent(self):
        baseline = _baseline(avgs={**_baseline()["avgs"], "income": Decimal("1000")})
        review = _review(
            baselines={"3m": baseline},
            default_baseline="3m",
            current={**_review()["current"], "income": Decimal("950")},  # 5% down
        )
        income_down = [i for i in generate(review) if i.kind == "income_down"]
        self.assertEqual(income_down, [])

    def test_missing_stream_raises_no_insight(self):
        # An income stream not showing up this month is not noteworthy on its own
        # -- income streams are naturally irregular.
        stream = {
            "payee": "Acme Payroll",
            "amount": Decimal("0"),
            "avg": Decimal("500"),
            "vs_avg": Decimal("-500"),
            "new": False,
        }
        baseline = _baseline(streams=[stream])
        review = _review(baselines={"3m": baseline}, default_baseline="3m")
        missing = [i for i in generate(review) if i.kind == "stream_missing"]
        self.assertEqual(missing, [])

    def test_new_stream_is_info(self):
        stream = {
            "payee": "New Client",
            "amount": Decimal("300"),
            "avg": Decimal("0"),
            "vs_avg": Decimal("300"),
            "new": True,
        }
        baseline = _baseline(streams=[stream])
        review = _review(baselines={"3m": baseline}, default_baseline="3m")
        new_stream = [i for i in generate(review) if i.kind == "stream_new"]
        self.assertEqual(len(new_stream), 1)
        self.assertEqual(new_stream[0].severity, "info")


class Step4BudgetInsightTests(SimpleTestCase):
    def test_nothing_overspent_is_good(self):
        step4 = [i for i in generate(_review()) if i.step == 4]
        self.assertEqual([i.kind for i in step4], ["budget_clear"])
        self.assertEqual(step4[0].severity, "good")

    def test_overspent_is_bad(self):
        row = {
            "category": _Named("Groceries"),
            "group": _Named("Everyday"),
            "assigned": Decimal("200"),
            "spent": Decimal("400"),
            "available": Decimal("-100"),
            "over": Decimal("200"),
        }
        review = _review(budget={"groups": [], "totals": {}, "overspent": [row], "over_assigned": []})
        step4 = [i for i in generate(review) if i.step == 4]
        self.assertEqual(step4[0].kind, "overspent")
        self.assertEqual(step4[0].severity, "bad")

    def test_over_assigned_is_warn(self):
        row = {
            "category": _Named("Dining"),
            "group": _Named("Everyday"),
            "assigned": Decimal("100"),
            "spent": Decimal("120"),
            "available": Decimal("30"),
            "over": Decimal("20"),
        }
        review = _review(budget={"groups": [], "totals": {}, "overspent": [], "over_assigned": [row]})
        step4 = [i for i in generate(review) if i.step == 4]
        self.assertEqual(step4[0].kind, "over_assigned")
        self.assertEqual(step4[0].severity, "warn")


class Step5BiggestInsightTests(SimpleTestCase):
    def test_top_transactions_over_half_of_spend_is_info(self):
        biggest = [
            {"amount": Decimal("600"), "date": None, "payee": "", "category": "", "account": "", "entry_url": ""}
        ]
        review = _review(biggest=biggest, current={**_review()["current"], "spend": Decimal("1000")})
        step5 = [i for i in generate(review) if i.step == 5]
        self.assertEqual(len(step5), 1)
        self.assertEqual(step5[0].severity, "info")

    def test_top_transactions_under_half_is_silent(self):
        biggest = [
            {"amount": Decimal("100"), "date": None, "payee": "", "category": "", "account": "", "entry_url": ""}
        ]
        review = _review(biggest=biggest, current={**_review()["current"], "spend": Decimal("1000")})
        step5 = [i for i in generate(review) if i.step == 5]
        self.assertEqual(step5, [])


class Step6BreakdownInsightTests(SimpleTestCase):
    def test_unbudgeted_spend_is_warn(self):
        group = {
            "name": "Everyday",
            "categories": [{"id": 1, "name": "Misc", "spent": Decimal("30"), "unbudgeted": True}],
        }
        review = _review(budget={"groups": [group], "totals": {}, "overspent": [], "over_assigned": []})
        unbudgeted = [i for i in generate(review) if i.kind == "unbudgeted_spend"]
        self.assertEqual(len(unbudgeted), 1)
        self.assertEqual(unbudgeted[0].severity, "warn")

    def test_biggest_movers_reported(self):
        group = {
            "name": "Everyday",
            "categories": [
                {"id": 1, "name": "Groceries", "spent": Decimal("400"), "unbudgeted": False},
                {"id": 2, "name": "Dining", "spent": Decimal("10"), "unbudgeted": False},
            ],
        }
        baseline = _baseline(cat_avg={1: Decimal("200"), 2: Decimal("100")})
        review = _review(
            budget={"groups": [group], "totals": {}, "overspent": [], "over_assigned": []},
            baselines={"3m": baseline},
            default_baseline="3m",
        )
        movers = {i.kind: i for i in generate(review) if i.kind.startswith("biggest_mover")}
        self.assertIn("biggest_mover_up", movers)
        self.assertIn("biggest_mover_down", movers)
        self.assertIn("Groceries", movers["biggest_mover_up"].title)
        self.assertIn("Dining", movers["biggest_mover_down"].title)


class Step7SavingInsightTests(SimpleTestCase):
    def test_nothing_saved_is_warn(self):
        review = _review(current={**_review()["current"], "saved": Decimal("0")})
        step7 = [i for i in generate(review) if i.step == 7]
        self.assertEqual(step7[0].kind, "nothing_saved")
        self.assertEqual(step7[0].severity, "warn")

    def test_savings_rate_up_is_good(self):
        baseline = _baseline(avgs={**_baseline()["avgs"], "savings_rate": 1.0})
        review = _review(
            baselines={"3m": baseline},
            default_baseline="3m",
            current={**_review()["current"], "saved": Decimal("100"), "savings_rate": 5.0},
        )
        step7 = [i for i in generate(review) if i.step == 7]
        self.assertEqual(step7[0].severity, "good")

    def test_savings_rate_down_is_warn(self):
        baseline = _baseline(avgs={**_baseline()["avgs"], "savings_rate": 10.0})
        review = _review(
            baselines={"3m": baseline},
            default_baseline="3m",
            current={**_review()["current"], "saved": Decimal("100"), "savings_rate": 2.0},
        )
        step7 = [i for i in generate(review) if i.step == 7]
        self.assertEqual(step7[0].severity, "warn")


class Step8NetWorthInsightTests(SimpleTestCase):
    def test_net_worth_up_this_month_is_good(self):
        step8 = [i for i in generate(_review()) if i.kind == "net_worth_month"][0]
        self.assertEqual(step8.severity, "good")  # now=1000, prev=800

    def test_net_worth_down_this_month_is_bad(self):
        net_worth = _review()["net_worth"]
        net_worth = {**net_worth, "prev": {**net_worth["prev"], "net": Decimal("1500")}}
        review = _review(net_worth=net_worth)
        step8 = [i for i in generate(review) if i.kind == "net_worth_month"][0]
        self.assertEqual(step8.severity, "bad")

    def test_net_worth_window_change_uses_series_start(self):
        net_worth = _review()["net_worth"]
        net_worth = {
            **net_worth,
            "series": [
                {
                    "key": "2026-05-01",
                    "label": "May 2026",
                    "net": Decimal("500"),
                    "assets": Decimal("500"),
                    "liabilities": Decimal("0"),
                },
                {
                    "key": "2026-08-01",
                    "label": "Aug 2026",
                    "net": Decimal("1000"),
                    "assets": Decimal("1000"),
                    "liabilities": Decimal("0"),
                },
            ],
        }
        review = _review(net_worth=net_worth)
        window = [i for i in generate(review) if i.kind == "net_worth_window"][0]
        self.assertEqual(window.severity, "good")
        self.assertEqual(window.delta, Decimal("500"))


class GenerateAggregationTests(SimpleTestCase):
    def test_generate_returns_insights_across_all_steps(self):
        insights = generate(_review())
        steps = {i.step for i in insights}
        self.assertTrue(steps.issubset({1, 2, 3, 4, 5, 6, 7, 8}))
        self.assertIn(1, steps)
        self.assertIn(2, steps)
        self.assertIn(4, steps)
        self.assertIn(8, steps)
