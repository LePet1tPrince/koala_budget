"""
Reading the two exports.

The assertions are about the shapes that later passes depend on -- a transfer that
names its counterpart, a split that knows which leg it is, an amount with the
currency symbol on the wrong side -- rather than about the CSV module.
"""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.ynab_import.services.parse import (
    ParseError,
    detect_date_format,
    identify,
    parse_plan,
    parse_register,
)

from .fixtures import TINY_PLAN, TINY_REGISTER, sample_plan_bytes, sample_register_bytes


class ParseRegisterTest(SimpleTestCase):
    def test_reads_the_sample_export(self):
        rows = parse_register(sample_register_bytes())
        self.assertEqual(len(rows), 7572)
        self.assertEqual(rows[0].entry_date, date(2026, 9, 30))

    def test_amount_with_a_trailing_currency_symbol(self):
        rows = parse_register(TINY_REGISTER.encode())
        self.assertEqual(rows[2].net, Decimal("2000.00"))
        self.assertEqual(rows[3].net, Decimal("-80.00"))

    def test_thousands_separator(self):
        register = TINY_REGISTER.replace("2000.00$", '"157,118.75$"')
        self.assertEqual(parse_register(register.encode())[2].net, Decimal("157118.75"))

    def test_transfer_names_its_counterpart(self):
        rows = parse_register(TINY_REGISTER.encode())
        self.assertEqual(rows[6].transfer_account, "Savings")
        self.assertIsNone(rows[3].transfer_account)

    def test_split_legs_know_their_position(self):
        rows = parse_register(TINY_REGISTER.encode())
        self.assertEqual(rows[4].split, (1, 2))
        self.assertEqual(rows[5].split, (2, 2))
        # The `Split (i/n)` prefix is structure, not a note the user wrote.
        self.assertEqual(rows[4].clean_memo, "")

    def test_cleared_states(self):
        rows = parse_register(TINY_REGISTER.encode())
        self.assertTrue(rows[3].is_reconciled)
        self.assertTrue(rows[3].is_cleared)
        # Cleared but not reconciled, and the reverse is never true.
        self.assertFalse(rows[4].is_reconciled)
        self.assertTrue(rows[4].is_cleared)
        self.assertFalse(rows[8].is_cleared)

    def test_rejects_a_file_that_is_not_a_register(self):
        with self.assertRaises(ParseError):
            parse_register(TINY_PLAN.encode())


class ParsePlanTest(SimpleTestCase):
    def test_reads_the_sample_export(self):
        rows = parse_plan(sample_plan_bytes())
        self.assertEqual(len(rows), 2958)
        self.assertEqual(len({row.month for row in rows}), 58)

    def test_month_and_columns(self):
        rows = parse_plan(TINY_PLAN.encode())
        self.assertEqual(rows[1].month, date(2024, 1, 1))
        self.assertEqual(rows[1].assigned, Decimal("100.00"))
        self.assertEqual(rows[1].activity, Decimal("-86.00"))
        self.assertEqual(rows[1].available, Decimal("14.00"))


class IdentifyTest(SimpleTestCase):
    def test_either_order(self):
        register, plan = TINY_REGISTER.encode(), TINY_PLAN.encode()
        self.assertEqual(identify([("a.csv", plan), ("b.csv", register)]), (register, plan))
        self.assertEqual(identify([("a.csv", register), ("b.csv", plan)]), (register, plan))

    def test_says_which_file_is_missing(self):
        with self.assertRaisesMessage(ParseError, "No plan file"):
            identify([("a.csv", TINY_REGISTER.encode())])
        with self.assertRaisesMessage(ParseError, "No register file"):
            identify([("a.csv", TINY_PLAN.encode())])


class DateFormatTest(SimpleTestCase):
    def test_day_first_when_the_data_proves_it(self):
        self.assertEqual(detect_date_format(["25-01-2024", "01-02-2024"]), "%d-%m-%Y")

    def test_month_first_when_the_data_proves_it(self):
        self.assertEqual(detect_date_format(["01/25/2024", "02/01/2024"]), "%m/%d/%Y")

    def test_ambiguous_dates_fall_back_to_day_first(self):
        # Every YNAB export outside the US is day-first, and nothing in a file of
        # ambiguous dates can settle it.
        self.assertEqual(detect_date_format(["01-02-2024", "03-04-2024"]), "%d-%m-%Y")

    def test_unreadable_dates(self):
        with self.assertRaises(ParseError):
            detect_date_format(["last Tuesday"])
