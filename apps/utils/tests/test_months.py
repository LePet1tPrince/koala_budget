from datetime import date

from django.test import SimpleTestCase

from apps.utils.months import add_months, months_between


class AddMonthsTest(SimpleTestCase):
    def test_forward_back_and_across_years(self):
        cases = [
            (date(2026, 1, 1), 1, date(2026, 2, 1)),
            (date(2026, 12, 1), 1, date(2027, 1, 1)),
            (date(2026, 1, 1), -1, date(2025, 12, 1)),
            (date(2026, 3, 1), -15, date(2024, 12, 1)),
            (date(2026, 3, 1), 0, date(2026, 3, 1)),
            (date(2026, 3, 1), 25, date(2028, 4, 1)),
        ]
        for day, n, expected in cases:
            with self.subTest(day=day, n=n):
                self.assertEqual(add_months(day, n), expected)

    def test_a_mid_month_date_lands_on_the_first(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 1))
        self.assertEqual(add_months(date(2026, 5, 17), 0), date(2026, 5, 1))


class MonthsBetweenTest(SimpleTestCase):
    def test_counts_whole_months_regardless_of_day(self):
        self.assertEqual(months_between(date(2026, 1, 31), date(2026, 1, 1)), 0)
        self.assertEqual(months_between(date(2025, 11, 15), date(2026, 2, 1)), 3)
        self.assertEqual(months_between(date(2026, 2, 1), date(2025, 11, 30)), -3)
