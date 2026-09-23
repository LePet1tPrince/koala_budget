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
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.splits import is_split
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
        reconciliations=export.build_reconciliation_rows(team),
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


class BlankFeedDescriptionTests(TestCase):
    """
    A feed row whose description is empty must survive the whole path.

    `BankTransaction.description` is NOT NULL but `""` is an ordinary value:
    a CSV whose description column was blank, a Plaid row that carried none,
    a transfer mirror copied from a primary that had none. Until this was
    fixed the exporter wrote that as a blank cell and the importer then
    refused its own file --

        journal.csv, row N: entry_id X has feed_source set but is missing
        feed_description.

    -- which is how it was found, on real books rather than by a test.
    """

    @classmethod
    def setUpTestData(cls):
        cls.source_team, cls.source_user = make_team("Blank Desc Source", "blank-desc-source")
        cls.dest_team, cls.dest_user = make_team("Blank Desc Dest", "blank-desc-dest")

        asset_group = AccountGroup.objects.create(team=cls.source_team, name="Cash", account_type="asset")
        expense_group = AccountGroup.objects.create(team=cls.source_team, name="Spending", account_type="expense")
        cls.chequing = Account.objects.create(
            team=cls.source_team, name="Chequing", account_group=asset_group, has_feed=True
        )
        cls.groceries = Account.objects.create(team=cls.source_team, name="Groceries", account_group=expense_group)

        # A categorised feed row with no description at all.
        entry = JournalEntry.objects.create(
            team=cls.source_team,
            entry_date=date(2026, 3, 1),
            description="Nameless purchase",
            source=JournalEntry.SOURCE_BANK_MATCH,
            status=JournalEntry.STATUS_POSTED,
        )
        JournalLine.objects.create(
            team=cls.source_team, journal_entry=entry, account=cls.groceries, dr_amount=Decimal("41.00")
        )
        JournalLine.objects.create(
            team=cls.source_team, journal_entry=entry, account=cls.chequing, cr_amount=Decimal("41.00")
        )
        BankTransaction.objects.create(
            team=cls.source_team,
            account=cls.chequing,
            journal_entry=entry,
            amount=Decimal("41.00"),
            posted_date=date(2026, 3, 1),
            description="",  # the whole point
            source=BankTransaction.SOURCE_CSV,
        )

        # An *uncategorized* feed row with no description either -- the other
        # branch of `_feed_columns`, which travels with a blank entry_id.
        BankTransaction.objects.create(
            team=cls.source_team,
            account=cls.chequing,
            journal_entry=None,
            amount=Decimal("9.99"),
            posted_date=date(2026, 3, 2),
            description="",
            source=BankTransaction.SOURCE_PLAID,
        )

    def test_the_export_can_be_read_back(self):
        read.read_archive(export_bytes(self.source_team))  # must not raise

    def test_importing_it_writes_both_rows_with_empty_descriptions(self):
        apply.apply_archive(self.dest_team, export_bytes(self.source_team), user=self.dest_user)
        rows = BankTransaction.objects.filter(team=self.dest_team).order_by("posted_date")
        self.assertEqual([r.description for r in rows], ["", ""])

    def test_description_is_an_empty_string_not_none_after_import(self):
        # The column cannot hold None; writing one would be an IntegrityError.
        apply.apply_archive(self.dest_team, export_bytes(self.source_team), user=self.dest_user)
        for row in BankTransaction.objects.filter(team=self.dest_team):
            self.assertIsNotNone(row.description)

    def test_the_uncategorized_row_survives_as_uncategorized(self):
        apply.apply_archive(self.dest_team, export_bytes(self.source_team), user=self.dest_user)
        uncategorized = BankTransaction.objects.filter(team=self.dest_team, journal_entry__isnull=True)
        self.assertEqual(uncategorized.count(), 1)
        self.assertEqual(uncategorized.first().amount, Decimal("9.99"))


