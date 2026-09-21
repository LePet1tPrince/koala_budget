"""
Phase 3: writing an archive into a team (§4, §6, §7 Phase 3).

The headline test is the round trip (§7 Phase 5): export a real team, import
that export into a second, and export the second team again. The two exports
must describe the same books. They are compared *structurally* -- grouped by
name/date/amount rather than by the raw `account_id`/`entry_id` columns --
because those ids are new primary keys assigned by the second team's import,
and nothing about this feature promises they land on the same integers the
source team happened to have. (Postgres bulk_create *does* tend to hand back
sequential ids in insertion order, which would make a raw positional
comparison pass too, most of the time -- structural comparison does not
depend on that implementation detail holding.)
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Account, AccountGroup
from apps.audit.models import AuditEvent
from apps.budget.models import Budget
from apps.journal.models import JournalEntry, JournalLine
from apps.portability.services import apply, export, read, write
from apps.portability.services.schema import UNCATEGORIZED_STATUS, DocumentError

from .db_fixtures import build_db_fixture_team, make_team


def export_bytes(team) -> bytes:
    accounts, journal_rows, budget_rows = export.build_archive(team)
    checks = export.build_checks(team)
    omitted = export.build_omitted(team)
    return write.build_archive_bytes(
        accounts=accounts,
        journal=journal_rows,
        budget=budget_rows,
        source={"team_name": team.name},
        checks=checks,
        omitted=omitted,
    )


def _account_names(tables) -> dict[int, str]:
    return {row["account_id"]: row["name"] for row in tables.accounts}


def _entry_signature(tables, entry_id: int) -> tuple:
    """An entry's lines, keyed by account name rather than account_id, so two
    teams' exports of the same logical entry compare equal regardless of
    which raw ids either team happened to assign."""
    names = _account_names(tables)
    lines = sorted(
        (
            names[row["account_id"]],
            row["dr_amount"],
            row["cr_amount"],
            row["is_cleared"],
            row["is_reconciled"],
            row["is_archived"],
            row["feed_source"],
            row["feed_amount"],
            row["feed_is_mirror"],
        )
        for row in tables.journal_rows
        if row["entry_id"] == entry_id
    )
    any_row = next(row for row in tables.journal_rows if row["entry_id"] == entry_id)
    return (
        any_row["entry_date"],
        any_row["payee"],
        any_row["description"],
        any_row["source"],
        any_row["status"],
        tuple(lines),
    )


def _entry_signatures(tables) -> set:
    entry_ids = {row["entry_id"] for row in tables.journal_rows if row["entry_id"] is not None}
    return {_entry_signature(tables, eid) for eid in entry_ids}


def _uncategorized_signatures(tables) -> set:
    names = _account_names(tables)
    return {
        (
            names[row["account_id"]],
            row["feed_source"],
            row["feed_amount"],
            row["feed_posted_date"],
            row["feed_description"],
        )
        for row in tables.journal_rows
        if row["status"] == UNCATEGORIZED_STATUS
    }


def _account_signatures(tables) -> set:
    return {
        (
            row["name"],
            row["account_type"],
            row["group_name"],
            row["has_feed"],
            row["is_system"],
            row["is_archived"],
            row["institution"],
            row["goal_name"],
            row["goal_target_amount"],
            row["goal_is_complete"],
        )
        for row in tables.accounts
    }


def _budget_signatures(tables) -> set:
    names = _account_names(tables)
    return {
        (row["kind"], row["month"], names[row["account_id"]], row["amount"], row["notes"], row["is_archived"])
        for row in tables.budget_rows
    }


class RoundTripTests(TestCase):
    """Export -> import into a fresh team -> export again -> compare."""

    @classmethod
    def setUpTestData(cls):
        cls.source_team, cls.source_user, cls.handles = build_db_fixture_team("Source", "source")
        cls.dest_team, cls.dest_user = make_team("Destination", "destination")

    def setUp(self):
        self.source_bytes = export_bytes(self.source_team)
        self.result = apply.apply_archive(self.dest_team, self.source_bytes, user=self.dest_user)
        self.dest_bytes = export_bytes(self.dest_team)
        self.source_tables = read.read_archive(self.source_bytes)
        self.dest_tables = read.read_archive(self.dest_bytes)

    def test_apply_does_not_raise(self):
        pass  # setUp already ran it; a raise there fails this test

    def test_same_number_of_accounts_entries_and_budget_rows(self):
        self.assertEqual(len(self.source_tables.accounts), len(self.dest_tables.accounts))
        self.assertEqual(len(self.source_tables.journal_rows), len(self.dest_tables.journal_rows))
        self.assertEqual(len(self.source_tables.budget_rows), len(self.dest_tables.budget_rows))

    def test_accounts_match_structurally(self):
        self.assertEqual(_account_signatures(self.source_tables), _account_signatures(self.dest_tables))

    def test_entries_match_structurally(self):
        self.assertEqual(_entry_signatures(self.source_tables), _entry_signatures(self.dest_tables))

    def test_uncategorized_rows_match_structurally(self):
        self.assertEqual(_uncategorized_signatures(self.source_tables), _uncategorized_signatures(self.dest_tables))

    def test_budget_rows_match_structurally(self):
        self.assertEqual(_budget_signatures(self.source_tables), _budget_signatures(self.dest_tables))

    def test_both_check_blocks_agree_on_the_money(self):
        self.assertEqual(
            self.source_tables.manifest.checks["trial_balance"], self.dest_tables.manifest.checks["trial_balance"]
        )
        self.assertEqual(self.source_tables.manifest.checks["net_worth"], self.dest_tables.manifest.checks["net_worth"])
        self.assertEqual(
            self.source_tables.manifest.checks["budget_totals"], self.dest_tables.manifest.checks["budget_totals"]
        )
        self.assertEqual(
            self.source_tables.manifest.checks["feed_counts"], self.dest_tables.manifest.checks["feed_counts"]
        )

    def test_reconciled_transfer_survives_with_its_mirror(self):
        transfer = next(sig for sig in _entry_signatures(self.dest_tables) if sig[2] == "Credit card payment")
        lines = transfer[5]
        mirrors = sorted(line[8] for line in lines)  # feed_is_mirror is index 8
        self.assertEqual(mirrors, [False, True])

    def test_void_entry_is_carried(self):
        void_entries = [sig for sig in _entry_signatures(self.dest_tables) if sig[4] == "void"]
        self.assertEqual(len(void_entries), 1)

    def test_goal_and_negative_allocation_survive(self):
        goal_account = next(a for a in self.dest_tables.accounts if a["goal_name"] == "New Deck")
        self.assertEqual(goal_account["goal_target_amount"], Decimal("5000.00"))
        allocations = [
            row
            for row in self.dest_tables.budget_rows
            if row["kind"] == "goal" and row["account_id"] == goal_account["account_id"]
        ]
        self.assertIn(Decimal("-100.00"), [row["amount"] for row in allocations])

    def test_journal_line_budget_link_is_rederived(self):
        # Every JournalLine on the destination team's Groceries account in
        # January should be linked to that month's Budget row -- proof
        # bulk_create_for_import's (account, month) resolution ran.
        groceries = Account.objects.get(team=self.dest_team, name="Groceries")
        budget = Budget.objects.get(team=self.dest_team, category=groceries, month=date(2026, 1, 1))
        lines = JournalLine.objects.filter(team=self.dest_team, account=groceries, dr_amount__gt=0)
        self.assertTrue(lines.exists())
        self.assertTrue(all(line.budget_id == budget.id for line in lines))

    def test_result_counts_are_sane(self):
        self.assertEqual(self.result.accounts, len(self.source_tables.accounts))
        self.assertEqual(self.result.goals, 1)
        self.assertGreater(self.result.lines, 0)
        self.assertGreater(self.result.bank_transactions, 0)

    def test_two_audit_events_are_logged(self):
        events = AuditEvent.objects.filter(team=self.dest_team).order_by("timestamp")
        types = [e.event_type for e in events]
        self.assertIn(AuditEvent.DATA_WIPED, types)
        self.assertIn(AuditEvent.DATA_IMPORTED, types)


class ImportIntoNonEmptyTeamTests(TestCase):
    """Every import wipes first -- including a team that already has books (§4.1)."""

    def test_the_destinations_own_data_is_gone_afterwards(self):
        source_team, _u, _h = build_db_fixture_team("Src", "src")
        dest_team, dest_user, dest_handles = build_db_fixture_team("Dst", "dst")
        original_dest_account_ids = set(Account.objects.filter(team=dest_team).values_list("id", flat=True))

        data = export_bytes(source_team)
        apply.apply_archive(dest_team, data, user=dest_user)

        # None of the destination's original rows survive.
        self.assertFalse(Account.objects.filter(id__in=original_dest_account_ids).exists())
        # But the destination now has the source's books.
        self.assertTrue(Account.objects.filter(team=dest_team, name="Goal: New Deck").exists())


class RollbackTests(TestCase):
    """A failed check must undo the wipe too -- the whole point of one transaction."""

    def test_a_forced_check_failure_leaves_the_destination_untouched(self):
        source_team, _u, _h = build_db_fixture_team("Src2", "src2")
        dest_team, dest_user, dest_handles = build_db_fixture_team("Dst2", "dst2")
        original_account_names = set(Account.objects.filter(team=dest_team).values_list("name", flat=True))
        original_entry_count = JournalEntry.objects.filter(team=dest_team).count()

        accounts, journal_rows, budget_rows = export.build_archive(source_team)
        checks = export.build_checks(source_team)
        checks["trial_balance"]["dr"] = "999999.99"  # force a mismatch
        tampered = write.build_archive_bytes(
            accounts=accounts,
            journal=journal_rows,
            budget=budget_rows,
            source={},
            checks=checks,
            omitted={},
        )

        with self.assertRaises(apply.ApplyError):
            apply.apply_archive(dest_team, tampered, user=dest_user)

        self.assertEqual(
            set(Account.objects.filter(team=dest_team).values_list("name", flat=True)), original_account_names
        )
        self.assertEqual(JournalEntry.objects.filter(team=dest_team).count(), original_entry_count)

    def test_an_unparseable_archive_touches_nothing(self):
        dest_team, dest_user, _h = build_db_fixture_team("Dst3", "dst3")
        original_count = Account.objects.filter(team=dest_team).count()
        with self.assertRaises(DocumentError):
            apply.apply_archive(dest_team, b"not a zip", user=dest_user)
        self.assertEqual(Account.objects.filter(team=dest_team).count(), original_count)


class SafetyArchiveTests(TestCase):
    def test_safety_archive_captures_the_pre_wipe_state(self):
        team, user, handles = build_db_fixture_team("Safety", "safety")
        safety_bytes = apply.build_safety_archive(team)

        # Now actually wipe and reimport something else entirely -- a team
        # built with a distinctly-named account the original never had.
        other_team, other_user = make_team("Other", "other-safety")
        group = AccountGroup.objects.create(team=other_team, name="Other Group", account_type="expense")
        Account.objects.create(team=other_team, name="Only In Other Team", account_group=group)
        other_bytes = export_bytes(other_team)
        apply.apply_archive(team, other_bytes, user=other_user)

        # Safety's own original accounts are gone; only Other's data remains.
        self.assertFalse(Account.objects.filter(team=team, name="Chequing").exists())
        self.assertTrue(Account.objects.filter(team=team, name="Only In Other Team").exists())

        # But the safety copy still describes the ORIGINAL team's books.
        tables = read.read_archive(safety_bytes)
        self.assertTrue(any(row["name"] == "Chequing" for row in tables.accounts))
        self.assertTrue(any(row["goal_name"] == "New Deck" for row in tables.accounts))


class ApplyErrorMessageTests(TestCase):
    def test_dangling_reference_refuses_before_writing_anything(self):
        team, user, _h = build_db_fixture_team("Dangling", "dangling")
        accounts, journal_rows, budget_rows = export.build_archive(team)
        journal_rows[0]["account_id"] = 999999
        bad_bytes = write.build_archive_bytes(
            accounts=accounts, journal=journal_rows, budget=budget_rows, source={}, checks={}, omitted={}
        )
        original_count = Account.objects.filter(team=team).count()
        with self.assertRaises(DocumentError):
            apply.apply_archive(team, bad_bytes, user=user)
        self.assertEqual(Account.objects.filter(team=team).count(), original_count)
