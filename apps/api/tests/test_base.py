from datetime import date

from django.test import SimpleTestCase
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.api.base import MonthField, month_query_param, parse_month_param


def drf_request(query=""):
    return Request(APIRequestFactory().get(f"/x/{query}"))


class MonthParamTest(SimpleTestCase):
    def test_parses_yyyy_mm(self):
        self.assertEqual(parse_month_param("2026-03"), date(2026, 3, 1))

    def test_a_bad_month_is_a_validation_error_on_the_field(self):
        for value in ("2026-03-01", "2026-13", "", None, 202603):
            with self.subTest(value=value), self.assertRaises(ValidationError) as caught:
                parse_month_param(value, field="start")
            self.assertIn("start", caught.exception.detail)

    def test_query_param(self):
        self.assertEqual(month_query_param(drf_request("?month=2026-03")), date(2026, 3, 1))
        self.assertEqual(month_query_param(drf_request("?from=2025-12"), "from"), date(2025, 12, 1))

    def test_query_param_default(self):
        self.assertEqual(month_query_param(drf_request(), default=date(2026, 1, 1)), date(2026, 1, 1))
        self.assertEqual(month_query_param(drf_request(), default=lambda: date(2026, 2, 1)), date(2026, 2, 1))
        with self.assertRaises(ValidationError) as caught:
            month_query_param(drf_request())
        self.assertIn("month", caught.exception.detail)

    def test_a_malformed_month_never_falls_back_to_the_default(self):
        with self.assertRaises(ValidationError):
            month_query_param(drf_request("?month=March"), default=date(2026, 1, 1))


class MonthFieldTest(SimpleTestCase):
    class PeriodSerializer(serializers.Serializer):
        month = MonthField()

    def test_round_trip(self):
        serializer = self.PeriodSerializer(data={"month": "2026-03"})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["month"], date(2026, 3, 1))
        self.assertEqual(self.PeriodSerializer({"month": date(2026, 3, 17)}).data, {"month": "2026-03"})

    def test_invalid(self):
        serializer = self.PeriodSerializer(data={"month": "2026-03-01"})
        self.assertFalse(serializer.is_valid())
        self.assertEqual(serializer.errors["month"], ["Enter a month as YYYY-MM."])
