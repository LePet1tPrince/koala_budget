"""
One void state for a transaction and its bank rows (`apps.journal.services.voiding`).

A bank row linked to a journal entry is void exactly when the entry is; a row
with no entry carries its own flag. These tests pin that invariant through the
service, the model backstops, the feed endpoints, the data migration that
brought old data into line, and a scan for writes that would bypass all three.
"""

import ast
import importlib
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.apps import apps as global_apps
from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction, VoidRowError
from apps.bank_feed.services.categorize import categorize_single, create_entry
from apps.books.context import current_book
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

from .models import JournalEntry, JournalLine, counted_entries
from .services import voiding


class VoidingFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Void Team", slug="void-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="voider", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        assets = AccountGroup.objects.create(book=cls.book, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        cards = AccountGroup.objects.create(book=cls.book, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        spend = AccountGroup.objects.create(book=cls.book, name="Spend", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=assets, has_feed=True)
        cls.card = Account.objects.create(book=cls.book, name="Card", account_group=cards, has_feed=True)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=spend)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tx(self, account=None, amount="40.00", **kwargs):
        return BankTransaction.objects.create(
            book=self.book,
            account=account or self.checking,
            amount=Decimal(amount),
            posted_date=date(2026, 6, 1),
            description=kwargs.pop("description", "Row"),
            source=BankTransaction.SOURCE_CSV,
            **kwargs,
        )

    def categorized(self, category=None, **kwargs):
        row = self.tx(**kwargs)
        categorize_single(row, category or self.groceries)
        row.refresh_from_db()
        return row

    def transfer(self):
        """A checking -> card transfer: one entry, a primary row and its mirror."""
        primary = self.categorized(category=self.card)
        mirror = BankTransaction.objects.get(journal_entry=primary.journal_entry, is_transfer_mirror=True)
        return primary, mirror

    def url(self, path):
        return f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/{path}"

    def post(self, path, data):
        with current_book(self.book):
            return self.client.post(self.url(path), data, format="json")

    def reload(self, *objs):
        for obj in objs:
            obj.refresh_from_db()


class VoidServiceTest(VoidingFixture):
    def test_voiding_an_entry_voids_every_row_on_it(self):
        primary, mirror = self.transfer()
        entry = primary.journal_entry

        voiding.void(entries=[entry])

        self.reload(primary, mirror, entry)
        self.assertEqual(entry.status, JournalEntry.STATUS_VOID)
        self.assertTrue(primary.is_void and mirror.is_void)
        self.assertIsNotNone(primary.voided_at)

    def test_voiding_a_row_voids_its_entry_and_its_siblings(self):
        primary, mirror = self.transfer()

        voiding.void(rows=[mirror])

        self.reload(primary, mirror)
        self.assertTrue(primary.is_void and mirror.is_void)
        self.assertEqual(primary.journal_entry.status, JournalEntry.STATUS_VOID)

    def test_an_uncategorized_row_is_voided_on_its_own(self):
        row = self.tx()
        other = self.tx()

        voiding.void(rows=[row])

        self.reload(row, other)
        self.assertTrue(row.is_void)
        self.assertFalse(other.is_void)

    def test_restore_reverses_both_kinds(self):
        primary, mirror = self.transfer()
        loose = self.tx()
        voiding.void(rows=[primary, loose])

        voiding.restore(rows=[mirror, loose])

        self.reload(primary, mirror, loose)
        self.assertEqual(primary.journal_entry.status, JournalEntry.STATUS_POSTED)
        self.assertFalse(primary.is_void or mirror.is_void or loose.is_void)
        self.assertIsNone(loose.voided_at)

    def test_a_reconciled_line_refuses_the_whole_batch_and_names_the_row(self):
        plain = self.categorized()
        reconciled = self.categorized()
        JournalLine.objects.filter(journal_entry=reconciled.journal_entry, account=self.checking).update(
            is_reconciled=True
        )

        with self.assertRaises(voiding.VoidRefused) as ctx:
            voiding.void(rows=[plain, reconciled])

        self.assertEqual([r["id"] for r in ctx.exception.refused], [reconciled.id])
        self.assertIn("reconciled", str(ctx.exception))
        self.reload(plain)
        self.assertFalse(plain.is_void)
        self.assertEqual(plain.journal_entry.status, JournalEntry.STATUS_POSTED)

    def test_the_other_side_of_a_transfer_being_reconciled_is_named_as_such(self):
        primary, mirror = self.transfer()
        JournalLine.objects.filter(journal_entry=primary.journal_entry, account=self.card).update(is_reconciled=True)

        with self.assertRaises(voiding.VoidRefused) as ctx:
            voiding.void(rows=[primary])

        self.assertIn("other side of this transfer", str(ctx.exception))

    def test_a_reconciliation_adjustment_is_not_restored_here(self):
        entry = JournalEntry.objects.create(
            book=self.book,
            entry_date=date(2026, 6, 1),
            description="Adjustment",
            source=JournalEntry.SOURCE_RECONCILIATION,
            status=JournalEntry.STATUS_VOID,
        )
        with self.assertRaises(voiding.VoidRefused):
            voiding.restore(entries=[entry])
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.STATUS_VOID)

    def test_a_void_entry_counts_toward_nothing(self):
        row = self.categorized()
        voiding.void(rows=[row])
        counted = JournalEntry.objects.filter(counted_entries(), pk=row.journal_entry_id)
        self.assertFalse(counted.exists())


