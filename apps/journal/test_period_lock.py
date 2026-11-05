"""
Tests for the closed period (`Book.locked_through`, `apps.journal.services.period_lock`).

The guarantee being protected: once a book is closed through a date, nothing
dated on or before it changes -- whichever page, endpoint or service tries -- and
the refusal says why in words the user can act on. Budget entries and
uncategorized bank rows are deliberately outside it.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    Account,
    AccountGroup,
)
from apps.audit.models import AuditEvent
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.bank_revision import Revision, revise
from apps.bank_feed.services.csv_upload import _auto_categorize_transaction
from apps.books.models import Book
from apps.budget import ledger
from apps.onboarding.services.opening import OpeningBalanceError, OpeningRow, create_opening_balances
from apps.reconciliation.services import candidates, session
from apps.reconciliation.services.signs import to_statement
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

from .models import JournalEntry, JournalLine
from .services import period_lock
from .services.period_lock import PeriodLockedError

LOCK = date(2026, 6, 30)
CLOSED = date(2026, 6, 15)
OPEN = date(2026, 7, 15)


class PeriodLockTestCase(TestCase):
    """A book closed through Jun 30 with a categorized row on each side of it."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Lock Team", slug="lock-team")
        cls.book = cls.team.default_book
        cls.admin = CustomUser.objects.create_user(username="lock-admin", password="pass")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.member = CustomUser.objects.create_user(username="lock-member", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})

        assets = AccountGroup.objects.create(book=cls.book, name="Lock Banks", account_type=ACCOUNT_TYPE_ASSET)
        expenses = AccountGroup.objects.create(book=cls.book, name="Lock Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        equity = AccountGroup.objects.create(
            book=cls.book, name="Lock Equity", account_type=ACCOUNT_TYPE_EQUITY, is_system=True
        )
        cls.chequing = Account.objects.create(book=cls.book, name="Lock Chequing", account_group=assets, has_feed=True)
        cls.groceries = Account.objects.create(book=cls.book, name="Lock Groceries", account_group=expenses)
        cls.dining = Account.objects.create(book=cls.book, name="Lock Dining", account_group=expenses)
        cls.adjustments = Account.objects.create(
            book=cls.book, name="Reconciliation Adjustments", account_group=equity, is_system=True
        )

        # Written before the lock exists -- after it, they couldn't be.
        cls.closed_entry, cls.closed_row = cls.categorized(CLOSED, "Closed groceries")
        cls.open_entry, cls.open_row = cls.categorized(OPEN, "Open groceries")
        cls.closed_void_entry, cls.closed_void_row = cls.categorized(date(2026, 6, 10), "Voided before closing")
        cls.closed_void_entry.status = JournalEntry.STATUS_VOID
        cls.closed_void_entry.save()
        cls.closed_uncategorized = cls.feed_row(date(2026, 6, 20), "Late arrival")
        cls.open_uncategorized = cls.feed_row(date(2026, 7, 20), "New arrival")

        Book.objects.filter(pk=cls.book.pk).update(locked_through=LOCK)
        cls.book.refresh_from_db()

    @classmethod
    def feed_row(cls, posted, description, amount=Decimal("40.00"), entry=None):
        return BankTransaction.objects.create(
            book=cls.book,
            account=cls.chequing,
            amount=amount,
            posted_date=posted,
            description=description,
            source=BankTransaction.SOURCE_MANUAL,
            journal_entry=entry,
        )

    @classmethod
    def categorized(cls, entry_date, description, amount=Decimal("40.00")):
        entry = JournalEntry.objects.create(
            book=cls.book,
            entry_date=entry_date,
            description=description,
            source=JournalEntry.SOURCE_MANUAL,
            status=JournalEntry.STATUS_POSTED,
        )
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=cls.chequing, cr_amount=amount)
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=cls.groceries, dr_amount=amount)
        return entry, cls.feed_row(entry_date, description, amount, entry)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def api(self, path):
        return f"/a/{self.team.slug}/{self.book.slug}/{path}"

    def assert_locked_response(self, response):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("closed", response.json()["error"])
        return response.json()


