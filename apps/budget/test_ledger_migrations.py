"""
The cut-over to the ledger (budget 0011, journal 0008, budget 0012): forward over
a database with budget rows, then back, which must give the rows back.
"""

from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("budget", "0010_budget_entries_backfill"), ("journal", "0007_one_budget_entry_per_month")]


class LedgerCutOverMigrationTest(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def leaves(self):
        return MigrationExecutor(connection).loader.graph.leaf_nodes()

    def tearDown(self):
        self.migrate(self.leaves())

    def make_book(self, apps):
        Team = apps.get_model("teams", "Team")
        Book = apps.get_model("books", "Book")
        AccountGroup = apps.get_model("accounts", "AccountGroup")
        Account = apps.get_model("accounts", "Account")
        Goal = apps.get_model("budget", "Goal")
        team = Team.objects.create(name="Cut-over", slug="cut-over")
        book = Book.objects.create(team=team, name="Personal", slug="personal")
        budget_group = AccountGroup.objects.create(book=book, name="Budget", account_type="budget", is_system=True)
        Account.objects.create(book=book, name="Unassigned", account_group=budget_group, is_system=True)

        def category(name, account_type):
            group = AccountGroup.objects.create(book=book, name=f"{name} group", account_type=account_type)
            account = Account.objects.create(book=book, name=name, account_group=group)
            Account.objects.create(
                book=book, name=f"{name} (budget)", account_group=budget_group, is_system=True, paired_account=account
            )
            return account

        food = category("Food", "expense")
        pay = category("Pay", "income")
        cash_group = AccountGroup.objects.create(book=book, name="Cash", account_type="asset")
        cash = Account.objects.create(book=book, name="Cash", account_group=cash_group)
        trip_account = category("Goal: Trip", "goal")
        trip = Goal.objects.create(book=book, name="Trip", target_amount=Decimal("1000"), account=trip_account)
        return book, food, pay, cash, trip

    def test_forward_then_back(self):
        old = self.migrate(BEFORE)
        book, food, pay, cash, trip = self.make_book(old)
        Budget = old.get_model("budget", "Budget")
        GoalAllocation = old.get_model("budget", "GoalAllocation")
        JournalEntry = old.get_model("journal", "JournalEntry")
        JournalLine = old.get_model("journal", "JournalLine")
        Budget.objects.create(book=book, category=food, month="2026-03-01", budget_amount=Decimal("400"))
        Budget.objects.create(book=book, category=pay, month="2026-03-01", budget_amount=Decimal("3000"))
        Budget.objects.create(book=book, category=food, month="2026-04-01", budget_amount=Decimal("0"))
        GoalAllocation.objects.create(book=book, goal=trip, month="2026-03-01", amount=Decimal("250"))
        lunch = JournalEntry.objects.create(book=book, entry_date="2026-03-09", description="Lunch", status="posted")
        JournalLine.objects.create(book=book, journal_entry=lunch, account=food, dr_amount=Decimal("12"))
        JournalLine.objects.create(book=book, journal_entry=lunch, account=cash, cr_amount=Decimal("12"))

        new = self.migrate(self.leaves())
        lines = {
            line.account.paired_account_id: line.cr_amount - line.dr_amount
            for line in new.get_model("journal", "JournalLine")
            .objects.filter(journal_entry__source="budget", account__paired_account__isnull=False)
            .select_related("account")
        }
        self.assertEqual(lines, {food.pk: Decimal("400"), pay.pk: Decimal("-3000"), trip.account_id: Decimal("250")})
        with self.assertRaises(LookupError):
            new.get_model("budget", "Budget")

        old = self.migrate(BEFORE)
        Budget = old.get_model("budget", "Budget")
        GoalAllocation = old.get_model("budget", "GoalAllocation")
        rows = {(b.category_id, str(b.month)): b.budget_amount for b in Budget.objects.all()}
        # Back, less the zero row: it had no line to come back from.
        self.assertEqual(rows, {(food.pk, "2026-03-01"): Decimal("400"), (pay.pk, "2026-03-01"): Decimal("3000")})
        self.assertEqual(
            [(a.goal_id, str(a.month), a.amount) for a in GoalAllocation.objects.all()],
            [(trip.pk, "2026-03-01", Decimal("250"))],
        )
        JournalLine = old.get_model("journal", "JournalLine")
        relinked = JournalLine.objects.get(account_id=food.pk, journal_entry__source="manual")
        self.assertEqual(relinked.budget.budget_amount, Decimal("400"))

    def test_forward_refuses_allocation_notes(self):
        old = self.migrate(BEFORE)
        book, _food, _pay, _cash, trip = self.make_book(old)
        GoalAllocation = old.get_model("budget", "GoalAllocation")
        allocation = GoalAllocation.objects.create(
            book=book, goal=trip, month="2026-03-01", amount=Decimal("250"), notes="birthday money"
        )
        with self.assertRaisesMessage(RuntimeError, "carry notes"):
            self.migrate(self.leaves())
        GoalAllocation.objects.filter(pk=allocation.pk).update(notes="")