class ModelBackstopTest(VoidingFixture):
    """Callers that skip the service still cannot leave a row and its entry disagreeing."""

    def test_saving_an_entry_with_a_new_status_carries_it_to_its_rows(self):
        primary, mirror = self.transfer()
        entry = JournalEntry.objects.get(pk=primary.journal_entry_id)

        entry.status = JournalEntry.STATUS_VOID
        entry.save()

        self.reload(primary, mirror)
        self.assertTrue(primary.is_void and mirror.is_void)

        entry.status = JournalEntry.STATUS_POSTED
        entry.save()
        self.reload(primary, mirror)
        self.assertFalse(primary.is_void or mirror.is_void)

    def test_a_linked_rows_flag_follows_its_entry_whatever_it_is_set_to(self):
        row = self.categorized()

        row.is_void = True
        row.save()

        row.refresh_from_db()
        self.assertFalse(row.is_void)  # the entry is posted, so the row is not void

    def test_a_stale_row_saved_after_its_entry_was_voided_stays_void(self):
        row = self.categorized()
        stale = BankTransaction.objects.get(pk=row.pk)
        voiding.void(rows=[row])

        stale.description = "edited elsewhere"
        stale.save(update_fields=["description"])

        stale.refresh_from_db()
        self.assertTrue(stale.is_void)

    def test_linking_a_void_row_to_an_entry_that_counts_is_refused(self):
        row = self.tx()
        voiding.void(rows=[row])
        row.refresh_from_db()

        with self.assertRaises(VoidRowError):
            create_entry(row, self.groceries)
        row.refresh_from_db()
        self.assertIsNone(row.journal_entry_id)

    def test_archive_and_restore_on_a_row_are_not_available(self):
        row = self.tx()
        with self.assertRaises(NotImplementedError):
            row.archive()
        with self.assertRaises(NotImplementedError):
            row.restore()


