"""
The one writer for a transaction's journal lines (`apps.journal.services.lines`).

Three things are pinned here: the writer's own behaviour (the home line kept in
place, legs re-pointed or replaced, a new entry's lines created), that every
categorization path reaches its leg-expansion seam, and a scan that fails when a
line is created anywhere outside the writer and its documented allowlist.
"""

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services import categorize
from apps.bank_feed.services.csv_upload import _auto_categorize_transaction
from apps.books.context import current_book
from apps.onboarding.services.opening import OpeningRow, create_opening_balances
from apps.reconciliation.models import Reconciliation
from apps.reconciliation.services.adjustment import create_adjustment, offset_account
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .models import JournalEntry, JournalLine
from .services import lines as writer
from .services.simple_edit import TransactionEdits, apply_edits

D = Decimal


class LinesFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Lines Team", slug="lines-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="liner", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        assets = AccountGroup.objects.create(book=cls.book, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        cards = AccountGroup.objects.create(book=cls.book, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        spend = AccountGroup.objects.create(book=cls.book, name="Spend", account_type=ACCOUNT_TYPE_EXPENSE)
        tax = AccountGroup.objects.create(book=cls.book, name="Tax", account_type=ACCOUNT_TYPE_EQUITY)
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=assets, has_feed=True)
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=assets, has_feed=True)
        cls.card = Account.objects.create(book=cls.book, name="Card", account_group=cards, has_feed=True)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=spend)
        cls.dining = Account.objects.create(book=cls.book, name="Dining", account_group=spend)
        # Stands in for an ITC account: anything that is not the leg's own category.
        cls.itc = Account.objects.create(book=cls.book, name="HST ITC", account_group=tax)
        # The system equity account opening balances and adjustments post against.
        cls.offset = offset_account(cls.book)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def row(self, amount="40.00", account=None, **kwargs):
        return BankTransaction.objects.create(
            book=self.book,
            account=account or self.checking,
            amount=D(amount),
            posted_date=date(2026, 6, 1),
            description=kwargs.pop("description", "Row"),
            source=kwargs.pop("source", BankTransaction.SOURCE_CSV),
            **kwargs,
        )

    def entry(self):
        return JournalEntry.objects.create(
            book=self.book, entry_date=date(2026, 6, 1), description="E", status=JournalEntry.STATUS_POSTED
        )

    def lines_of(self, entry):
        return [(line.account_id, line.dr_amount, line.cr_amount) for line in entry.lines.order_by("id")]

    def api(self, method, path, data=None):
        url = f"/a/{self.team.slug}/{self.book.slug}/{path}"
        with current_book(self.book):
            return getattr(self.client, method)(url, data, format="json")