class StatementRoundTripTests(TestCase):
    """
    Statements travel (format version 2): a finished one arrives intact, with
    its lines still pointing at it, and a draft arrives with its ticks.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.reconciliation.services import candidates, session
        from apps.reconciliation.services.signs import to_statement

        cls.source_team, cls.source_user, _ = build_db_fixture_team("Stmt Src", "stmt-src")
        cls.dest_team, cls.dest_user = make_team("Stmt Dest", "stmt-dest")
        chequing = Account.objects.get(team=cls.source_team, name="Chequing")
        card = Account.objects.get(team=cls.source_team, name="Credit Card")

        draft = session.start(chequing, date(2099, 1, 31), Decimal("0"), cls.source_user)
        session.tick_through(draft, date(2099, 1, 31))
        current = candidates.summary(draft)
        session.update_statement(
            draft, statement_balance=to_statement(chequing, current.opening + current.ticked_total)
        )
        cls.finished = session.finish(draft, cls.source_user)
        cls.finished_lines = cls.finished.lines.count()

        card_draft = session.start(card, date(2099, 1, 31), Decimal("1.00"), cls.source_user)
        cls.card_ticks = len(session.tick_through(card_draft, date(2099, 1, 31)))

    def setUp(self):
        from apps.reconciliation.models import Reconciliation

        self.result = apply.apply_archive(self.dest_team, export_bytes(self.source_team), user=self.dest_user)
        self.statements = {r.account.name: r for r in Reconciliation.objects.filter(team=self.dest_team)}

    def test_both_statements_arrive(self):
        self.assertEqual(self.result.reconciliations, 2)
        self.assertEqual(set(self.statements), {"Chequing", "Credit Card"})

    def test_the_finished_statement_is_intact_with_its_lines(self):
        from apps.reconciliation.services.integrity import is_intact

        rec = self.statements["Chequing"]
        self.assertEqual(rec.status, "completed")
        self.assertEqual(rec.lines.count(), self.finished_lines)
        self.assertTrue(is_intact(rec))

    def test_the_draft_keeps_its_ticks(self):
        rec = self.statements["Credit Card"]
        self.assertEqual(rec.status, "draft")
        self.assertEqual(rec.lines.filter(is_reconciled=False).count(), self.card_ticks)


class SplitRoundTripTests(TestCase):
    """
    A split must come out of an import as the same split it went in as.

    Splits are one `JournalEntry` with a bank line and several category legs
    (`apps/bank_feed/services/splits.py`). Nothing in this format treats them
    specially -- journal.csv is one row per line, so three lines are three
    rows -- but "nothing treats them specially" is a claim worth testing
    rather than assuming: five places in the feed assumed two lines and were
    silently wrong until splits shipped.
    """

    @classmethod
    def setUpTestData(cls):
        cls.source_team, cls.source_user, cls.handles = build_db_fixture_team("Split Src", "split-src")
        cls.dest_team, cls.dest_user = make_team("Split Dest", "split-dest")

    def setUp(self):
        apply.apply_archive(self.dest_team, export_bytes(self.source_team), user=self.dest_user)
        self.split = (
            JournalEntry.objects.filter(team=self.dest_team, description="Costco run").prefetch_related("lines").get()
        )

    def test_the_split_arrives_with_all_three_lines(self):
        self.assertEqual(self.split.lines.count(), 3)

    def test_the_split_balances_after_import(self):
        lines = list(self.split.lines.all())
        self.assertEqual(sum(line.dr_amount for line in lines), sum(line.cr_amount for line in lines))

    def test_the_legs_keep_their_opposite_signs(self):
        by_account = {line.account.name: (line.dr_amount, line.cr_amount) for line in self.split.lines.all()}
        self.assertEqual(by_account["Groceries"], (Decimal("100.00"), Decimal("0.00")))
        self.assertEqual(by_account["Misc"], (Decimal("0.00"), Decimal("20.00")))
        self.assertEqual(by_account["Chequing"], (Decimal("0.00"), Decimal("80.00")))

    def test_the_bank_line_keeps_its_cleared_flag(self):
        # `apply_splits` updates the bank line in place precisely so its
        # reconciliation state is not lost; an import must not lose it either.
        bank_line = self.split.lines.get(account__name="Chequing")
        self.assertTrue(bank_line.is_cleared)

    def test_one_feed_row_for_the_split_not_one_per_leg(self):
        feed = BankTransaction.objects.filter(team=self.dest_team, journal_entry=self.split)
        self.assertEqual(feed.count(), 1)
        self.assertEqual(feed.get().amount, Decimal("80.00"))
        self.assertEqual(feed.get().account.name, "Chequing")

    def test_the_split_is_still_recognised_as_a_split(self):
        self.assertTrue(is_split(self.split))

    def test_no_mirror_was_invented_for_the_split(self):
        # The import never calls `sync_transfer`, so a split cannot pick up the
        # phantom mirror that re-deriving the relationship would create.
        mirrors = BankTransaction.objects.filter(team=self.dest_team, journal_entry=self.split, is_transfer_mirror=True)
        self.assertEqual(mirrors.count(), 0)


class UnplaceableFeedRowTests(TestCase):
    """
    Every `BankTransaction` must reach the file, including the ones no journal
    line can carry.

    A feed row rides on the line whose account it shares. Two real states
    leave a row with no line to ride on -- its entry has no line on its own
    account, or another row already claimed that line -- and both used to make
    the row vanish from journal.csv while `build_checks` kept counting it from
    the database. The import's own integrity gate caught the discrepancy and
    refused the file with "feed_counts did not match after writing", which is
    the gate working correctly and the export being wrong: it had produced a
    file that could not pass. Reported from real books.

    Such a row now travels as a standalone feed row, arriving as one to
    review. That loses its entry link and nothing else -- the entry, its lines
    and every balance ride on the line rows regardless -- and the count is
    disclosed in the manifest's `omitted` block.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("Unplaceable", "unplaceable")
        cls.dest, cls.dest_user = make_team("Unplaceable Dest", "unplaceable-dest")

        asset = AccountGroup.objects.create(team=cls.team, name="Cash", account_type="asset")
        expense = AccountGroup.objects.create(team=cls.team, name="Spend", account_type="expense")
        cls.chequing = Account.objects.create(team=cls.team, name="Chequing", account_group=asset, has_feed=True)
        cls.savings = Account.objects.create(team=cls.team, name="Savings", account_group=asset, has_feed=True)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=expense)

        cls.entry = JournalEntry.objects.create(
            team=cls.team,
            entry_date=date(2026, 4, 1),
            description="Thing",
            source=JournalEntry.SOURCE_BANK_MATCH,
            status=JournalEntry.STATUS_POSTED,
        )
        JournalLine.objects.create(
            team=cls.team, journal_entry=cls.entry, account=cls.groceries, dr_amount=Decimal("10.00")
        )
        JournalLine.objects.create(
            team=cls.team, journal_entry=cls.entry, account=cls.chequing, cr_amount=Decimal("10.00")
        )

        # The row that places normally.
        cls.placed = BankTransaction.objects.create(
            team=cls.team,
            account=cls.chequing,
            journal_entry=cls.entry,
            amount=Decimal("10.00"),
            posted_date=date(2026, 4, 1),
            description="PLACED",
            source=BankTransaction.SOURCE_CSV,
        )
        # Collision: a second row claiming the same line.
        cls.collided = BankTransaction.objects.create(
            team=cls.team,
            account=cls.chequing,
            journal_entry=cls.entry,
            amount=Decimal("10.00"),
            posted_date=date(2026, 4, 1),
            description="COLLIDED",
            source=BankTransaction.SOURCE_CSV,
        )
        # Orphan: an entry with no line on this row's own account.
        cls.orphan = BankTransaction.objects.create(
            team=cls.team,
            account=cls.savings,
            journal_entry=cls.entry,
            amount=Decimal("10.00"),
            posted_date=date(2026, 4, 1),
            description="ORPHAN",
            source=BankTransaction.SOURCE_CSV,
        )

    def test_every_feed_row_reaches_the_file(self):
        _accounts, journal, _budget = export.build_archive(self.team)
        emitted = [r for r in journal if r["feed_source"] is not None]
        self.assertEqual(len(emitted), BankTransaction.objects.filter(team=self.team).count())
        self.assertEqual({r["feed_description"] for r in emitted}, {"PLACED", "COLLIDED", "ORPHAN"})

    def test_the_lowest_id_keeps_the_line_so_exports_are_stable(self):
        _accounts, journal, _budget = export.build_archive(self.team)
        on_a_line = [r for r in journal if r["feed_source"] is not None and r["entry_id"] is not None]
        self.assertEqual(len(on_a_line), 1)
        self.assertEqual(on_a_line[0]["feed_description"], "PLACED")

    def test_unplaceable_rows_travel_as_rows_to_review(self):
        _accounts, journal, _budget = export.build_archive(self.team)
        standalone = [r for r in journal if r["status"] == UNCATEGORIZED_STATUS]
        self.assertEqual({r["feed_description"] for r in standalone}, {"COLLIDED", "ORPHAN"})

    def test_the_manifest_counts_them_as_uncategorized(self):
        # Or the import's own gate would refuse the file it just produced.
        checks = export.build_checks(self.team)
        self.assertEqual(checks["feed_counts"]["total"], 3)
        self.assertEqual(checks["feed_counts"]["uncategorized"], 2)

    def test_the_repair_is_disclosed_not_silent(self):
        self.assertEqual(export.build_omitted(self.team)["unlinked_feed_rows"], 2)

    def test_the_import_verifies(self):
        apply.apply_archive(self.dest, export_bytes(self.team), user=self.dest_user)  # must not raise

    def test_all_three_rows_arrive(self):
        apply.apply_archive(self.dest, export_bytes(self.team), user=self.dest_user)
        arrived = BankTransaction.objects.filter(team=self.dest)
        self.assertEqual(arrived.count(), 3)
        self.assertEqual(arrived.filter(journal_entry__isnull=True).count(), 2)

    def test_the_entry_and_its_balances_are_untouched_by_the_repair(self):
        apply.apply_archive(self.dest, export_bytes(self.team), user=self.dest_user)
        entry = JournalEntry.objects.get(team=self.dest, description="Thing")
        lines = list(entry.lines.all())
        self.assertEqual(len(lines), 2)
        self.assertEqual(sum(line.dr_amount for line in lines), Decimal("10.00"))
        self.assertEqual(sum(line.cr_amount for line in lines), Decimal("10.00"))

    def test_a_healthy_team_reports_no_repair(self):
        healthy, _user = make_team("Healthy", "healthy-feed")
        self.assertEqual(export.build_omitted(healthy)["unlinked_feed_rows"], 0)


