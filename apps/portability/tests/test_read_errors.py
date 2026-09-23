"""
Every way a file can fail to import, and what should happen instead (§6, §7
Phase 1). Each test starts from a known-good archive (the fixture tables) and
damages exactly one thing, so a failure here points at one specific check.
"""

import copy
import io
import json
import zipfile
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.portability.services import read, write
from apps.portability.services.schema import FORMAT_VERSION, DocumentError
from apps.portability.tests.fixtures import build_fixture_tables


def _archive(accounts=None, journal=None, budget=None):
    fixture_accounts, fixture_journal, fixture_budget = build_fixture_tables()
    return write.build_archive_bytes(
        accounts=accounts if accounts is not None else fixture_accounts,
        journal=journal if journal is not None else fixture_journal,
        budget=budget if budget is not None else fixture_budget,
        source={},
        checks={},
        omitted={},
    )


def _rezip_with_manifest(data: bytes, manifest: dict) -> bytes:
    zf_in = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf_out:
        zf_out.writestr("manifest.json", json.dumps(manifest))
        for name in ("accounts.csv", "journal.csv", "budget.csv"):
            zf_out.writestr(name, zf_in.read(name))
    return buf.getvalue()


class StructuralErrorTests(SimpleTestCase):
    def test_not_a_zip_file_is_refused(self):
        with self.assertRaises(DocumentError):
            read.read_archive(b"this is not a zip file")

    def test_zip_without_manifest_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("accounts.csv", "account_id,name\r\n")
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(buf.getvalue())
        self.assertIn("manifest.json", str(ctx.exception))

    def test_wrong_format_name_is_refused(self):
        data = _archive()
        zf_in = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf_in.read("manifest.json"))
        manifest["format"] = "some-other-app-export"
        with self.assertRaises(DocumentError):
            read.read_archive(_rezip_with_manifest(data, manifest))

    def test_missing_data_file_is_refused(self):
        data = _archive()
        zf_in = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf_in.read("manifest.json"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf_out:
            zf_out.writestr("manifest.json", json.dumps(manifest))
            zf_out.writestr("accounts.csv", zf_in.read("accounts.csv"))
            zf_out.writestr("budget.csv", zf_in.read("budget.csv"))
            # journal.csv omitted
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(buf.getvalue())
        self.assertIn("journal.csv", str(ctx.exception))

    def test_missing_required_column_is_refused(self):
        # Rewrite accounts.csv without its account_id column.
        data = _archive()
        zf_in = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf_in.read("manifest.json"))
        lines = zf_in.read("accounts.csv").decode("utf-8-sig").splitlines()
        header = lines[0].split(",")
        header.remove("account_id")
        broken = "\r\n".join([",".join(header)] + lines[1:]) + "\r\n"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf_out:
            zf_out.writestr("manifest.json", json.dumps(manifest))
            zf_out.writestr("accounts.csv", broken.encode("utf-8-sig"))
            zf_out.writestr("journal.csv", zf_in.read("journal.csv"))
            zf_out.writestr("budget.csv", zf_in.read("budget.csv"))

        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(buf.getvalue())
        self.assertIn("account_id", str(ctx.exception))


class VersionTests(SimpleTestCase):
    def test_newer_format_version_is_refused_with_an_upgrade_message(self):
        data = _archive()
        zf_in = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf_in.read("manifest.json"))
        manifest["format_version"] = FORMAT_VERSION + 1
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_rezip_with_manifest(data, manifest))
        self.assertIn("newer version", str(ctx.exception).lower())

    def test_older_format_version_is_refused_since_the_chain_is_empty(self):
        data = _archive()
        zf_in = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf_in.read("manifest.json"))
        manifest["format_version"] = 0
        with self.assertRaises(DocumentError):
            read.read_archive(_rezip_with_manifest(data, manifest))

    def test_current_format_version_is_accepted(self):
        # Not a regression test so much as a sanity check that the two above
        # aren't vacuously true because every version gets refused.
        tables = read.read_archive(_archive())
        self.assertEqual(tables.manifest.format_version, FORMAT_VERSION)