class WriteLinesTest(LinesFixture):
    def test_an_entry_with_no_lines_gets_its_home_line_then_its_legs(self):
        entry = self.entry()

        writer.write_lines(entry, self.checking, [(self.groceries, D("40.00"))], total=D("40.00"), book=self.book)

        self.assertEqual(
            self.lines_of(entry),
            [(self.checking.id, D("0"), D("40.00")), (self.groceries.id, D("40.00"), D("0"))],
        )

    def test_home_fields_are_set_on_a_new_home_line_only(self):
        entry = self.entry()

        writer.write_lines(
            entry,
            self.checking,
            [(self.groceries, D("-15.00"))],
            total=D("-15.00"),
            book=self.book,
            home_fields={"is_cleared": True},
        )

        home = entry.lines.get(account=self.checking)
        self.assertTrue(home.is_cleared)
        self.assertEqual((home.dr_amount, home.cr_amount), (D("15.00"), D("0")))
        self.assertFalse(entry.lines.get(account=self.groceries).is_cleared)

    def test_a_changed_category_is_replaced_by_default(self):
        """Re-apportioning (the split editor, the Transactions page) replaces a line no leg claims."""
        row = self.row()
        categorize.create_entry(row, self.groceries)
        old = row.journal_entry.lines.get(account=self.groceries)

        writer.write_lines(
            row.journal_entry, self.checking, [(self.dining, D("40.00"))], total=D("40.00"), book=self.book
        )

        self.assertFalse(JournalLine.objects.filter(pk=old.pk).exists())
        self.assertTrue(row.journal_entry.lines.filter(account=self.dining).exists())

    def test_repoint_moves_the_category_line_in_place(self):
        """Re-categorizing keeps the line: its pk and the flags it carries."""
        row = self.row()
        categorize.create_entry(row, self.groceries)
        line = row.journal_entry.lines.get(account=self.groceries)
        JournalLine.objects.filter(pk=line.pk).update(is_cleared=True)

        writer.write_lines(
            row.journal_entry,
            self.checking,
            [(self.dining, D("40.00"))],
            total=D("40.00"),
            book=self.book,
            repoint=True,
        )

        line.refresh_from_db()
        self.assertEqual(line.account_id, self.dining.id)
        self.assertTrue(line.is_cleared)
        self.assertEqual(row.journal_entry.lines.count(), 2)

    def test_repoint_refuses_moving_a_reconciled_category_line(self):
        row = self.row()
        categorize.create_entry(row, self.savings)  # a transfer: the category line is Savings' bank line
        JournalLine.objects.filter(journal_entry=row.journal_entry, account=self.savings).update(is_reconciled=True)

        with self.assertRaises(ValueError):
            writer.write_lines(
                row.journal_entry,
                self.checking,
                [(self.groceries, D("40.00"))],
                total=D("40.00"),
                book=self.book,
                repoint=True,
            )

    def test_move_lines_repoints_the_home_line_before_writing(self):
        row = self.row()
        categorize.create_entry(row, self.groceries)
        entry = row.journal_entry
        home = entry.lines.get(account=self.checking)

        writer.write_lines(
            entry,
            self.card,
            [(self.groceries, D("40.00"))],
            total=D("40.00"),
            book=self.book,
            move_lines=entry.lines.filter(account=self.checking),
        )

        home.refresh_from_db()
        self.assertEqual(home.account_id, self.card.id)
        self.assertEqual(entry.lines.count(), 2)

    def test_a_refusal_writes_nothing_and_leaves_the_transaction_usable(self):
        """`bank_revision` catches a refusal and carries on, so nothing may be written first."""
        row = self.row()
        categorize.create_entry(row, self.savings)
        entry = row.journal_entry
        JournalLine.objects.filter(journal_entry=entry, account=self.savings).update(is_reconciled=True)
        before = self.lines_of(entry)

        with transaction.atomic():
            with self.assertRaises(ValueError):
                writer.write_lines(
                    entry,
                    self.card,
                    [(self.groceries, D("40.00"))],
                    total=D("40.00"),
                    book=self.book,
                    move_lines=entry.lines.filter(account=self.checking),
                )
            # Still usable: no write was attempted, so nothing marked it for rollback.
            self.assertEqual(self.lines_of(entry), before)

    def test_an_unchanged_home_line_is_not_saved(self):
        row = self.row()
        categorize.create_entry(row, self.groceries)
        home = row.journal_entry.lines.get(account=self.checking)

        categorize.repoint_category(row, self.dining)

        self.assertEqual(JournalLine.objects.get(pk=home.pk).updated_at, home.updated_at)


def _split_off_tax(legs):
    """A stand-in tax code: 10% of every Groceries leg goes to the ITC account."""
    out = []
    for account, amount in legs:
        if account.name == "Groceries":
            tax = (amount / 10).quantize(D("0.01"))
            itc = Account.objects.get(book=account.book, name="HST ITC")
            out += [(account, amount - tax), (itc, tax)]
        else:
            out.append((account, amount))
    return out