class GuardTest(PeriodLockTestCase):
    def test_the_lock_date_itself_is_closed(self):
        self.assertTrue(period_lock.is_locked(self.book, LOCK))
        self.assertTrue(period_lock.is_locked(self.book, CLOSED))
        self.assertFalse(period_lock.is_locked(self.book, date(2026, 7, 1)))

    def test_no_lock_means_nothing_is_closed(self):
        self.book.locked_through = None
        self.assertFalse(period_lock.is_locked(self.book, date(1990, 1, 1)))
        period_lock.assert_entry_mutable(self.closed_entry, book=self.book)

    def test_the_message_names_the_date_and_who_can_change_it(self):
        with self.assertRaises(PeriodLockedError) as caught:
            period_lock.assert_date_open(self.book, CLOSED)
        self.assertIn("2026", str(caught.exception))
        self.assertIn("admin", str(caught.exception))
        self.assertIn("settings", str(caught.exception))

    def test_redating_across_the_boundary_is_refused_both_ways(self):
        with self.assertRaises(PeriodLockedError):
            period_lock.assert_redate_allowed(self.closed_entry, OPEN, book=self.book)
        with self.assertRaises(PeriodLockedError):
            period_lock.assert_redate_allowed(self.open_entry, CLOSED, book=self.book)
        period_lock.assert_redate_allowed(self.open_entry, date(2026, 8, 1), book=self.book)

    def test_first_open_date(self):
        self.assertEqual(period_lock.first_open_date(self.book, CLOSED), date(2026, 7, 1))
        self.assertEqual(period_lock.first_open_date(self.book, OPEN), OPEN)

    def test_exempt_switches_the_lock_off(self):
        with period_lock.exempt():
            self.assertFalse(period_lock.is_locked(self.book, CLOSED))
        self.assertTrue(period_lock.is_locked(self.book, CLOSED))


class ModelBackstopTest(PeriodLockTestCase):
    def test_creating_an_entry_in_the_closed_period_is_refused(self):
        with self.assertRaises(PeriodLockedError):
            JournalEntry.objects.create(book=self.book, entry_date=CLOSED, description="Backdated")

    def test_an_unchanged_save_is_allowed_and_a_change_is_not(self):
        entry = JournalEntry.objects.get(pk=self.closed_entry.pk)
        entry.save()
        entry.description = "Edited"
        with self.assertRaises(PeriodLockedError):
            entry.save()

    def test_redating_an_open_entry_into_the_closed_period_is_refused(self):
        entry = JournalEntry.objects.get(pk=self.open_entry.pk)
        entry.entry_date = CLOSED
        with self.assertRaises(PeriodLockedError):
            entry.save()

    def test_deleting_a_closed_entry_is_refused(self):
        with self.assertRaises(PeriodLockedError):
            JournalEntry.objects.get(pk=self.closed_entry.pk).delete()

    def test_a_line_amount_is_locked_but_its_reconciled_flag_is_not(self):
        line = JournalLine.objects.get(journal_entry=self.closed_entry, account=self.chequing)
        line.is_reconciled = True
        line.save()
        line.cr_amount = Decimal("41.00")
        with self.assertRaises(PeriodLockedError):
            line.save()
        with self.assertRaises(PeriodLockedError):
            JournalLine.objects.get(pk=line.pk).delete()

    def test_budget_entries_are_not_locked(self):
        ledger.set_budget(self.book, self.groceries, date(2026, 6, 1), Decimal("300"))
        ledger.set_budget(self.book, self.groceries, date(2026, 6, 1), Decimal("350"))
        self.assertEqual(ledger.budget_amount(self.book, self.groceries, date(2026, 6, 1)), Decimal("350"))
        budget_entry = JournalEntry.objects.get(book=self.book, source=JournalEntry.SOURCE_BUDGET)
        self.assertFalse(period_lock.entry_is_locked(budget_entry, book=self.book))