class BusinessRuleTests(SimpleTestCase):
    def test_unbalanced_entry_is_refused(self):
        accounts, journal, budget = build_fixture_tables()
        journal = copy.deepcopy(journal)
        journal[0]["dr_amount"] = Decimal("999.00")
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(accounts, journal, budget))
        self.assertIn("does not balance", str(ctx.exception))

    def test_dangling_account_reference_in_journal_is_refused(self):
        accounts, journal, budget = build_fixture_tables()
        journal = copy.deepcopy(journal)
        journal[0]["account_id"] = 9999
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(accounts, journal, budget))
        self.assertIn("9999", str(ctx.exception))
        self.assertIn("accounts.csv", str(ctx.exception))

    def test_dangling_account_reference_in_budget_is_refused(self):
        accounts, journal, budget = build_fixture_tables()
        budget = copy.deepcopy(budget)
        budget[0]["account_id"] = 9999
        with self.assertRaises(DocumentError):
            read.read_archive(_archive(accounts, journal, budget))

    def test_inconsistent_repeated_entry_columns_are_refused(self):
        accounts, journal, budget = build_fixture_tables()
        journal = copy.deepcopy(journal)
        # entry_id 100's two lines currently agree on entry_date; break that.
        for row in journal:
            if row["entry_id"] == 100 and row["account_id"] == 1:
                row["entry_date"] = date(2099, 1, 1)
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(accounts, journal, budget))
        self.assertIn("entry_id 100", str(ctx.exception))

    def test_non_first_of_month_is_refused(self):
        accounts, journal, budget = build_fixture_tables()
        budget = copy.deepcopy(budget)
        budget[0]["month"] = date(2026, 1, 15)
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(accounts, journal, budget))
        self.assertIn("first of the month", str(ctx.exception))

    def test_unknown_account_type_is_refused(self):
        accounts, journal, budget = build_fixture_tables()
        accounts = copy.deepcopy(accounts)
        accounts[0]["account_type"] = "cryptocurrency"
        with self.assertRaises(DocumentError):
            read.read_archive(_archive(accounts, journal, budget))

    def test_unknown_status_is_refused(self):
        accounts, journal, budget = build_fixture_tables()
        journal = copy.deepcopy(journal)
        journal[0]["status"] = "pending-review"
        with self.assertRaises(DocumentError):
            read.read_archive(_archive(accounts, journal, budget))

    def test_unknown_kind_in_budget_csv_is_refused(self):
        accounts, journal, budget = build_fixture_tables()
        budget = copy.deepcopy(budget)
        budget[0]["kind"] = "savings"
        with self.assertRaises(DocumentError):
            read.read_archive(_archive(accounts, journal, budget))

    def test_missing_account_id_on_a_journal_row_is_refused_not_silently_none(self):
        accounts, journal, budget = build_fixture_tables()
        journal = copy.deepcopy(journal)
        journal[0]["account_id"] = None
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(accounts, journal, budget))
        self.assertIn("account_id is required", str(ctx.exception))

    def test_missing_amount_on_a_real_line_is_refused_not_treated_as_zero(self):
        accounts, journal, budget = build_fixture_tables()
        journal = copy.deepcopy(journal)
        journal[0]["dr_amount"] = None
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(accounts, journal, budget))
        self.assertIn("dr_amount and cr_amount are both required", str(ctx.exception))

    def test_feed_source_without_its_required_companions_is_refused(self):
        accounts, journal, budget = build_fixture_tables()
        journal = copy.deepcopy(journal)
        for row in journal:
            if row["feed_source"]:
                row["feed_amount"] = None
                break
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(accounts, journal, budget))
        self.assertIn("feed_source", str(ctx.exception))


