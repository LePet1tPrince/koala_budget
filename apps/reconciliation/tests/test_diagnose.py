from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.reconciliation.services.diagnose import MAX_HINTS, Row, diagnose

D = Decimal
AUG31 = date(2026, 8, 31)


def row(id, amount, ticked=True, on=date(2026, 8, 15), label="Tx"):
    return Row(id=id, date=on, amount=D(amount), ticked=ticked, label=label)


def kinds(hints):
    return [h.kind for h in hints]


class DiagnoseTests(SimpleTestCase):
    def test_zero_difference_has_no_hints(self):
        self.assertEqual(diagnose([row(1, "-5")], D("0"), AUG31), [])

    def test_missing_tick(self):
        hints = diagnose([row(1, "-12.75", ticked=False)], D("-12.75"), AUG31)
        self.assertEqual(kinds(hints), ["missing_tick"])
        self.assertEqual((hints[0].line_ids, hints[0].action), ([1], "tick"))

    def test_extra_tick(self):
        hints = diagnose([row(1, "-12.75")], D("12.75"), AUG31)
        self.assertIn("extra_tick", kinds(hints))
        self.assertEqual(hints[0].action, "untick")

    def test_duplicate(self):
        rows = [row(1, "-12.75", on=date(2026, 8, 30)), row(2, "-12.75", on=date(2026, 8, 30))]
        hints = diagnose(rows, D("12.75"), AUG31)
        self.assertEqual(kinds(hints), ["duplicate"])  # one hint, not an "untick?" per copy
        self.assertEqual(hints[0].line_ids, [1, 2])
        self.assertEqual(hints[0].as_dict()["action_ids"], [2])

    def test_duplicate_needs_close_dates(self):
        rows = [row(1, "-12.75", on=date(2026, 8, 1)), row(2, "-12.75", on=date(2026, 8, 30))]
        self.assertNotIn("duplicate", kinds(diagnose(rows, D("12.75"), AUG31)))

    def test_wrong_sign(self):
        # A $20 refund entered as a $20 purchase: flipping it moves the total by +40.
        hints = diagnose([row(1, "-20.00")], D("40.00"), AUG31)
        self.assertIn("wrong_sign", kinds(hints))

    def test_transposed_digits(self):
        # Koala has -45.10 where the bank has -54.10: difference -9.00.
        hints = diagnose([row(1, "-45.10")], D("-9.00"), AUG31)
        self.assertIn("transposed", kinds(hints))
        self.assertIn("$54.10", next(h for h in hints if h.kind == "transposed").message)

    def test_after_statement_date(self):
        rows = [row(1, "-5.00", on=date(2026, 9, 2)), row(2, "-7.00", on=date(2026, 9, 3))]
        hints = diagnose(rows, D("12.00"), AUG31)
        after = next(h for h in hints if h.kind == "after_statement")
        self.assertEqual(after.line_ids, [1, 2])

    def test_uncategorized_single_and_total(self):
        single = diagnose([], D("-30.00"), AUG31, [row(9, "-30.00", ticked=False)])
        self.assertEqual(kinds(single), ["uncategorized"])
        total = diagnose([], D("-30.00"), AUG31, [row(8, "-10.00", ticked=False), row(9, "-20.00", ticked=False)])
        self.assertEqual(kinds(total), ["uncategorized"])

    def test_capped(self):
        rows = [row(i, "-1.00", ticked=False) for i in range(20)]
        self.assertEqual(len(diagnose(rows, D("-1.00"), AUG31)), MAX_HINTS)