class TransactionsPageTest(PeriodLockTestCase):
    def transactions(self, suffix=""):
        return self.api(f"journal/api/transactions/{suffix}")

    def test_editing_a_closed_transaction_is_refused(self):
        response = self.client.patch(
            self.transactions("edit/"), {"ids": [self.closed_entry.id], "description": "Edited"}, format="json"
        )
        self.assert_locked_response(response)
        self.closed_entry.refresh_from_db()
        self.assertEqual(self.closed_entry.description, "Closed groceries")

    def test_editing_an_open_transaction_still_works(self):
        response = self.client.patch(
            self.transactions("edit/"), {"ids": [self.open_entry.id], "description": "Edited"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_redating_into_and_out_of_the_closed_period_is_refused(self):
        into = self.client.patch(
            self.transactions("edit/"), {"ids": [self.open_entry.id], "date": "2026-06-01"}, format="json"
        )
        self.assert_locked_response(into)
        out = self.client.patch(
            self.transactions("edit/"), {"ids": [self.closed_entry.id], "date": "2026-07-02"}, format="json"
        )
        self.assert_locked_response(out)

    def test_a_batch_with_one_closed_transaction_writes_nothing(self):
        response = self.client.patch(
            self.transactions("edit/"),
            {"ids": [self.open_entry.id, self.closed_entry.id], "description": "Both"},
            format="json",
        )
        self.assert_locked_response(response)
        self.open_entry.refresh_from_db()
        self.assertEqual(self.open_entry.description, "Open groceries")

    def test_delete_void_and_restore_are_refused(self):
        self.assert_locked_response(
            self.client.post(self.transactions("batch_delete/"), {"ids": [self.closed_entry.id]}, format="json")
        )
        self.assert_locked_response(
            self.client.post(
                self.transactions("batch_status/"), {"ids": [self.closed_entry.id], "status": "void"}, format="json"
            )
        )
        self.assert_locked_response(
            self.client.post(
                self.transactions("batch_status/"),
                {"ids": [self.closed_void_entry.id], "status": "posted"},
                format="json",
            )
        )
        self.assertTrue(JournalEntry.objects.filter(pk=self.closed_entry.pk, status="posted").exists())
        self.assertTrue(JournalEntry.objects.filter(pk=self.closed_void_entry.pk, status="void").exists())

    def test_the_edit_modal_is_told_why_it_is_read_only(self):
        body = self.client.get(self.transactions(f"{self.closed_entry.id}/")).json()
        self.assertIn("closed", body["locked_reason"])
        self.assertFalse(any(body["capabilities"].values()))

        body = self.client.get(self.transactions(f"{self.open_entry.id}/")).json()
        self.assertIsNone(body["locked_reason"])
        self.assertTrue(body["capabilities"]["can_edit"])

    def test_the_page_names_the_closed_period(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("journal:transactions_home", args=self.book.url_args))
        self.assertContains(response, 'data-testid="period-lock-note"')


class JournalApiTest(PeriodLockTestCase):
    def entry_payload(self, entry_date):
        return {
            "entry_date": entry_date,
            "description": "By hand",
            "status": "posted",
            "lines": [
                {"account": self.chequing.id, "dr_amount": "0", "cr_amount": "10.00"},
                {"account": self.groceries.id, "dr_amount": "10.00", "cr_amount": "0"},
            ],
        }

    def test_creating_in_the_closed_period_is_refused(self):
        url = self.api("journal/api/journal-entries/")
        self.assertEqual(self.client.post(url, self.entry_payload("2026-06-01"), format="json").status_code, 400)
        self.assertEqual(self.client.post(url, self.entry_payload("2026-07-01"), format="json").status_code, 201)

    def test_editing_deleting_and_voiding_a_closed_entry_are_refused(self):
        url = self.api(f"journal/api/journal-entries/{self.closed_entry.id}/")
        self.assertEqual(self.client.put(url, self.entry_payload("2026-06-15"), format="json").status_code, 400)
        self.assert_locked_response(self.client.delete(url))
        self.assert_locked_response(self.client.post(url + "void_entry/"))
        self.assertTrue(JournalEntry.objects.filter(pk=self.closed_entry.pk, status="posted").exists())

    def test_deleting_through_the_line_api_is_refused(self):
        line = self.closed_entry.lines.first()
        self.assert_locked_response(self.client.delete(self.api(f"journal/api/lines/{line.id}/")))
        self.assertTrue(JournalEntry.objects.filter(pk=self.closed_entry.pk).exists())


class BankFeedTest(PeriodLockTestCase):
    def feed(self, suffix=""):
        return self.api(f"bankfeed/api/feed/{suffix}")

    def edit_payload(self, row, **overrides):
        payload = {
            "date": row.posted_date.isoformat(),
            "account": self.chequing.id,
            "category": self.groceries.id,
            "outflow": "40.00",
            "inflow": "0",
            "description": row.description,
            "payee": "",
        }
        payload.update(overrides)
        return payload

    def test_categorizing_a_row_into_the_closed_period_names_it(self):
        response = self.client.post(
            self.feed("categorize/"),
            {
                "rows": [{"id": self.closed_uncategorized.id}, {"id": self.open_uncategorized.id}],
                "category_id": self.groceries.id,
            },
            format="json",
        )
        body = self.assert_locked_response(response)
        self.assertEqual([r["id"] for r in body["refused"]], [self.closed_uncategorized.id])
        self.assertFalse(BankTransaction.objects.get(pk=self.open_uncategorized.pk).journal_entry_id)

    def test_categorizing_an_open_row_still_works(self):
        response = self.client.post(
            self.feed("categorize/"),
            {"rows": [{"id": self.open_uncategorized.id}], "category_id": self.groceries.id},
            format="json",
        )
        self.assertEqual(response.status_code, 204, response.content)

    def test_editing_a_closed_row_is_refused_but_an_uncategorized_one_is_not(self):
        self.assert_locked_response(
            self.client.put(
                self.feed(f"{self.closed_row.id}/"),
                self.edit_payload(self.closed_row, category=self.dining.id),
                format="json",
            )
        )
        self.assertEqual(self.closed_entry.lines.filter(account=self.groceries).count(), 1)

        response = self.client.put(
            self.feed(f"{self.closed_uncategorized.id}/"),
            self.edit_payload(self.closed_uncategorized, category=None, description="Renamed"),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assert_locked_response(
            self.client.put(
                self.feed(f"{self.closed_uncategorized.id}/"),
                self.edit_payload(self.closed_uncategorized),
                format="json",
            )
        )

    def test_moving_an_open_row_into_the_closed_period_is_refused(self):
        self.assert_locked_response(
            self.client.put(
                self.feed(f"{self.open_row.id}/"), self.edit_payload(self.open_row, date="2026-06-29"), format="json"
            )
        )

    def test_batch_edit_names_every_closed_row_and_writes_nothing(self):
        response = self.client.patch(
            self.feed("batch_edit/"),
            {
                "ids": [self.closed_uncategorized.id, self.open_uncategorized.id, self.closed_row.id],
                "category_id": self.dining.id,
            },
            format="json",
        )
        body = self.assert_locked_response(response)
        self.assertEqual({r["id"] for r in body["refused"]}, {self.closed_uncategorized.id, self.closed_row.id})
        self.assertFalse(BankTransaction.objects.get(pk=self.open_uncategorized.pk).journal_entry_id)

    def test_void_restore_and_delete_follow_the_entry(self):
        body = self.assert_locked_response(
            self.client.post(self.feed("batch_void/"), {"ids": [self.closed_row.id]}, format="json")
        )
        self.assertEqual(body["refused"][0]["id"], self.closed_row.id)
        self.assert_locked_response(
            self.client.post(self.feed("batch_restore/"), {"ids": [self.closed_void_row.id]}, format="json")
        )
        self.assert_locked_response(
            self.client.post(self.feed("batch_delete/"), {"ids": [self.closed_void_row.id]}, format="json")
        )
        self.assertTrue(JournalEntry.objects.filter(pk=self.closed_void_entry.pk).exists())

    def test_an_uncategorized_row_in_the_closed_period_can_still_be_voided(self):
        response = self.client.post(self.feed("batch_void/"), {"ids": [self.closed_uncategorized.id]}, format="json")
        self.assertEqual(response.status_code, 204, response.content)

    def test_duplicating_a_closed_row_makes_an_uncategorized_copy(self):
        response = self.client.post(self.feed("batch_duplicate/"), {"ids": [self.closed_row.id]}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        copy = BankTransaction.objects.get(raw__duplicated_from=self.closed_row.id)
        self.assertIsNone(copy.journal_entry_id)
        self.assertEqual(copy.posted_date, CLOSED)

    def test_a_categorized_manual_transaction_in_the_closed_period_is_refused(self):
        payload = self.edit_payload(self.closed_row, description="Backdated")
        self.assert_locked_response(self.client.post(self.feed(), payload, format="json"))
        payload["category"] = None
        self.assertEqual(self.client.post(self.feed(), payload, format="json").status_code, 201)

    def test_the_feed_page_names_the_closed_period(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("bank_feed:bank_feed_home", args=self.book.url_args))
        self.assertContains(response, "period-lock-note")

    def test_csv_auto_categorize_leaves_a_closed_row_uncategorized(self):
        _auto_categorize_transaction(self.closed_uncategorized, self.groceries.id, self.book)
        self.closed_uncategorized.refresh_from_db()
        self.assertIsNone(self.closed_uncategorized.journal_entry_id)


class BankRevisionTest(PeriodLockTestCase):
    def test_a_revised_closed_row_keeps_its_figures_and_the_difference_lands_after_the_lock(self):
        result = revise(
            self.closed_row,
            Revision(amount=Decimal("45.00"), posted_date=date(2026, 6, 16), description="Posted groceries"),
        )
        self.closed_row.refresh_from_db()
        self.assertEqual(self.closed_row.amount, Decimal("40.00"))
        self.assertEqual(self.closed_row.posted_date, CLOSED)
        self.assertIn("closed", result.date_kept_reason)
        self.assertEqual(result.difference_row.amount, Decimal("5.00"))
        self.assertEqual(result.difference_row.posted_date, date(2026, 7, 1))
        self.assertIsNone(result.difference_row.journal_entry_id)


class ReconciliationTest(PeriodLockTestCase):
    def test_an_adjustment_in_the_closed_period_is_refused(self):
        draft = session.start(self.chequing, LOCK, Decimal("-500.00"), self.admin)
        difference = candidates.summary(draft).difference
        self.assertNotEqual(difference, 0)
        with self.assertRaises(session.ReconciliationError) as caught:
            session.finish(draft, self.admin, adjust=True, expected_difference=to_statement(self.chequing, difference))
        self.assertIn("closed", str(caught.exception))
        self.assertFalse(JournalEntry.objects.filter(source=JournalEntry.SOURCE_RECONCILIATION).exists())

    def test_a_statement_that_balances_can_be_finished_in_the_closed_period(self):
        draft = session.start(self.chequing, LOCK, Decimal("0"), self.admin)
        finished = session.finish(draft, self.admin)
        self.assertTrue(finished.is_completed)

    def test_undoing_a_statement_whose_adjustment_is_closed_is_refused(self):
        Book.objects.filter(pk=self.book.pk).update(locked_through=None)
        self.chequing.refresh_from_db()
        draft = session.start(self.chequing, LOCK, Decimal("-500.00"), self.admin)
        difference = candidates.summary(draft).difference
        done = session.finish(
            draft, self.admin, adjust=True, expected_difference=to_statement(self.chequing, difference)
        )
        Book.objects.filter(pk=self.book.pk).update(locked_through=LOCK)

        done = type(done).objects.get(pk=done.pk)
        with self.assertRaises(session.ReconciliationError):
            session.undo(done, self.admin)
        done.refresh_from_db()
        self.assertTrue(done.is_completed)


class OpeningBalanceTest(PeriodLockTestCase):
    def test_opening_balances_in_the_closed_period_are_refused(self):
        rows = [OpeningRow(account=self.chequing, amount=Decimal("100"))]
        with self.assertRaises(OpeningBalanceError):
            create_opening_balances(self.book, rows, as_of=CLOSED)
        self.assertEqual(len(create_opening_balances(self.book, rows, as_of=OPEN)), 1)


class SettingsTest(PeriodLockTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def post(self, **data):
        return self.client.post(
            reverse("books:settings", args=self.book.url_args), {"name": self.book.name, "slug": self.book.slug, **data}
        )

    def test_an_admin_sets_moves_and_clears_the_lock_and_each_change_is_logged(self):
        self.post(locked_through="2026-03-31")
        self.book.refresh_from_db()
        self.assertEqual(self.book.locked_through, date(2026, 3, 31))
        event = AuditEvent.objects.filter(event_type=AuditEvent.BOOK_SETTINGS_CHANGED, book=self.book).latest(
            "timestamp"
        )
        self.assertEqual(event.metadata["locked_through"], "2026-03-31")
        self.assertEqual(event.metadata["locked_through_before"], "2026-06-30")

        self.post(locked_through="")
        self.book.refresh_from_db()
        self.assertIsNone(self.book.locked_through)

    def test_a_post_without_the_field_keeps_the_lock(self):
        self.post()
        self.book.refresh_from_db()
        self.assertEqual(self.book.locked_through, LOCK)

    def test_a_future_date_is_refused(self):
        response = self.post(locked_through="2999-01-01")
        self.assertEqual(response.status_code, 200)
        self.book.refresh_from_db()
        self.assertEqual(self.book.locked_through, LOCK)

    def test_a_member_cannot_change_the_lock(self):
        self.client.force_login(self.member)
        self.assertEqual(self.post(locked_through="").status_code, 404)
        self.book.refresh_from_db()
        self.assertEqual(self.book.locked_through, LOCK)

    def test_the_settings_page_shows_the_field(self):
        response = self.client.get(reverse("books:settings", args=self.book.url_args))
        self.assertContains(response, 'data-testid="locked-through-input"')
        self.assertContains(response, 'value="2026-06-30"')


class BulkImportTest(TestCase):
    """The importers that build or replace a whole book are exempt (`period_lock.exempt`)."""

    def test_loading_an_export_into_a_closed_book_works_and_keeps_the_lock(self):
        from apps.portability.services import apply
        from apps.portability.tests.db_fixtures import build_db_fixture_team, make_team
        from apps.portability.tests.test_apply import export_bytes

        source_team, _user, _handles = build_db_fixture_team("Lock Source", "lock-source")
        dest_team, dest_user = make_team("Lock Destination", "lock-destination")
        dest_book = dest_team.default_book
        Book.objects.filter(pk=dest_book.pk).update(locked_through=date(2099, 12, 31))
        dest_book.refresh_from_db()

        apply.apply_archive(dest_book, export_bytes(source_team.default_book), user=dest_user)

        dest_book.refresh_from_db()
        self.assertEqual(dest_book.locked_through, date(2099, 12, 31))
        self.assertTrue(JournalEntry.objects.filter(book=dest_book).exclude(source=JournalEntry.SOURCE_BUDGET).exists())
