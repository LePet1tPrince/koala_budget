from datetime import date

from django.test import SimpleTestCase

from apps.utils.months import add_months, format_month, months_between, parse_month


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


class ParseMonthTest(SimpleTestCase):
    def test_a_month_is_its_first_day(self):
        self.assertEqual(parse_month("2026-03"), date(2026, 3, 1))
        self.assertEqual(parse_month("1999-12"), date(1999, 12, 1))

    def test_anything_but_yyyy_mm_is_none(self):
        for value in (None, "", "2026-3", "2026-03-01", "2026-13", "2026-00", "0000-01", "26-03", "2026-03\n", "x"):
            with self.subTest(value=value):
                self.assertIsNone(parse_month(value))

    def test_format_is_the_inverse(self):
        self.assertEqual(format_month(date(2026, 3, 17)), "2026-03")
        self.assertEqual(parse_month(format_month(date(2026, 11, 1))), date(2026, 11, 1))
