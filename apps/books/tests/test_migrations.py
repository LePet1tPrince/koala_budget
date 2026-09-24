"""
The migrations that moved every financial row from its team to a set of books:
M1's data migration (one "Personal" book per team) and M3's backfill (every row
gets its team's book), then M6 dropping `team`. Run forward over a populated
pre-books database, and back again.
"""

from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

# The last migration of each app before books existed.
PRE_BOOKS = [
    ("books", None),
    ("accounts", "0008_add_sort_order"),
    ("journal", "0002_reconciliation"),
    ("budget", "0003_alter_budget_options"),
    ("bank_feed", "0004_banktransaction_is_transfer_mirror"),
    ("plaid", "0003_plaiditem_last_synced_at"),
    ("reconciliation", "0001_initial"),
    ("monthly_review", "0002_existing_teams_have_no_reviews"),
    ("onboarding", "0002_existing_teams_are_already_onboarded"),
    ("portability", "0001_initial"),
    ("ynab_import", "0002_ynabimport_started_at"),
    ("audit", "0009_alter_auditevent_event_type"),
]


class BookMigrationTest(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        # ("app", None) means "none of this app's migrations" -- not a graph node.
        return executor.loader.project_state([t for t in targets if t[1] is not None]).apps

    def leaves(self):
        return MigrationExecutor(connection).loader.graph.leaf_nodes()

    def tearDown(self):
        # Leave the database fully migrated for the rest of the suite.
        self.migrate(self.leaves())

    def test_forward_creates_one_book_per_team_and_backfills_every_row(self):
        old = self.migrate(PRE_BOOKS)
        Team = old.get_model("teams", "Team")
        AccountGroup = old.get_model("accounts", "AccountGroup")
        Account = old.get_model("accounts", "Account")
        JournalEntry = old.get_model("journal", "JournalEntry")
        JournalLine = old.get_model("journal", "JournalLine")
        Budget = old.get_model("budget", "Budget")
        AuditEvent = old.get_model("audit", "AuditEvent")

        teams = [Team.objects.create(name=f"Team {i}", slug=f"team-{i}") for i in range(2)]
        for team in teams:
            group = AccountGroup.objects.create(team=team, name="Living", account_type="expense")
            cash_group = AccountGroup.objects.create(team=team, name="Cash", account_type="asset")
            food = Account.objects.create(team=team, name="Food", account_group=group)
            cash = Account.objects.create(team=team, name="Cash", account_group=cash_group)
            entry = JournalEntry.objects.create(team=team, entry_date="2026-01-05", description="Lunch")
            JournalLine.objects.create(team=team, journal_entry=entry, account=food, dr_amount=Decimal("9"))
            JournalLine.objects.create(team=team, journal_entry=entry, account=cash, cr_amount=Decimal("9"))
            Budget.objects.create(team=team, month="2026-01-01", category=food, budget_amount=Decimal("100"))
            AuditEvent.objects.create(team=team, event_type="user_login")
            AuditEvent.objects.create(team=team, event_type="bulk_edit")

        new = self.migrate(self.leaves())
        Book = new.get_model("books", "Book")
        for team in teams:
            books = list(Book.objects.filter(team_id=team.id))
            self.assertEqual([(b.name, b.slug) for b in books], [("Personal", "personal")])
            book = books[0]
            # Existing books keep today's behaviour: income budgeted before it lands.
            self.assertTrue(book.budget_future_income)
            for label, name in (
                ("accounts", "AccountGroup"),
                ("accounts", "Account"),
                ("journal", "JournalEntry"),
                ("journal", "JournalLine"),
                ("budget", "Budget"),
            ):
                model = new.get_model(label, name)
                self.assertTrue(model.objects.filter(book_id=book.id).exists(), name)
            events = new.get_model("audit", "AuditEvent").objects.filter(team_id=team.id)
            self.assertIsNone(events.get(event_type="user_login").book_id)
            self.assertEqual(events.get(event_type="bulk_edit").book_id, book.id)
        self.assertFalse(new.get_model("accounts", "Account").objects.filter(book__isnull=True).exists())

        # And back: `team` returns, filled from the book.
        old = self.migrate(PRE_BOOKS)
        for team in teams:
            Account = old.get_model("accounts", "Account")
            self.assertEqual(Account.objects.filter(team_id=team.id).count(), 2)
            self.assertEqual(old.get_model("journal", "JournalLine").objects.filter(team_id=team.id).count(), 2)
