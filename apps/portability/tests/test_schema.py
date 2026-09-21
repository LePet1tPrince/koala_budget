"""
Schema completeness and cell-codec correctness (§2.6, §7 Phase 1).

The completeness test is the one this whole module exists to make possible:
it walks the *actual* fields Django knows about on every exported model and
fails if one belongs to neither a `FieldMap.columns` mapping nor a
`FieldMap.omitted` reason. It is the mechanical version of the check that,
done by hand while this module was being written, caught `goal_archived_at`
and `BankTransaction.amount` missing from the plan's own column tables (see
`docs/export-import-plan.md` §8) -- so it is written to fail loudly and name
exactly what is missing, the way that check should have from the start.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from django.test import SimpleTestCase

from apps.portability.services import schema


class SchemaCompletenessTests(SimpleTestCase):
    def test_every_concrete_field_is_mapped_or_omitted(self):
        for field_map in schema.FIELD_MAPS:
            with self.subTest(model=field_map.model.__name__):
                model_fields = {f.name for f in field_map.model._meta.get_fields() if getattr(f, "concrete", False)}
                declared = set(field_map.columns) | set(field_map.omitted)

                missing = model_fields - declared
                self.assertFalse(
                    missing,
                    f"{field_map.model.__name__} has concrete field(s) {sorted(missing)} that are neither "
                    "mapped to a column nor listed in `omitted`. Either map them or omit them with a reason.",
                )

                extra = declared - model_fields
                self.assertFalse(
                    extra,
                    f"{field_map.model.__name__}'s FieldMap names {sorted(extra)}, which are not concrete "
                    "fields on the model (stale entry after a rename?).",
                )

    def test_omissions_all_have_a_non_empty_reason(self):
        for field_map in schema.FIELD_MAPS:
            for field_name, reason in field_map.omitted.items():
                with self.subTest(model=field_map.model.__name__, field=field_name):
                    self.assertTrue(
                        reason and reason.strip(),
                        "an omission with no reason is indistinguishable from one that was never reviewed",
                    )

    def test_file_columns_are_produced_by_some_field_map_or_declared_synthetic(self):
        # This is exactly what `validate_schema()` checks at app startup
        # (`PortabilityConfig.ready()`); asserted again here so a broken
        # schema fails a test, not just an import.
        schema.validate_schema()

    def test_no_duplicate_columns_within_a_file(self):
        for filename, columns in schema.FILE_COLUMNS.items():
            names = [c.name for c in columns]
            with self.subTest(file=filename):
                self.assertEqual(len(names), len(set(names)), f"{filename} has a duplicate column name")


class CellCodecTests(SimpleTestCase):
    """encode_cell/decode_cell round trip for every kind, including the blank case."""

    def _round_trip(self, kind, value):
        cell = schema.encode_cell(kind, value)
        return schema.decode_cell(kind, cell, file="t.csv", row_number=2, column="c")

    def test_str_blank_decodes_to_empty_string_not_none(self):
        self.assertEqual(self._round_trip(schema.KIND_STR, None), "")
        self.assertEqual(self._round_trip(schema.KIND_STR, ""), "")
        self.assertEqual(self._round_trip(schema.KIND_STR, "hello"), "hello")

    def test_str_or_none_blank_decodes_to_none(self):
        self.assertIsNone(self._round_trip(schema.KIND_STR_OR_NONE, None))
        self.assertEqual(self._round_trip(schema.KIND_STR_OR_NONE, "Tangerine"), "Tangerine")

    def test_int_round_trips_and_blank_is_none(self):
        self.assertEqual(self._round_trip(schema.KIND_INT, 42), 42)
        self.assertEqual(self._round_trip(schema.KIND_INT, 0), 0)
        self.assertIsNone(self._round_trip(schema.KIND_INT, None))

    def test_decimal_round_trips_and_is_quantized_to_two_places(self):
        self.assertEqual(self._round_trip(schema.KIND_DECIMAL, Decimal("84.1")), Decimal("84.10"))
        self.assertEqual(self._round_trip(schema.KIND_DECIMAL, Decimal("-100")), Decimal("-100.00"))
        self.assertIsNone(self._round_trip(schema.KIND_DECIMAL, None))

    def test_decimal_two_places_never_loses_a_cent_the_way_a_float_would(self):
        # The reason this format is CSV-of-strings rather than a float
        # anywhere in the pipeline (§3.5).
        total = Decimal("0.10") + Decimal("0.20")
        self.assertEqual(self._round_trip(schema.KIND_DECIMAL, total), Decimal("0.30"))

    def test_date_round_trips_and_blank_is_none(self):
        self.assertEqual(self._round_trip(schema.KIND_DATE, date(2026, 7, 4)), date(2026, 7, 4))
        self.assertIsNone(self._round_trip(schema.KIND_DATE, None))

    def test_date_rejects_garbage(self):
        with self.assertRaises(schema.DocumentError):
            schema.decode_cell(schema.KIND_DATE, "04-07-2026", file="t.csv", row_number=2, column="c")

    def test_datetime_round_trips_as_utc_and_blank_is_none(self):
        original = datetime(2026, 7, 4, 12, 30, tzinfo=UTC)
        self.assertEqual(self._round_trip(schema.KIND_DATETIME, original), original)
        self.assertIsNone(self._round_trip(schema.KIND_DATETIME, None))

    def test_bool_round_trips_as_lowercase_true_false(self):
        self.assertEqual(schema.encode_cell(schema.KIND_BOOL, True), "true")
        self.assertEqual(schema.encode_cell(schema.KIND_BOOL, False), "false")
        self.assertIs(self._round_trip(schema.KIND_BOOL, True), True)
        self.assertIs(self._round_trip(schema.KIND_BOOL, False), False)
        self.assertIsNone(self._round_trip(schema.KIND_BOOL, None))

    def test_bool_rejects_anything_other_than_true_or_false(self):
        with self.assertRaises(schema.DocumentError):
            schema.decode_cell(schema.KIND_BOOL, "1", file="t.csv", row_number=2, column="c")
        with self.assertRaises(schema.DocumentError):
            schema.decode_cell(schema.KIND_BOOL, "yes", file="t.csv", row_number=2, column="c")

    def test_decode_error_names_file_row_and_column(self):
        with self.assertRaises(schema.DocumentError) as ctx:
            schema.decode_cell(schema.KIND_INT, "not-a-number", file="accounts.csv", row_number=7, column="account_id")
        message = str(ctx.exception)
        self.assertIn("accounts.csv", message)
        self.assertIn("7", message)
        self.assertIn("account_id", message)