class FeedEndpointTest(VoidingFixture):
    def test_batch_void_and_restore(self):
        primary, mirror = self.transfer()

        resp = self.post("batch_void/", {"ids": [primary.id]})
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.reload(primary, mirror)
        self.assertTrue(primary.is_void and mirror.is_void)

        resp = self.post("batch_restore/", {"ids": [mirror.id]})
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.reload(primary, mirror)
        self.assertFalse(primary.is_void or mirror.is_void)

    def test_a_plain_reconciled_row_is_refused_not_silently_skipped(self):
        plain = self.tx()
        reconciled = self.categorized()
        JournalLine.objects.filter(journal_entry=reconciled.journal_entry, account=self.checking).update(
            is_reconciled=True
        )

        resp = self.post("batch_void/", {"ids": [plain.id, reconciled.id]})

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual([r["id"] for r in resp.data["refused"]], [reconciled.id])
        self.reload(plain)
        self.assertFalse(plain.is_void)

    def test_a_void_row_cannot_be_edited_or_categorized(self):
        row = self.categorized()
        voiding.void(rows=[row])

        with current_book(self.book):
            resp = self.client.put(
                self.url(f"{row.id}/"),
                {"date": "2026-06-01", "outflow": "40.00", "account": self.checking.id, "category": self.card.id},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("void", resp.data["error"])

        with current_book(self.book):
            resp = self.client.patch(self.url("batch_edit/"), {"ids": [row.id], "payee": "X"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["refused"][0]["id"], row.id)

        loose = self.tx()
        voiding.void(rows=[loose])
        resp = self.post("categorize/", {"rows": [{"id": loose.id}], "category_id": self.groceries.id})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_another_books_rows_are_not_voided(self):
        other_team = Team.objects.create(name="Other", slug="other-void")
        other_group = AccountGroup.objects.create(
            book=other_team.default_book, name="Bank", account_type=ACCOUNT_TYPE_ASSET
        )
        other_account = Account.objects.create(book=other_team.default_book, name="Theirs", account_group=other_group)
        theirs = BankTransaction.objects.create(
            book=other_team.default_book,
            account=other_account,
            amount=Decimal("5"),
            posted_date=date(2026, 6, 1),
            description="Theirs",
        )

        self.post("batch_void/", {"ids": [theirs.id]})

        theirs.refresh_from_db()
        self.assertFalse(theirs.is_void)


class ConsistencyCheckTest(VoidingFixture):
    def test_command_reports_and_fixes_drift(self):
        row = self.categorized()
        BankTransaction.objects.filter(pk=row.pk).update(is_void=True)  # drift, bypassing the models

        with self.assertRaises(CommandError):
            call_command("void_consistency", stdout=StringIO())
        call_command("void_consistency", "--fix", stdout=StringIO())

        row.refresh_from_db()
        self.assertFalse(row.is_void)
        voiding.assert_consistent(self.book)


class DataMigrationTest(VoidingFixture):
    """`bank_feed.0009_void_consistency`, run against today's models."""

    def forwards(self):
        module = importlib.import_module("apps.bank_feed.migrations.0009_void_consistency")
        module.forwards(global_apps, None)

    def test_a_void_row_on_a_posted_entry_voids_the_entry_and_its_siblings(self):
        primary, mirror = self.transfer()
        BankTransaction.objects.filter(pk=primary.pk).update(is_void=True)  # the old "archived" state

        self.forwards()

        self.reload(primary, mirror)
        self.assertEqual(primary.journal_entry.status, JournalEntry.STATUS_VOID)
        self.assertTrue(mirror.is_void)

    def test_rows_on_a_void_entry_are_voided(self):
        row = self.categorized()
        JournalEntry.objects.filter(pk=row.journal_entry_id).update(status=JournalEntry.STATUS_VOID)

        self.forwards()

        row.refresh_from_db()
        self.assertTrue(row.is_void)

    def test_balances_do_not_move(self):
        kept = self.categorized(amount="10.00")
        archived = self.categorized(amount="500.00")
        BankTransaction.objects.filter(pk=archived.pk).update(is_void=True)

        self.forwards()  # raises if any account's balance moved

        kept.refresh_from_db()
        self.assertEqual(kept.journal_entry.status, JournalEntry.STATUS_POSTED)
        self.assertEqual(Account.objects.get(pk=self.checking.pk).balance, Decimal("-10.00"))


class NoBypassingWritesTest(TestCase):
    """
    `QuerySet.update()` skips both models' `save()`, so a void state written that
    way can leave a row and its entry disagreeing. Only the voiding service, the
    models themselves, the consistency command and the migrations may do it.
    """

    ALLOWED = {
        "apps/journal/services/voiding.py",
        "apps/journal/models.py",
        "apps/journal/management/commands/void_consistency.py",
    }

    def test_void_state_is_not_written_with_update(self):
        root = Path(settings.BASE_DIR)
        offenders = []
        for path in (root / "apps").rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if rel in self.ALLOWED or "/migrations/" in rel or "/tests" in rel or "/test_" in rel:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "update"):
                    continue
                for kw in node.keywords:
                    writes_void = kw.arg in ("is_void", "voided_at")
                    writes_status = kw.arg == "status" and "STATUS_VOID" in ast.unparse(kw.value)
                    if writes_void or writes_status:
                        offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [], "Change void state through apps.journal.services.voiding")
