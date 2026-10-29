"""The budget kept in the ledger (apps/budget/ledger.py): one budget entry per month."""

import json
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Account, AccountGroup
from apps.books.context import current_book
from apps.budget.ledger import set_budget, set_goal_allocation
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.services.gates import book_facts, can_set_opening_balances
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser
from apps.ynab_import.services.apply import can_import

from . import ledger
from .buckets import unassigned_account
from .models import Goal
from .services import GoalService

AUG = date(2026, 8, 1)
SEPT = date(2026, 9, 1)
OCT = date(2026, 10, 1)


def bucket_of(account):
    return Account.objects.get(paired_account=account)


def lines_of(entry):
    """`{account_id: credit amount}` of an entry's lines."""
    return {line.account_id: line.cr_amount - line.dr_amount for line in entry.lines.all()}


class LedgerFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Ledger", slug="ledger")
        cls.book = cls.team.default_book
        cls.book.budget_future_income = True
        cls.book.save()
        cls.user = CustomUser.objects.create_user(username="ledger@example.com", email="ledger@example.com")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        asset = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        equity = AccountGroup.objects.create(book=cls.book, name="Opening", account_type="goal")
        income = AccountGroup.objects.create(book=cls.book, name="Work", account_type="income")
        expense = AccountGroup.objects.create(book=cls.book, name="Living", account_type="expense")
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=asset)
        cls.opening = Account.objects.create(book=cls.book, name="Opening Balance", account_group=equity)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=income)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=expense)
        cls.fun = Account.objects.create(book=cls.book, name="Fun", account_group=expense)
        cls.goal = Goal.objects.create(book=cls.book, name="House", target_amount=Decimal("50000"))

        cls.post(date(2026, 8, 2), cls.checking, cls.opening, "20000")
        set_budget(cls.book, cls.groceries, AUG, Decimal("3500"))
        set_budget(cls.book, cls.groceries, SEPT, Decimal("4000"))
        set_budget(cls.book, cls.salary, SEPT, Decimal("5000"))
        set_goal_allocation(cls.book, cls.goal, AUG, Decimal("15000"))
        set_goal_allocation(cls.book, cls.goal, SEPT, Decimal("1000"))

    @classmethod
    def post(cls, day, debit, credit, amount):
        entry = JournalEntry.objects.create(book=cls.book, entry_date=day, description="entry", status="posted")
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=debit, dr_amount=Decimal(amount))
        JournalLine.objects.create(book=cls.book, journal_entry=entry, account=credit, cr_amount=Decimal(amount))
        return entry

    def assert_sound(self, through=OCT):
        result = ledger.check_book(self.book, through=through)
        self.assertEqual(result.entry_problems, [])
        self.assertEqual(result.unassigned_mismatches, [])
        self.assertGreater(result.months_checked, 0)


class BudgetEntryTest(LedgerFixture):
    def test_each_month_is_one_entry(self):
        aug, sept = ledger.budget_entry(self.book, AUG), ledger.budget_entry(self.book, SEPT)
        self.assertEqual(aug.source, JournalEntry.SOURCE_BUDGET)
        self.assertEqual(aug.status, JournalEntry.STATUS_POSTED)
        unassigned = unassigned_account(self.book)
        self.assertEqual(
            lines_of(aug),
            {
                bucket_of(self.groceries).pk: Decimal("3500"),
                bucket_of(self.goal.account).pk: Decimal("15000"),
                unassigned.pk: Decimal("-18500"),
            },
        )
        # Expected income is debit-normal: an income budget is a debit to its bucket.
        # September nets to zero, so it has no Unassigned line.
        self.assertEqual(
            lines_of(sept),
            {
                bucket_of(self.groceries).pk: Decimal("4000"),
                bucket_of(self.salary).pk: Decimal("-5000"),
                bucket_of(self.goal.account).pk: Decimal("1000"),
            },
        )
        self.assertTrue(aug.is_balanced and sept.is_balanced)

    def test_changing_an_amount_rewrites_its_line_in_place(self):
        line = ledger.budget_entry(self.book, AUG).lines.get(account=bucket_of(self.groceries))
        set_budget(self.book, self.groceries, AUG, Decimal("3000"))
        line.refresh_from_db()
        self.assertEqual(line.cr_amount, Decimal("3000"))
        self.assertEqual(
            ledger.budget_entry(self.book, AUG).lines.get(account=unassigned_account(self.book)).dr_amount,
            Decimal("18000"),
        )
        self.assert_sound()

    def test_a_negative_amount_posts_to_the_other_side(self):
        set_budget(self.book, self.fun, OCT, Decimal("-20"))
        self.assertEqual(lines_of(ledger.budget_entry(self.book, OCT))[bucket_of(self.fun).pk], Decimal("-20"))
        self.assert_sound()

    def test_zero_drops_the_line_and_an_empty_month_drops_the_entry(self):
        set_budget(self.book, self.fun, OCT, Decimal("50"))
        self.assertIsNotNone(ledger.budget_entry(self.book, OCT))
        set_budget(self.book, self.fun, OCT, Decimal("0"))
        self.assertIsNone(ledger.budget_entry(self.book, OCT))

    def test_other_buckets_are_left_alone(self):
        set_budget(self.book, self.fun, SEPT, Decimal("80"))
        lines = lines_of(ledger.budget_entry(self.book, SEPT))
        self.assertEqual(lines[bucket_of(self.groceries).pk], Decimal("4000"))
        self.assertEqual(lines[bucket_of(self.fun).pk], Decimal("80"))
        self.assertEqual(lines[unassigned_account(self.book).pk], Decimal("-80"))

    def test_adding_to_a_budget_and_a_goal(self):
        self.assertEqual(ledger.add_to_budget(self.book, self.groceries, SEPT, Decimal("250")), Decimal("4250"))
        self.assertEqual(ledger.add_to_goal_allocation(self.book, self.goal, SEPT, Decimal("-300")), Decimal("700"))
        self.assertEqual(ledger.budget_amount(self.book, self.groceries, SEPT), Decimal("4250"))
        self.assertEqual(ledger.goal_allocation(self.book, self.goal, SEPT), Decimal("700"))
        self.assert_sound()

    def test_rebalance_is_idempotent(self):
        before = {e.pk: lines_of(e) for e in JournalEntry.objects.filter(source=JournalEntry.SOURCE_BUDGET)}
        ledger.rebalance_book(self.book)
        ledger.rebalance_book(self.book)
        after = {e.pk: lines_of(e) for e in JournalEntry.objects.filter(source=JournalEntry.SOURCE_BUDGET)}
        self.assertEqual(before, after)