class FeedRowRidesOneLineTests(TestCase):
    """
    An entry may hold more than one line on the same account, and its feed row
    must still travel exactly once.

    The commonest way that shape arises is a split with a leg pointing back at
    the bank account -- cash back at the till, or a partial transfer to
    yourself. The feed lookup is keyed `(entry_id, account_id)`, so consulting
    it once per line handed the same `BankTransaction` to both rows and the
    import wrote it twice: one row in the database against two in the file,
    which `_verify` caught as "feed_counts did not match after writing" only
    after the destination had already been wiped and rolled back.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("Two Lines", "two-lines")
        cls.dest, cls.dest_user = make_team("Two Lines Dest", "two-lines-dest")

        cash = AccountGroup.objects.create(team=cls.team, name="Cash", account_type="asset")
        spend = AccountGroup.objects.create(team=cls.team, name="Spend", account_type="expense")
        cls.chequing = Account.objects.create(team=cls.team, name="Chequing", account_group=cash, has_feed=True)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=spend)

        cls.entry = JournalEntry.objects.create(
            team=cls.team,
            entry_date=date(2026, 5, 2),
            description="Groceries with cash back",
            source=JournalEntry.SOURCE_BANK_MATCH,
            status=JournalEntry.STATUS_POSTED,
        )
        JournalLine.objects.create(
            team=cls.team, journal_entry=cls.entry, account=cls.groceries, dr_amount=Decimal("70.00")
        )
        # The second line on the bank account -- the leg that made the row
        # ride twice.
        JournalLine.objects.create(
            team=cls.team, journal_entry=cls.entry, account=cls.chequing, dr_amount=Decimal("30.00")
        )
        JournalLine.objects.create(
            team=cls.team, journal_entry=cls.entry, account=cls.chequing, cr_amount=Decimal("100.00")
        )
        BankTransaction.objects.create(
            team=cls.team,
            account=cls.chequing,
            journal_entry=cls.entry,
            amount=Decimal("100.00"),
            posted_date=date(2026, 5, 2),
            description="CASH BACK",
            source=BankTransaction.SOURCE_CSV,
        )

    def test_the_feed_row_is_emitted_once_not_once_per_line(self):
        _accounts, journal, _budget = export.build_archive(self.team)
        carrying = [r for r in journal if r["feed_source"] is not None]
        self.assertEqual(len(carrying), 1)

    def test_all_three_lines_still_travel(self):
        _accounts, journal, _budget = export.build_archive(self.team)
        lines = [r for r in journal if r["entry_id"] is not None]
        self.assertEqual(len(lines), 3)

    def test_the_row_rides_the_lowest_id_line_of_its_account(self):
        # Stable across exports of the same team, rather than query-order
        # dependent -- the dr 30.00 leg is written before the cr 100.00 one.
        _accounts, journal, _budget = export.build_archive(self.team)
        carrying = next(r for r in journal if r["feed_source"] is not None)
        self.assertEqual(carrying["dr_amount"], Decimal("30.00"))

    def test_the_import_verifies_and_writes_one_feed_row(self):
        apply.apply_archive(self.dest, export_bytes(self.team), user=self.dest_user)
        self.assertEqual(BankTransaction.objects.filter(team=self.dest).count(), 1)

    def test_the_entry_arrives_intact_and_balanced(self):
        apply.apply_archive(self.dest, export_bytes(self.team), user=self.dest_user)
        entry = JournalEntry.objects.get(team=self.dest, description="Groceries with cash back")
        lines = list(entry.lines.all())
        self.assertEqual(len(lines), 3)
        self.assertEqual(sum(line.dr_amount for line in lines), sum(line.cr_amount for line in lines))


class ExportInvariantGuardTests(TestCase):
    """
    The export refuses to write a file whose feed-row count disagrees with the
    database, rather than leaving the importer to discover it after the wipe.
    """

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user, _handles = build_db_fixture_team("Guard", "guard-team")

    def test_a_healthy_team_exports(self):
        export.build_archive(self.team)  # must not raise

    def test_a_mismatch_is_refused_before_anything_is_written(self):
        # Simulate a future regression in the row-building walk: a feed row
        # that never reaches the file. The guard has to notice, whatever the
        # cause, since its whole point is catching the case nobody predicted.
        real = export._build_journal_rows

        def dropping_one(team):
            rows = real(team)
            for index, row in enumerate(rows):
                if row["feed_source"] is not None:
                    return rows[:index] + rows[index + 1 :]
            return rows

        export._build_journal_rows = dropping_one
        try:
            with self.assertRaises(export.ExportError) as ctx:
                export.build_archive(self.team)
        finally:
            export._build_journal_rows = real
        self.assertIn("bank feed row", str(ctx.exception))
