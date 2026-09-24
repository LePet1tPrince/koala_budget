"""
Writing an import into a team's books.

The sample export is the fixture here too: 6,644 entries and 13,335 lines is the
volume the code has to work at, and a small synthetic export would not exercise the
batching, the budget map, or the reconciliation across 58 months.
"""

from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.models import Sum
from django.test import TestCase

from apps.accounts.models import Account, AccountGroup
from apps.budget.models import Budget, Goal, GoalAllocation
from apps.budget.services import BudgetService, NetWorthService
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser
from apps.ynab_import.services.apply import ApplyError, apply_plan, can_import
from apps.ynab_import.services.build import build, parse_choices
from apps.ynab_import.services.reconcile import reconcile

from .fixtures import sample_analysis, tiny_analysis


def make_team(name, slug, budget_future_income=True):
    team = Team.objects.create(name=name, slug=slug)
    # The imports under test budget income before it arrives (D1's back-fill).
    book = team.default_book
    book.budget_future_income = budget_future_income
    book.save()
    user = CustomUser.objects.create_user(username=f"{slug}-owner", password="pass")
    team.members.add(user, through_defaults={"role": ROLE_ADMIN})
    return team, user


class TinyApplyTest(TestCase):
    """The rules, at a size where every row can be asserted about individually."""

    def setUp(self):
        self.team, self.user = make_team("Tiny", "tiny")
        self.book = self.team.default_book
        self.analysis = tiny_analysis()
        self.plan = build(self.analysis)
        self.result = apply_plan(self.book, self.plan, user=self.user)

    def account(self, name):
        return Account.objects.get(book=self.book, name=name)

    def test_the_chart_of_accounts(self):
        types = {
            (account.name, account.account_group.account_type)
            for account in Account.objects.filter(book=self.book).select_related("account_group")
        }
        self.assertIn(("Chequing", "asset"), types)
        self.assertIn(("Visa", "liability"), types)
        self.assertIn(("Groceries", "expense"), types)
        self.assertIn(("Employer", "income"), types)
        self.assertIn(("Reconciliation Adjustments", "goal"), types)

    def test_every_entry_is_posted_and_balanced(self):
        entries = JournalEntry.objects.filter(book=self.book)
        self.assertTrue(all(entry.status == JournalEntry.STATUS_POSTED for entry in entries))
        self.assertTrue(all(entry.is_balanced for entry in entries))
        self.assertEqual(
            {entry.source for entry in entries.exclude(description__startswith="Opening balance")},
            {JournalEntry.SOURCE_IMPORT},
        )

    def test_account_balances_match_the_export(self):
        self.assertEqual(self.account("Chequing").balance, Decimal("2120.00"))
        self.assertEqual(self.account("Savings").balance, Decimal("301.25"))
        # A liability's balance is dr - cr like everything else, so what is owed
        # reads as a negative.
        self.assertEqual(self.account("Visa").balance, Decimal("-130.00"))

    def test_net_worth_is_what_the_user_actually_has(self):
        net_worth = NetWorthService(self.book).get_net_worth(date(2024, 3, 1))
        self.assertEqual(net_worth, Decimal("2291.25"))

    def test_reconciliation_flags_land_on_the_bank_side_only(self):
        entry = JournalEntry.objects.get(book=self.book, description="Weekly shop")
        flags = {line.account.name: line.is_reconciled for line in entry.lines.all()}
        self.assertTrue(flags["Chequing"])
        self.assertFalse(flags["Groceries"])

    def test_lines_are_linked_to_the_budget_for_their_month(self):
        # `bulk_create` skips `JournalLine.save()`, so this link is made by the
        # import rather than by the model -- and a NULL here is invisible until
        # something reads it.
        line = JournalLine.objects.get(
            book=self.book,
            account=self.account("Groceries"),
            journal_entry__description="Weekly shop",
        )
        self.assertIsNotNone(line.budget_id)
        self.assertEqual(line.budget.month, date(2024, 1, 1))
        self.assertEqual(line.budget.budget_amount, Decimal("100.00"))

    def test_goals_arrive_funded_but_not_complete(self):
        goal = Goal.objects.get(book=self.book, name="House")
        self.assertEqual(goal.target_amount, Decimal("300.00"))
        self.assertFalse(goal.is_complete)
        self.assertIn(goal, Goal.objects.active())
        # The backing equity account the rest of the app expects a goal to have.
        self.assertIsNotNone(goal.account_id)
        self.assertEqual(
            GoalAllocation.objects.get(book=self.book, goal=goal, month=date(2024, 1, 1)).amount,
            Decimal("300.00"),
        )

    def test_opening_balances_are_dated_when_the_account_opened(self):
        opening = JournalEntry.objects.get(book=self.book, description="Opening balance — Chequing")
        self.assertEqual(opening.entry_date, date(2024, 1, 1))
        lines = {line.account.name: line for line in opening.lines.all()}
        self.assertEqual(lines["Chequing"].dr_amount, Decimal("500.00"))
        self.assertEqual(lines["Reconciliation Adjustments"].cr_amount, Decimal("500.00"))

    def test_a_card_balance_opens_as_money_owed(self):
        opening = JournalEntry.objects.get(book=self.book, description="Opening balance — Visa")
        lines = {line.account.name: line for line in opening.lines.all()}
        self.assertEqual(lines["Visa"].cr_amount, Decimal("120.00"))

    def test_budget_available_follows_ynab(self):
        service = BudgetService(self.book)
        # Groceries: 100 budgeted, 86 spent, so 14 rolls into February on top of 50.
        self.assertEqual(service.available(self.account("Groceries"), date(2024, 1, 1)), Decimal("14.00"))
        self.assertEqual(service.available(self.account("Groceries"), date(2024, 2, 1)), Decimal("64.00"))
        # Fun overspent by 4 in January. YNAB covered it out of Ready to Assign and
        # showed 20 in February; the top-up is what reproduces that under KB's
        # carry-the-negative-forward rule.
        self.assertEqual(service.available(self.account("Fun"), date(2024, 1, 1)), Decimal("-4.00"))
        self.assertEqual(service.available(self.account("Fun"), date(2024, 2, 1)), Decimal("20.00"))

    def test_income_available_starts_at_zero(self):
        service = BudgetService(self.book)
        self.assertEqual(service.available(self.account("Employer"), date(2024, 1, 1)), Decimal("0.00"))
        self.assertEqual(service.available(self.account("Employer"), date(2024, 2, 1)), Decimal("0.00"))

    def test_no_bank_feed_rows_are_created(self):
        from apps.bank_feed.models import BankTransaction

        # The register is already categorised. Staging it in the feed would present
        # the user with thousands of questions they have already answered.
        self.assertEqual(BankTransaction.objects.filter(book=self.book).count(), 0)

    def test_a_second_import_is_refused(self):
        self.assertFalse(can_import(self.book))
        with self.assertRaisesMessage(ApplyError, "already has transactions"):
            apply_plan(self.book, build(tiny_analysis()), user=self.user)

    def test_result_counts(self):
        self.assertEqual(self.result.entries, len(self.plan.entries))
        self.assertEqual(self.result.openings, 2)
        self.assertEqual(self.result.goals, 1)


