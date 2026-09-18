from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.monthly_review.services.baselines import (
    MonthlyMatrix,
    build_baselines,
    clamp_window,
)


def _months_matrix(first_month, month, income_by_month=None, spend_by_month=None):
    """A minimal matrix spanning first_month..month (inclusive), zero-filled."""
    months = []
    cursor = first_month
    while cursor <= month:
        months.append(cursor)
        cursor = date(cursor.year + (cursor.month // 12), cursor.month % 12 + 1, 1)

    income = income_by_month or {m: Decimal("0") for m in months}
    spend = spend_by_month or {m: Decimal("0") for m in months}
    net = {m: income.get(m, Decimal("0")) - spend.get(m, Decimal("0")) for m in months}
    saved = {m: Decimal("0") for m in months}
    savings_rate = {m: 0.0 for m in months}

    return MonthlyMatrix(
        months=months,
        income=income,
        spend=spend,
        net=net,
        saved=saved,
        savings_rate=savings_rate,
        first_month=first_month,
    )


class ClampWindowTests(SimpleTestCase):
    def test_no_history_returns_empty(self):
        self.assertEqual(clamp_window(date(2026, 8, 1), 3, None), [])

    def test_full_window_when_history_is_long_enough(self):
        window = clamp_window(date(2026, 8, 1), 3, date(2025, 1, 1))
        self.assertEqual(window, [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1)])

    def test_clamped_when_history_starts_inside_window(self):
        # First activity is June 2026; a 3-month baseline for August can only
        # reach back to June and July -- two months, not three.
        window = clamp_window(date(2026, 8, 1), 3, date(2026, 6, 1))
        self.assertEqual(window, [date(2026, 6, 1), date(2026, 7, 1)])

    def test_reviewing_the_first_month_yields_no_window(self):
        window = clamp_window(date(2026, 8, 1), 3, date(2026, 8, 1))
        self.assertEqual(window, [])

    def test_reviewing_before_first_activity_yields_no_window(self):
        window = clamp_window(date(2026, 1, 1), 3, date(2026, 8, 1))
        self.assertEqual(window, [])

    def test_never_includes_the_reviewed_month(self):
        window = clamp_window(date(2026, 8, 1), 12, date(2020, 1, 1))
        self.assertNotIn(date(2026, 8, 1), window)
        self.assertEqual(window[-1], date(2026, 7, 1))

    def test_crosses_year_boundary(self):
        window = clamp_window(date(2026, 2, 1), 3, date(2020, 1, 1))
        self.assertEqual(window, [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1)])


class BuildBaselinesTests(SimpleTestCase):
    def test_zero_history_yields_no_baselines(self):
        matrix = _months_matrix(date(2026, 8, 1), date(2026, 8, 1))
        baselines, order, default = build_baselines(matrix, date(2026, 8, 1))
        self.assertEqual(baselines, {})
        self.assertEqual(order, [])
        self.assertIsNone(default)

    def test_one_prior_month_only_yields_clamped_baselines(self):
        matrix = _months_matrix(date(2026, 7, 1), date(2026, 8, 1))
        baselines, order, default = build_baselines(matrix, date(2026, 8, 1))
        # Only enough history for a (clamped) 1m; 3/6/12m all clamp to the
        # same single month too, since that's all there is.
        self.assertEqual(set(order), {"1m", "3m", "6m", "12m"})
        self.assertEqual(baselines["1m"]["months"], 1)
        self.assertFalse(baselines["1m"]["clamped"])  # 1m with exactly 1 month is not clamped
        self.assertEqual(baselines["3m"]["months"], 1)
        self.assertTrue(baselines["3m"]["clamped"])
        self.assertEqual(default, "3m")

    def test_1m_is_last_month_not_an_average(self):
        income = {
            date(2026, 5, 1): Decimal("100"),
            date(2026, 6, 1): Decimal("200"),
            date(2026, 7, 1): Decimal("900"),
            date(2026, 8, 1): Decimal("50"),
        }
        matrix = _months_matrix(date(2026, 5, 1), date(2026, 8, 1), income_by_month=income)
        baselines, _order, _default = build_baselines(matrix, date(2026, 8, 1))
        self.assertEqual(baselines["1m"]["avgs"]["income"], Decimal("900"))  # July, not an average
        # 3-month average of May, June, July = (100+200+900)/3
        self.assertEqual(baselines["3m"]["avgs"]["income"], Decimal("400"))

    def test_current_month_never_appears_in_its_own_baseline(self):
        income = {
            date(2026, 5, 1): Decimal("100"),
            date(2026, 6, 1): Decimal("100"),
            date(2026, 7, 1): Decimal("100"),
            date(2026, 8, 1): Decimal("999999"),
        }
        matrix = _months_matrix(date(2026, 5, 1), date(2026, 8, 1), income_by_month=income)
        baselines, _order, _default = build_baselines(matrix, date(2026, 8, 1))
        for baseline in baselines.values():
            self.assertNotIn(date(2026, 8, 1).isoformat(), baseline["keys"])
            self.assertNotEqual(baseline["avgs"]["income"], Decimal("999999"))

    def test_full_history_all_four_baselines_present_and_unclamped(self):
        matrix = _months_matrix(date(2024, 1, 1), date(2026, 8, 1))
        baselines, order, default = build_baselines(matrix, date(2026, 8, 1))
        self.assertEqual(order, ["1m", "3m", "6m", "12m"])
        for baseline_id in order:
            self.assertFalse(baselines[baseline_id]["clamped"])
        self.assertEqual(baselines["12m"]["months"], 12)
        self.assertEqual(default, "3m")

    def test_streams_marks_new_payee(self):
        matrix = _months_matrix(date(2026, 5, 1), date(2026, 8, 1))
        matrix.streams = {
            "acme": {
                "label": "Acme Payroll",
                "by_month": {date(2026, 8, 1): Decimal("500")},
            },
            "regular": {
                "label": "Regular Co",
                "by_month": {
                    date(2026, 5, 1): Decimal("100"),
                    date(2026, 6, 1): Decimal("100"),
                    date(2026, 7, 1): Decimal("100"),
                    date(2026, 8, 1): Decimal("100"),
                },
            },
        }
        baselines, _order, _default = build_baselines(matrix, date(2026, 8, 1))
        rows = {r["payee"]: r for r in baselines["3m"]["streams"]}
        self.assertTrue(rows["Acme Payroll"]["new"])
        self.assertFalse(rows["Regular Co"]["new"])
        self.assertEqual(rows["Regular Co"]["avg"], Decimal("100"))
        self.assertEqual(rows["Regular Co"]["vs_avg"], Decimal("0"))

    def test_goal_rows_carry_prev_regardless_of_baseline(self):
        matrix = _months_matrix(date(2026, 5, 1), date(2026, 8, 1))
        matrix.goals = {
            1: {
                "goal": "Emergency Fund",
                "by_month": {
                    date(2026, 7, 1): Decimal("50"),
                    date(2026, 8, 1): Decimal("75"),
                },
            }
        }
        baselines, _order, _default = build_baselines(matrix, date(2026, 8, 1))
        for baseline_id in baselines:
            row = baselines[baseline_id]["saving_rows"][0]
            self.assertEqual(row["amount"], Decimal("75"))
            self.assertEqual(row["prev"], Decimal("50"))