class LedgerUnassignedTest(LedgerFixture):
    """Unassigned from bucket balances equals Unassigned from the monthly walk, month by month."""

    def test_matches_with_spending_overspending_income_and_goal_spending(self):
        self.post(date(2026, 8, 10), self.groceries, self.checking, "4200")  # overspent in August
        self.post(date(2026, 9, 5), self.checking, self.salary, "4800")  # income short of budget
        self.post(date(2026, 9, 12), self.fun, self.checking, "75")  # unbudgeted spending
        self.post(date(2026, 9, 20), self.goal.account, self.checking, "500")  # spending from the goal
        self.assert_sound()

    def test_matches_with_future_income_off(self):
        self.book.budget_future_income = False
        self.book.save()
        self.assert_sound()

    def test_an_unbalanced_entry_is_caught_and_fixed(self):
        line = ledger.budget_entry(self.book, AUG).lines.get(account=bucket_of(self.groceries))
        JournalLine.objects.filter(pk=line.pk).update(cr_amount=Decimal("1"))
        result = ledger.check_book(self.book, through=OCT)
        self.assertEqual([month for month, _problem in result.entry_problems], [AUG])
        ledger.rebalance_book(self.book)
        self.assert_sound()
        self.assertEqual(ledger.budget_amount(self.book, self.groceries, AUG), Decimal("1"))


class DeletionTest(LedgerFixture):
    def test_deleting_a_budgeted_category_is_still_allowed(self):
        self.fun.delete()  # no budget: nothing to release
        self.groceries.delete()
        self.assertFalse(Account.objects.filter(name__startswith="Groceries").exists())
        self.assertNotIn(None, [e.is_balanced or None for e in JournalEntry.objects.filter(source="budget")])
        self.assert_sound()

    def test_deleting_a_goal_releases_its_bucket(self):
        bucket = bucket_of(self.goal.account)
        GoalService(self.book).delete(self.goal)
        self.assertFalse(Account.objects.filter(pk=bucket.pk).exists())
        self.assert_sound()

    def test_undoing_a_contribution_rewrites_the_month(self):
        GoalService(self.book).edit_allocation(self.goal, SEPT, Decimal("0"))
        self.assertNotIn(bucket_of(self.goal.account).pk, lines_of(ledger.budget_entry(self.book, SEPT)))
        self.assert_sound()