class HashWarningTests(SimpleTestCase):
    def test_edited_file_warns_but_does_not_refuse(self):
        data = _archive()
        zf_in = zipfile.ZipFile(io.BytesIO(data))
        manifest_bytes = zf_in.read("manifest.json")
        edited_accounts_csv = zf_in.read("accounts.csv").replace(b"Chequing", b"Chequing (renamed)")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf_out:
            zf_out.writestr("manifest.json", manifest_bytes)
            zf_out.writestr("accounts.csv", edited_accounts_csv)
            zf_out.writestr("journal.csv", zf_in.read("journal.csv"))
            zf_out.writestr("budget.csv", zf_in.read("budget.csv"))

        tables = read.read_archive(buf.getvalue())  # must not raise
        self.assertEqual(len(tables.hash_warnings), 1)
        self.assertIn("accounts.csv", tables.hash_warnings[0])
        self.assertTrue(any(a["name"] == "Chequing (renamed)" for a in tables.accounts))

    def test_untouched_files_produce_no_warning_even_when_a_sibling_is_edited(self):
        data = _archive()
        zf_in = zipfile.ZipFile(io.BytesIO(data))
        manifest_bytes = zf_in.read("manifest.json")
        edited_accounts_csv = zf_in.read("accounts.csv").replace(b"Chequing", b"Chequing (renamed)")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf_out:
            zf_out.writestr("manifest.json", manifest_bytes)
            zf_out.writestr("accounts.csv", edited_accounts_csv)
            zf_out.writestr("journal.csv", zf_in.read("journal.csv"))
            zf_out.writestr("budget.csv", zf_in.read("budget.csv"))

        tables = read.read_archive(buf.getvalue())
        self.assertEqual(len(tables.hash_warnings), 1)  # only accounts.csv, not journal/budget


class FeedRowCompletenessTests(SimpleTestCase):
    """
    What a `feed_source` obliges the rest of the row to carry -- and what it
    does not.

    `BankTransaction.description` is a plain `CharField`: NOT NULL, but `""`
    is a perfectly ordinary value for it (a CSV column left empty, a Plaid row
    with no description, a transfer mirror copied from a primary that had
    none). The exporter writes that as a blank cell, so requiring the cell to
    be non-blank made the exporter capable of producing an archive its own
    importer refused -- reported from real books, and the reason this class
    exists.
    """

    def _journal_with(self, **feed_overrides):
        _accounts, journal, _budget = build_fixture_tables()
        row = next(r for r in journal if r["feed_source"] is not None)
        row.update(feed_overrides)
        return journal

    def test_a_feed_row_with_a_blank_description_is_accepted(self):
        data = _archive(journal=self._journal_with(feed_description=""))
        tables = read.read_archive(data)  # must not raise
        feed_rows = [r for r in tables.journal_rows if r["feed_source"] is not None]
        self.assertTrue(any(r["feed_description"] == "" for r in feed_rows))

    def test_a_blank_description_round_trips_as_empty_string_not_none(self):
        # `BankTransaction.description` cannot hold None, so decoding a blank
        # cell to None would hand `apply` a value the column rejects.
        data = _archive(journal=self._journal_with(feed_description=""))
        tables = read.read_archive(data)
        row = next(r for r in tables.journal_rows if r["feed_source"] is not None)
        self.assertEqual(row["feed_description"], "")
        self.assertIsNotNone(row["feed_description"])

    def test_a_missing_amount_is_still_refused(self):
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(journal=self._journal_with(feed_amount=None)))
        self.assertIn("feed_amount", str(ctx.exception))

    def test_a_missing_posted_date_is_still_refused(self):
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(journal=self._journal_with(feed_posted_date=None)))
        self.assertIn("feed_posted_date", str(ctx.exception))

    def test_a_missing_archived_flag_is_still_refused(self):
        with self.assertRaises(DocumentError) as ctx:
            read.read_archive(_archive(journal=self._journal_with(feed_is_archived=None)))
        self.assertIn("feed_is_archived", str(ctx.exception))

    def test_a_blank_merchant_name_is_accepted(self):
        # merchant_name IS nullable, so None is the honest value here.
        data = _archive(journal=self._journal_with(feed_merchant=None))
        tables = read.read_archive(data)
        row = next(r for r in tables.journal_rows if r["feed_source"] is not None)
        self.assertIsNone(row["feed_merchant"])
