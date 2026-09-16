"""
Tests for BankFeedViewSet.upload_validate_dates endpoint and the
validate_date_column service that backs it.
"""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.bank_feed.services.csv_upload import validate_date_column
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class ValidateDateColumnServiceTest(TestCase):
    """Tests for the validate_date_column service function."""

    def _csv(self, content: str) -> BytesIO:
        return BytesIO(content.encode())

    def test_all_dates_valid_reports_no_errors(self):
        content = "Date,Description,Amount\n2025-01-01,A,1.00\n2025-01-02,B,2.00"
        result = validate_date_column(self._csv(content), "test.csv", 0, "%Y-%m-%d")

        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.invalid_count, 0)
        self.assertEqual(result.invalid_samples, [])
        self.assertIsNone(result.suggested_format)

    def test_wrong_format_flags_every_row_and_suggests_the_right_one(self):
        # Day-first dates checked against a month-first format.
        content = "Date,Description,Amount\n28/02/2025,A,1.00\n15/03/2025,B,2.00"
        result = validate_date_column(self._csv(content), "test.csv", 0, "%m/%d/%Y")

        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.invalid_count, 2)
        self.assertEqual(result.invalid_samples[0].row_number, 2)
        self.assertEqual(result.invalid_samples[0].value, "28/02/2025")
        self.assertEqual(result.suggested_format, "%d/%m/%Y")

    def test_partially_invalid_dates_are_counted(self):
        # 02/28 parses as MM/DD, 28/02 does not.
        content = "Date,Description,Amount\n02/28/2025,A,1.00\n28/02/2025,B,2.00"
        result = validate_date_column(self._csv(content), "test.csv", 0, "%m/%d/%Y")

        self.assertEqual(result.invalid_count, 1)
        self.assertEqual(result.invalid_samples[0].row_number, 3)

    def test_no_format_fits_yields_no_suggestion(self):
        content = "Date,Description,Amount\nnot a date,A,1.00\nalso not,B,2.00"
        result = validate_date_column(self._csv(content), "test.csv", 0, "%Y-%m-%d")

        self.assertEqual(result.invalid_count, 2)
        self.assertIsNone(result.suggested_format)

    def test_suggestion_survives_a_few_genuinely_broken_rows(self):
        """One junk cell must not suppress an otherwise obviously better format."""
        content = "Date,Description,Amount\n28/02/2025,A,1.00\n15/03/2025,B,2.00\nbanana,C,3.00"
        result = validate_date_column(self._csv(content), "test.csv", 0, "%m/%d/%Y")

        self.assertEqual(result.invalid_count, 3)
        self.assertEqual(result.suggested_format, "%d/%m/%Y")

    def test_no_suggestion_when_nothing_beats_the_chosen_format(self):
        """A format that already parses everything it can gets no alternative offered."""
        content = "Date,Description,Amount\n2025-01-01,A,1.00\nbanana,B,2.00"
        result = validate_date_column(self._csv(content), "test.csv", 0, "%Y-%m-%d")

        self.assertEqual(result.invalid_count, 1)
        self.assertIsNone(result.suggested_format)

    def test_blank_dates_count_as_invalid(self):
        content = "Date,Description,Amount\n,A,1.00\n2025-01-02,B,2.00"
        result = validate_date_column(self._csv(content), "test.csv", 0, "%Y-%m-%d")

        self.assertEqual(result.invalid_count, 1)
        self.assertEqual(result.invalid_samples[0].value, "")
        # A blank cell is not fixable by a format change, so the remaining
        # non-blank value still fits and no alternative is suggested.
        self.assertIsNone(result.suggested_format)

    def test_samples_are_capped(self):
        rows = "\n".join(f"bad-{i},A,1.00" for i in range(20))
        content = f"Date,Description,Amount\n{rows}"
        result = validate_date_column(self._csv(content), "test.csv", 0, "%Y-%m-%d")

        self.assertEqual(result.invalid_count, 20)
        self.assertEqual(len(result.invalid_samples), 5)

    def test_has_headers_false_checks_the_first_row_too(self):
        content = "2025-01-01,A,1.00\n2025-01-02,B,2.00"
        result = validate_date_column(self._csv(content), "test.csv", 0, "%Y-%m-%d", has_headers=False)

        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.invalid_count, 0)

    def test_unsupported_file_type_returns_error(self):
        result = validate_date_column(self._csv("whatever"), "test.pdf", 0, "%Y-%m-%d")

        self.assertIsNotNone(result.error)
        self.assertEqual(result.invalid_count, 0)

    def test_out_of_range_column_counts_as_invalid(self):
        content = "Date,Description\n2025-01-01,A"
        result = validate_date_column(self._csv(content), "test.csv", 9, "%Y-%m-%d")

        self.assertEqual(result.invalid_count, 1)


class BankFeedViewSetUploadValidateDatesTest(TestCase):
    """Tests for the upload_validate_dates endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = f"/a/{self.team.slug}/bankfeed/api/feed/upload_validate_dates/"

    def _csv_file(self, content: str) -> SimpleUploadedFile:
        return SimpleUploadedFile("test.csv", content.encode(), content_type="text/csv")

    def test_returns_invalid_count_and_suggestion(self):
        csv_file = self._csv_file("Date,Description,Amount\n28/02/2025,A,1.00\n15/03/2025,B,2.00")
        response = self.client.post(
            self.url,
            {"file": csv_file, "date_column": 0, "date_format": "%m/%d/%Y", "has_headers": "true"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_rows"], 2)
        self.assertEqual(response.data["invalid_count"], 2)
        self.assertEqual(response.data["suggested_format"], "%d/%m/%Y")
        self.assertEqual(len(response.data["invalid_samples"]), 2)
        self.assertEqual(response.data["invalid_samples"][0]["value"], "28/02/2025")

    def test_valid_format_returns_zero_invalid(self):
        csv_file = self._csv_file("Date,Description,Amount\n2025-01-01,A,1.00")
        response = self.client.post(
            self.url,
            {"file": csv_file, "date_column": 0, "date_format": "%Y-%m-%d"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["invalid_count"], 0)

    def test_missing_file_returns_400(self):
        response = self.client.post(
            self.url,
            {"date_column": 0, "date_format": "%Y-%m-%d"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_date_format_returns_400(self):
        csv_file = self._csv_file("Date,Description\n2025-01-01,A")
        response = self.client.post(
            self.url,
            {"file": csv_file, "date_column": 0},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_date_column_returns_400(self):
        csv_file = self._csv_file("Date,Description\n2025-01-01,A")
        response = self.client.post(
            self.url,
            {"file": csv_file, "date_column": "nope", "date_format": "%Y-%m-%d"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_requires_authentication(self):
        client = APIClient()
        csv_file = self._csv_file("Date,Description\n2025-01-01,A")
        response = client.post(
            self.url,
            {"file": csv_file, "date_column": 0, "date_format": "%Y-%m-%d"},
            format="multipart",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