class BulkPathsTest(LedgerFixture):
    def setUp(self):
        self.client.force_login(self.user)

    def url(self, name):
        return reverse(name, args=self.book.url_args)

    def test_grid_save_rewrites_every_month_it_touched(self):
        response = self.client.post(
            self.url("budget:budget_grid_save"),
            json.dumps(
                {
                    "changes": [
                        {"category_id": self.fun.pk, "month": "2026-09-01", "amount": "60"},
                        {"category_id": self.fun.pk, "month": "2026-10-01", "amount": "70"},
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(lines_of(ledger.budget_entry(self.book, OCT))[bucket_of(self.fun).pk], Decimal("70"))
        self.assert_sound()

    def test_autofill_rewrites_the_month(self):
        response = self.client.post(
            self.url("budget:budget_autofill"), {"action": "assigned_last_month", "month": "2026-09-01"}
        )
        self.assertEqual(response.status_code, 302)
        # September's groceries now match August's 3,500.
        self.assertEqual(lines_of(ledger.budget_entry(self.book, SEPT))[bucket_of(self.groceries).pk], Decimal("3500"))
        self.assert_sound()


class TransactionsIgnoreBudgetEntriesTest(LedgerFixture):
    """Budget entries are not history: nothing that lists or counts transactions sees them."""

    def test_transactions_api_lists_none_and_cannot_reach_one(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        base = f"/a/{self.team.slug}/{self.book.slug}/journal/api"
        with current_book(self.book):
            rows = client.get(f"{base}/transactions/").json()["results"]
            self.assertEqual([row["description"] for row in rows], ["entry"])
            entry = ledger.budget_entry(self.book, AUG)
            self.assertEqual(client.get(f"{base}/journal-entries/{entry.pk}/").status_code, 404)
            self.assertEqual(client.delete(f"{base}/journal-entries/{entry.pk}/").status_code, 404)
        self.assertTrue(JournalEntry.objects.filter(pk=entry.pk).exists())

    def test_a_book_with_only_a_budget_still_counts_as_empty(self):
        JournalEntry.objects.filter(source=JournalEntry.SOURCE_MANUAL).delete()
        self.assertTrue(can_import(self.book))
        self.assertFalse(book_facts(self.book).has_entries)
        self.assertFalse(can_set_opening_balances(self.book))


class ReadsTest(LedgerFixture):
    """Every budget figure is read off the budget entries."""

    def test_budgeted_and_available(self):
        from .services import BudgetService

        service = BudgetService(self.book)
        self.assertEqual(service.budgeted(self.groceries, SEPT), Decimal("4000"))
        self.assertEqual(service.budgeted(self.salary, SEPT), Decimal("5000"))
        self.assertEqual(service.available(self.groceries, SEPT), Decimal("7500"))
        available, _previous = service.get_available_with_previous(SEPT, [self.groceries])
        self.assertEqual(available[self.groceries.pk], Decimal("7500"))

    def test_goal_figures(self):
        from .services import goal_monthly

        goal = Goal.objects.filter(pk=self.goal.pk).with_progress(SEPT).get()
        self.assertEqual(goal.allocated, Decimal("16000"))
        self.assertEqual(goal.saved_this_month, Decimal("1000"))
        self.assertEqual(goal_monthly(self.book, [self.goal])[self.goal.pk][SEPT]["assigned"], Decimal("1000"))

    def test_budget_page_shows_the_amount(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("budget:budget_home", args=self.book.url_args), {"month": "2026-09"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="4000.00"')

    def test_has_budget_needs_a_category_budget(self):
        self.assertTrue(ledger.has_budget(self.book))
        ledger.set_budgets(
            self.book, {(c.pk, m): 0 for c, m in ((self.groceries, AUG), (self.groceries, SEPT), (self.salary, SEPT))}
        )
        self.assertFalse(ledger.has_budget(self.book))  # goal allocations alone don't count


class RetypeTest(LedgerFixture):
    def test_moving_a_category_between_income_and_expense_flips_its_lines(self):
        income = AccountGroup.objects.get(book=self.book, name="Work")
        self.groceries.account_group = income
        self.groceries.save()
        self.assertEqual(lines_of(ledger.budget_entry(self.book, SEPT))[bucket_of(self.groceries).pk], Decimal("-4000"))
        # The amount budgeted stays: it now reads as expected income.
        self.assertEqual(ledger.budget_amount(self.book, self.groceries, SEPT), Decimal("4000"))
        self.assert_sound()

    def test_a_rename_leaves_the_lines_alone(self):
        self.groceries.name = "Food"
        self.groceries.save()
        self.assertEqual(lines_of(ledger.budget_entry(self.book, SEPT))[bucket_of(self.groceries).pk], Decimal("4000"))


class LedgerCheckCommandTest(LedgerFixture):
    """`manage.py budget_ledger_check`: the operator's integrity check on budget entries."""

    def run_check(self, *args):
        out = StringIO()
        call_command("budget_ledger_check", "--team", self.team.slug, *args, stdout=out)
        return out.getvalue()

    def unbalance(self):
        # A raw update skips every writer, the way drift would arrive.
        JournalLine.objects.filter(
            book=self.book, journal_entry__source=JournalEntry.SOURCE_BUDGET, account=unassigned_account(self.book)
        ).update(dr_amount=Decimal("1"), cr_amount=Decimal("0"))

    def test_a_sound_book_reports_ok(self):
        out = self.run_check()
        self.assertIn(f"OK    {self.team.slug}/{self.book.slug}", out)
        self.assertIn("Every book's budget entries check out.", out)

    def test_an_unbalanced_entry_is_reported(self):
        self.unbalance()
        out = self.run_check()
        self.assertIn(f"FAIL  {self.team.slug}/{self.book.slug}", out)
        self.assertIn("1 book(s) failed.", out)

    def test_fix_rebalances_the_unassigned_line(self):
        self.unbalance()
        out = self.run_check("--fix")
        self.assertIn(f"OK    {self.team.slug}/{self.book.slug}", out)
        self.assertEqual(ledger.check_book(self.book).entry_problems, [])

    def test_filters_narrow_to_the_named_book(self):
        out = self.run_check("--book", "no-such-book")
        self.assertNotIn("OK    ", out)
        self.assertIn("Every book's budget entries check out.", out)