class SkippedAccountApplyTest(TestCase):
    def test_a_dropped_account_is_not_created_and_its_rows_do_not_appear(self):
        team, user = make_team("Dropped", "dropped")
        book = team.default_book
        analysis = tiny_analysis()
        plan = build(analysis, parse_choices(analysis, {"accounts": {"Savings": {"skip": True}}}))
        apply_plan(book, plan, user=user)

        self.assertFalse(Account.objects.filter(book=book, name="Savings").exists())
        self.assertTrue(all(entry.is_balanced for entry in JournalEntry.objects.filter(book=book)))


class ExistingChartApplyTest(TestCase):
    def test_an_import_over_a_stock_chart_reuses_its_groups(self):
        # A user who clicked through onboarding first has accounts but no
        # transactions, and `AccountGroup` is unique on name per team.
        team, user = make_team("Stocked", "stocked")
        book = team.default_book
        from apps.teams.services.template_budget import PERSONAL_BUDGET_TEMPLATE
        from apps.teams.services.template_engine import apply_template

        apply_template(book=book, template=PERSONAL_BUDGET_TEMPLATE)
        before = AccountGroup.objects.filter(book=book).count()

        analysis = tiny_analysis()
        apply_plan(book, build(analysis), user=user)

        self.assertEqual(AccountGroup.objects.filter(book=book, name="Bank Accounts").count(), 1)
        self.assertGreater(AccountGroup.objects.filter(book=book).count(), before - 1)
        self.assertTrue(Account.objects.filter(book=book, name="Chequing").exists())


