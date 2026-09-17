"""
Tests for the downloadable sample bank statement.

The sample file is only useful if it survives the real import pipeline, so these
tests push it through the same parse/preview path a user's own file takes rather
than asserting on the text alone.
"""

from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Sum
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.csv_upload import create_transactions, parse_file, preview_transactions
from apps.bank_feed.services.sample_csv import CSV_HEADERS, build_sample_csv, sample_rows
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class SampleCsvContentTest(TestCase):
    def test_rows_are_within_the_expected_window(self):
        today = date(2026, 9, 17)
        rows = sample_rows(today)

        self.assertTrue(rows)
        earliest = min(row[0] for row in rows)
        latest = max(row[0] for row in rows)

        # Three complete months back, plus the current month to date.
        self.assertEqual(earliest.year, 2026)
        self.assertEqual(earliest.month, 6)
        self.assertLessEqual(latest, today)
        self.assertEqual(latest.month, 9)

    def test_no_row_is_dated_in_the_future(self):
        """The current month has not finished happening yet."""
        today = date(2026, 9, 3)
        self.assertTrue(all(row[0] <= today for row in sample_rows(today)))

    def test_is_deterministic(self):
        today = date(2026, 9, 17)
        self.assertEqual(build_sample_csv(today), build_sample_csv(today))

    def test_net_is_positive(self):
        """The payoff of the walkthrough is a rising net worth, so the sample must climb."""
        rows = sample_rows(date(2026, 9, 30))
        net = sum((row[2] - row[3] for row in rows), Decimal("0"))
        self.assertGreater(net, Decimal("0"))

    def test_handles_a_short_month(self):
        """Pattern days past the end of the month are pulled back, not dropped or crashed."""
        rows = sample_rows(date(2026, 3, 31))
        february = [row[0] for row in rows if row[0].month == 2]
        self.assertTrue(february)
        self.assertLessEqual(max(february).day, 28)

    def test_each_row_has_exactly_one_side(self):
        for posted, description, inflow, outflow in sample_rows(date(2026, 9, 17)):
            with self.subTest(row=f"{posted} {description}"):
                self.assertNotEqual(bool(inflow), bool(outflow))


class SampleCsvImportTest(TestCase):
    """The generated file must go through the ordinary upload pipeline cleanly."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Sample Team", slug="sample-team")
        group = AccountGroup.objects.create(team=cls.team, name="Bank Accounts", account_type="asset")
        cls.account = Account.objects.create(team=cls.team, name="Chequing Account", account_group=group, has_feed=True)

    def _preview(self, today=None):
        upload = SimpleUploadedFile("sample.csv", build_sample_csv(today).encode(), content_type="text/csv")
        return preview_transactions(
            file=upload,
            filename="sample.csv",
            column_mapping={"date": 0, "description": 1, "inflow": 2, "outflow": 3, "has_headers": True},
            category_mappings={},
            team=self.team,
            account_id=self.account.id,
            date_format="%Y-%m-%d",
        )

    def test_headers_are_auto_mappable(self):
        upload = SimpleUploadedFile("sample.csv", build_sample_csv().encode(), content_type="text/csv")
        result = parse_file(upload, "sample.csv")

        self.assertIsNone(result.error)
        self.assertEqual(result.headers, CSV_HEADERS)

    def test_every_row_parses(self):
        """No row may land in the preview with an error badge."""
        today = date(2026, 9, 17)
        result = self._preview(today)

        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.transactions), len(sample_rows(today)))
        self.assertEqual([t for t in result.transactions if t.error], [])

    def test_inflows_become_negative_amounts(self):
        """Plaid convention: money in is negative. A paycheque must not read as spending."""
        transactions = self._preview().transactions

        payroll = [t for t in transactions if "PAYROLL" in (t.description or "")]
        rent = [t for t in transactions if "RENT" in (t.description or "")]

        self.assertTrue(payroll)
        self.assertTrue(rent)
        self.assertTrue(all(t.amount < 0 for t in payroll))
        self.assertTrue(all(t.amount > 0 for t in rent))


class SampleCsvEndpointTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Endpoint Team", slug="endpoint-team")
        cls.user = CustomUser.objects.create_user(username="member", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        cls.other_team = Team.objects.create(name="Other Team", slug="other-team")
        cls.outsider = CustomUser.objects.create_user(username="outsider", password="pass")
        cls.other_team.members.add(cls.outsider, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.client = APIClient()
        self.url = f"/a/{self.team.slug}/bankfeed/api/feed/sample_csv/"

    def test_downloads_as_an_attachment(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("koala-sample-statement.csv", response["Content-Disposition"])
        self.assertIn("Funds In", response.content.decode())

    def test_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_non_member_is_refused(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))


class SampleCsvEndToEndTest(TestCase):
    """
    The walkthrough promises the user will watch their net worth climb. That only
    holds if the sample file, imported and categorized the ordinary way, actually
    leaves the account better off than it started.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="E2E Team", slug="e2e-team")
        assets = AccountGroup.objects.create(team=cls.team, name="Bank Accounts", account_type="asset")
        cls.account = Account.objects.create(
            team=cls.team, name="Chequing Account", account_group=assets, has_feed=True
        )

    def test_import_creates_every_row_and_nets_positive(self):
        today = date(2026, 9, 17)
        upload = SimpleUploadedFile("sample.csv", build_sample_csv(today).encode(), content_type="text/csv")

        preview = preview_transactions(
            file=upload,
            filename="sample.csv",
            column_mapping={"date": 0, "description": 1, "inflow": 2, "outflow": 3, "has_headers": True},
            category_mappings={},
            team=self.team,
            account_id=self.account.id,
            date_format="%Y-%m-%d",
        )

        result = create_transactions(
            transactions=[
                {
                    "date": t.date.isoformat(),
                    "description": t.description,
                    "payee": t.payee,
                    "category_id": t.matched_category_id,
                    "amount": str(t.amount),
                }
                for t in preview.transactions
            ],
            team=self.team,
            account_id=self.account.id,
            skip_duplicates=False,
        )

        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["created_count"], len(sample_rows(today)))

        # Plaid convention: positive = money out. A negative total means the
        # account took in more than it spent, which is what makes net worth rise.
        net = BankTransaction.objects.filter(team=self.team).aggregate(total=Sum("amount"))["total"]
        self.assertLess(net, Decimal("0"))

    def test_rows_land_uncategorized(self):
        """Categorizing is the next step of the walkthrough -- the import must not pre-empt it."""
        upload = SimpleUploadedFile("sample.csv", build_sample_csv().encode(), content_type="text/csv")

        preview = preview_transactions(
            file=upload,
            filename="sample.csv",
            column_mapping={"date": 0, "description": 1, "inflow": 2, "outflow": 3, "has_headers": True},
            category_mappings={},
            team=self.team,
            account_id=self.account.id,
            date_format="%Y-%m-%d",
        )

        self.assertEqual(preview.unmapped_categories, [])
        self.assertTrue(all(t.matched_category_id is None for t in preview.transactions))