class ExpansionSeamTest(LinesFixture):
    """
    Every path that categorizes a transaction reaches `expand_legs`.

    Patched with a stand-in tax rule, so a path that bypassed the writer would
    leave a two-line entry where the rule asks for three.
    """

    def assert_expanded(self, entry, total_on_home):
        entry.refresh_from_db()
        lines = list(entry.lines.all())
        by_account = {line.account_id: line for line in lines}
        self.assertEqual(len(lines), 3, self.lines_of(entry))
        self.assertEqual(sum(line.dr_amount for line in lines), sum(line.cr_amount for line in lines))
        self.assertEqual(by_account[self.itc.id].dr_amount - by_account[self.itc.id].cr_amount, total_on_home / 10)

    def seam(self):
        return mock.patch.object(writer, "expand_legs", side_effect=_split_off_tax)

    def test_it_is_a_no_op_today(self):
        legs = [(self.groceries, D("10.00")), (self.dining, D("-2.00"))]
        self.assertEqual(writer.expand_legs(legs), legs)

    def test_categorizing_a_feed_row(self):
        row = self.row("40.00")
        with self.seam():
            categorize.categorize_single(row, self.groceries)
        self.assert_expanded(row.journal_entry, D("40.00"))

    def test_recategorizing_a_feed_row(self):
        row = self.row("40.00")
        categorize.categorize_single(row, self.dining)
        with self.seam():
            categorize.categorize_single(row, self.groceries)
        self.assert_expanded(row.journal_entry, D("40.00"))

    def test_csv_auto_categorize(self):
        row = self.row("50.00")
        with self.seam():
            _auto_categorize_transaction(row, self.groceries.id, self.book)
        row.refresh_from_db()
        self.assert_expanded(row.journal_entry, D("50.00"))

    def test_the_feed_add_and_edit_endpoints(self):
        payload = {
            "date": "2026-06-01",
            "category": self.groceries.id,
            "outflow": "20.00",
            "inflow": "0",
            "account": self.checking.id,
            "description": "Shop",
        }
        with self.seam():
            resp = self.api("post", "bankfeed/api/feed/", payload)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        row = BankTransaction.objects.get(pk=resp.json()["id"])
        self.assert_expanded(row.journal_entry, D("20.00"))

        with self.seam():
            # The expanded entry has three lines, which the feed reads as a split:
            # a single-category edit has to say it means to replace them.
            resp = self.api(
                "put", f"bankfeed/api/feed/{row.id}/", {**payload, "outflow": "30.00", "remove_split": True}
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assert_expanded(row.journal_entry, D("30.00"))

    def test_the_transactions_page(self):
        row = self.row("40.00")
        categorize.categorize_single(row, self.dining)
        with self.seam():
            apply_edits(row.journal_entry, TransactionEdits(category_id=self.groceries.id), book=self.book)
        self.assert_expanded(row.journal_entry, D("40.00"))

    def test_opening_balances_and_reconciliation_adjustments_call_it(self):
        with mock.patch.object(writer, "expand_legs", side_effect=lambda legs: list(legs)) as seam:
            create_opening_balances(
                self.book, [OpeningRow(account=self.checking, amount=D("100.00"))], date(2026, 1, 1)
            )
            rec = Reconciliation.objects.create(
                book=self.book, account=self.checking, statement_date=date(2026, 6, 30), statement_balance=D("90")
            )
            create_adjustment(rec, D("-10.00"))
        self.assertEqual(seam.call_count, 2)


class WriterPathsKeepTheirLinesTest(LinesFixture):
    """The routed paths write the same lines they always did."""

    def test_create_entry_puts_the_bank_line_first_on_the_opposite_side(self):
        out, inn = self.row("40.00"), self.row("-25.00")
        categorize.create_entry(out, self.groceries)
        categorize.create_entry(inn, self.groceries)
        self.assertEqual(
            self.lines_of(out.journal_entry),
            [(self.checking.id, D("0"), D("40.00")), (self.groceries.id, D("40.00"), D("0"))],
        )
        self.assertEqual(
            self.lines_of(inn.journal_entry),
            [(self.checking.id, D("25.00"), D("0")), (self.groceries.id, D("0"), D("25.00"))],
        )

    def test_csv_auto_categorize_matches_the_feed(self):
        csv_row, feed_row = self.row("12.34"), self.row("12.34")
        _auto_categorize_transaction(csv_row, self.groceries.id, self.book)
        categorize.create_entry(feed_row, self.groceries)
        csv_row.refresh_from_db()
        strip = [(a, dr, cr) for a, dr, cr in self.lines_of(csv_row.journal_entry)]
        self.assertEqual(strip, self.lines_of(feed_row.journal_entry))
        self.assertEqual(csv_row.journal_entry.source, feed_row.journal_entry.source)

    def test_repoint_category_keeps_the_line(self):
        row = self.row()
        categorize.create_entry(row, self.groceries)
        line = row.journal_entry.lines.get(account=self.groceries)

        categorize.repoint_category(row, self.dining)

        line.refresh_from_db()
        self.assertEqual(line.account_id, self.dining.id)

    def test_opening_balances(self):
        (asset,) = create_opening_balances(
            self.book, [OpeningRow(account=self.checking, amount=D("100.00"))], date(2026, 1, 1)
        )
        (debt,) = create_opening_balances(
            self.book, [OpeningRow(account=self.card, amount=D("60.00"))], date(2026, 1, 1)
        )
        self.assertEqual(asset.lines.get(account=self.checking).dr_amount, D("100.00"))
        self.assertEqual(debt.lines.get(account=self.card).cr_amount, D("60.00"))
        for entry in (asset, debt):
            self.assertEqual(entry.lines.count(), 2)
            self.assertTrue(entry.is_balanced)

    def test_reconciliation_adjustment_line_is_reconciled_on_its_statement(self):
        rec = Reconciliation.objects.create(
            book=self.book, account=self.checking, statement_date=date(2026, 6, 30), statement_balance=D("10")
        )
        entry = create_adjustment(rec, D("10.00"))
        own = entry.lines.get(account=self.checking)
        self.assertEqual((own.dr_amount, own.cr_amount), (D("10.00"), D("0")))
        self.assertTrue(own.is_reconciled)
        self.assertEqual(own.reconciliation_id, rec.id)
        self.assertFalse(entry.lines.exclude(pk=own.pk).get().is_reconciled)


class JournalEntryApiReplaceTest(LinesFixture):
    """The journal-entry API's delete-and-recreate is only for entries no feed row points at."""

    LINES = [
        {"account": None, "dr_amount": "0", "cr_amount": "40.00"},
        {"account": None, "dr_amount": "40.00", "cr_amount": "0"},
    ]

    def lines_payload(self, home, category):
        return [{**self.LINES[0], "account": home.id}, {**self.LINES[1], "account": category.id}]

    def test_a_feed_backed_entry_refuses_line_replacement(self):
        row = self.row()
        categorize.create_entry(row, self.groceries)
        before = self.lines_of(row.journal_entry)

        resp = self.api(
            "patch",
            f"journal/api/journal-entries/{row.journal_entry_id}/",
            {"lines": self.lines_payload(self.checking, self.dining)},
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.lines_of(row.journal_entry), before)

    def test_a_feed_backed_entry_can_still_be_edited_without_lines(self):
        row = self.row()
        categorize.create_entry(row, self.groceries)

        resp = self.api("patch", f"journal/api/journal-entries/{row.journal_entry_id}/", {"description": "Renamed"})

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

    def test_a_plain_entry_still_has_its_lines_replaced(self):
        entry = self.entry()
        writer.add_lines(
            entry,
            [
                {"account": self.checking, "dr_amount": D("0"), "cr_amount": D("40.00")},
                {"account": self.groceries, "dr_amount": D("40.00"), "cr_amount": D("0")},
            ],
            book=self.book,
        )

        resp = self.api(
            "patch",
            f"journal/api/journal-entries/{entry.id}/",
            {"lines": self.lines_payload(self.checking, self.dining)},
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(set(entry.lines.values_list("account_id", flat=True)), {self.checking.id, self.dining.id})


class LinesAreWrittenInOnePlaceTest(TestCase):
    """
    A transaction's lines are created only by `apps.journal.services.lines`.

    A path that builds its own `JournalLine` skips the leg-expansion seam (tax
    codes) and whatever guard the writer's choke point applies to every write.
    The allowlist is the whole-book bulk writers, each for a reason recorded in
    the writer's module docstring.
    """

    WRITER = "apps/journal/services/lines.py"
    ALLOWED = {
        # Defines the bulk insert the importers use; never builds a line itself.
        "apps/journal/models.py": "the model and its bulk-insert helper",
        "apps/ynab_import/services/apply.py": "whole-book YNAB import into an empty book",
        "apps/portability/services/apply.py": "whole-book import of an export into an empty book",
        "apps/budget/ledger.py": "budget entries: not transactions, with their own single writer",
    }
    CREATING = {"create", "bulk_create", "bulk_create_for_import", "get_or_create", "update_or_create"}

    def offenders_in(self, source):
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # JournalLine(...)
            if isinstance(func, ast.Name) and func.id == "JournalLine":
                found.append(node.lineno)
                continue
            if not (isinstance(func, ast.Attribute) and func.attr in self.CREATING):
                continue
            target = ast.unparse(func.value)
            # JournalLine.objects.create(...), entry.lines.create(...), account.journal_lines.create(...)
            if target.startswith("JournalLine.") or target.split(".")[-1] in ("lines", "journal_lines"):
                found.append(node.lineno)
        return found

    def test_the_scan_catches_each_form(self):
        source = "\n".join(
            [
                "JournalLine(account=a)",
                "JournalLine.objects.create(account=a)",
                "JournalLine.objects.bulk_create_for_import(rows)",
                "entry.lines.create(account=a)",
                "account.journal_lines.create(journal_entry=e)",
                "Payee.objects.create(name='x')",
            ]
        )
        self.assertEqual(self.offenders_in(source), [1, 2, 3, 4, 5])

    def test_journal_lines_are_only_created_by_the_writer(self):
        root = Path(settings.BASE_DIR)
        offenders = []
        for path in (root / "apps").rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if rel == self.WRITER or rel in self.ALLOWED:
                continue
            if "/migrations/" in rel or "/tests" in rel or "/test_" in rel or rel.endswith("tests.py"):
                continue
            offenders += [f"{rel}:{lineno}" for lineno in self.offenders_in(path.read_text())]
        self.assertEqual(offenders, [], "Write a transaction's lines through apps.journal.services.lines")

    def test_the_allowlist_has_no_stale_entries(self):
        root = Path(settings.BASE_DIR)
        for rel in self.ALLOWED:
            self.assertTrue((root / rel).exists(), rel)
