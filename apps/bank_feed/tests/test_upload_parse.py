"""
Tests for BankFeedViewSet.upload_parse endpoint.
"""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class BankFeedViewSetUploadParseTest(TestCase):
    """Tests for BankFeedViewSet.upload_parse endpoint."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for all tests."""
        cls.team = Team.objects.create(name="Test Team", slug="test-team")
        cls.user = CustomUser.objects.create_user(username="testuser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        """Set up for each test."""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _create_csv_file(self, content: str) -> SimpleUploadedFile:
        """Create a SimpleUploadedFile for CSV content."""
        return SimpleUploadedFile("test.csv", content.encode(), content_type="text/csv")

    def _create_xlsx_file(self) -> SimpleUploadedFile:
        """Create a minimal xlsx file for testing."""
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["Date", "Description", "Amount"])
        ws.append(["2025-01-01", "Test transaction", "100.00"])
        ws.append(["2025-01-02", "Another transaction", "-50.00"])

        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return SimpleUploadedFile(
            "test.xlsx",
            buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_upload_parse_csv_returns_headers_and_sample(self):
        """Test that CSV upload returns headers and sample rows."""
        csv_content = "Date,Description,Amount\n2025-01-01,Test,100.00\n2025-01-02,Test2,50.00"
        csv_file = self._create_csv_file(csv_content)

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_parse/",
                {"file": csv_file},
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["headers"], ["Date", "Description", "Amount"])
            self.assertEqual(len(response.data["sample_rows"]), 2)
            self.assertEqual(response.data["total_rows"], 2)
            self.assertIsNone(response.data["error"])

    def test_upload_parse_xlsx_returns_headers_and_sample(self):
        """Test that Excel upload returns headers and sample rows."""
        xlsx_file = self._create_xlsx_file()

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_parse/",
                {"file": xlsx_file},
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["headers"], ["Date", "Description", "Amount"])
            self.assertEqual(response.data["total_rows"], 2)
            self.assertIsNone(response.data["error"])

    def test_upload_parse_no_file_returns_400(self):
        """Test that missing file returns 400."""
        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_parse/",
                {},
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("error", response.data)

    def test_upload_parse_empty_file_returns_error(self):
        """Test that empty file returns error in response."""
        csv_file = self._create_csv_file("")

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_parse/",
                {"file": csv_file},
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIsNotNone(response.data["error"])

    def test_upload_parse_unsupported_type_returns_error(self):
        """Test that unsupported file type returns error."""
        txt_file = SimpleUploadedFile("test.txt", b"Some text content", content_type="text/plain")

        with current_team(self.team):
            response = self.client.post(
                f"/a/{self.team.slug}/bankfeed/api/feed/upload_parse/",
                {"file": txt_file},
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIsNotNone(response.data["error"])
            self.assertIn("Unsupported", response.data["error"])