class SampleApplyTest(TestCase):
    """The real export, written to a real team."""

    @classmethod
    def setUpTestData(cls):
        cls.team, cls.user = make_team("Sample", "sample")
        cls.book = cls.team.default_book
        cls.analysis = sample_analysis()
        cls.plan = build(cls.analysis)
        cls.result = apply_plan(cls.book, cls.plan, user=cls.user)
        # ~13,000 lines just arrived inside the test transaction, while the
        # planner's statistics (autoanalyzed after earlier tests rolled back)
        # say these tables are empty. Left alone, it picks nested loops and a
        # single net-worth aggregate runs for minutes; a real import commits and
        # is autoanalyzed, so this is a test-only concern.
        with connection.cursor() as cursor:
            cursor.execute(
                "ANALYZE journal_journalline, journal_journalentry, accounts_account, bank_feed_banktransaction"
            )

    def test_everything_was_written(self):
        # 6,623 transactions plus 13 opening balances: 8 of the export's 21
        # `Starting Balance` rows are for accounts that were added empty, and an
        # entry with nothing on either side is not a journal entry.
        self.assertEqual(self.plan.stats["zero_openings"], 8)
        self.assertEqual(JournalEntry.objects.filter(book=self.book).count(), 6623 + 13)
        self.assertEqual(JournalLine.objects.filter(book=self.book).count(), 13335 + 13 * 2)
        self.assertEqual(Account.objects.filter(book=self.book).count(), 104 + 3)  # + one per goal
        self.assertEqual(Budget.objects.filter(book=self.book).count(), 1872)
        self.assertEqual(Goal.objects.filter(book=self.book).count(), 3)

    def test_every_entry_balances(self):
        totals = (
            JournalLine.objects.filter(book=self.book)
            .values("journal_entry_id")
            .annotate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
        )
        self.assertEqual([row for row in totals if row["dr"] != row["cr"]], [])

    def test_account_balances_match_the_export(self):
        balances = {
            account.name: account.balance
            for account in Account.objects.filter(book=self.book).select_related("account_group")
        }
        for facts in self.analysis.accounts:
            self.assertEqual(balances[facts.name], facts.closing_balance, facts.name)

    def test_net_worth_matches_the_preview(self):
        net_worth = NetWorthService(self.book).get_net_worth(date(2026, 10, 1))
        self.assertEqual(str(net_worth), self.plan.stats["net_worth"])

    def test_reconciliation_passes(self):
        result = reconcile(self.analysis, self.plan)
        self.assertTrue(result.passed, [c.samples[:2] for c in result.checks if not c.passed])

    def test_budget_available_matches_ynab_for_a_sampled_category(self):
        # `BudgetService.available()` recurses a month at a time with a query each,
        # so this checks the service itself against YNAB on a couple of categories
        # rather than all 45 -- the exhaustive comparison is the pure replay in
        # `reconcile.check_available`.
        service = BudgetService(self.book)
        month = date(2026, 8, 1)
        for group, name in (("Monthly", "Groceries"), ("Tax Deductible", "Medical")):
            account = Account.objects.get(book=self.book, name=name, account_group__account_type="expense")
            expected = next(
                row.available for row in self.analysis.plan if row.key == (group, name) and row.month == month
            )
            self.assertEqual(service.available(account, month), expected, name)

    def test_transactions_carry_their_payees(self):
        # A transfer names an account rather than a payee, and an opening balance is
        # not a transaction with anyone -- so neither gets one, and everything else
        # does.
        self.assertGreater(JournalEntry.objects.filter(book=self.book, payee__isnull=False).count(), 5000)
        self.assertEqual(
            JournalEntry.objects.filter(
                book=self.book, payee__isnull=False, description__startswith="Opening balance"
            ).count(),
            0,
        )

    def test_reconciled_lines_are_the_bank_side(self):
        reconciled = JournalLine.objects.filter(book=self.book, is_reconciled=True).select_related(
            "account__account_group"
        )
        self.assertTrue(
            all(line.account.account_group.account_type in ("asset", "liability") for line in reconciled[:200])
        )
