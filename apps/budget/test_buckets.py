"""Budget buckets (apps/budget/buckets.py) and the ledger guard that keeps them out of real transactions."""

from datetime import date
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.forms import AccountGroupForm
from apps.accounts.guards import BudgetAccountError
from apps.accounts.models import ACCOUNT_TYPE_BUDGET, Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.books.context import current_book
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.teams.services.template_budget import PERSONAL_BUDGET_TEMPLATE
from apps.teams.services.template_engine import apply_template
from apps.users.models import CustomUser

from .buckets import sync_book, unassigned_account
from .models import Goal
from .services import picker_accounts_data


def bucket_of(account):
    return Account.objects.filter(paired_account=account).first()


def buckets(book):
    return Account.objects.filter(book=book).budget_buckets()


class BucketFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Buckets", slug="buckets")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="buckets@example.com", email="buckets@example.com")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        cls.assets = AccountGroup.objects.create(book=cls.book, name="Cash", account_type="asset")
        cls.equity = AccountGroup.objects.create(book=cls.book, name="Opening", account_type="goal")
        cls.income = AccountGroup.objects.create(book=cls.book, name="Work", account_type="income")
        cls.expenses = AccountGroup.objects.create(book=cls.book, name="Living", account_type="expense")
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=cls.assets)
        cls.opening = Account.objects.create(book=cls.book, name="Opening Balance", account_group=cls.equity)
        cls.salary = Account.objects.create(book=cls.book, name="Salary", account_group=cls.income)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=cls.expenses)

    def entry(self, *lines, source=JournalEntry.SOURCE_MANUAL):
        """Post an entry of (account, dr, cr) lines."""
        entry = JournalEntry.objects.create(
            book=self.book, entry_date=date(2026, 9, 1), description="entry", status="posted", source=source
        )
        for account, dr, cr in lines:
            JournalLine.objects.create(
                book=self.book, journal_entry=entry, account=account, dr_amount=Decimal(dr), cr_amount=Decimal(cr)
            )
        return entry


class BucketSyncTest(BucketFixture):
    def test_income_and_expense_accounts_get_a_paired_bucket(self):
        for account in (self.salary, self.groceries):
            bucket = bucket_of(account)
            self.assertIsNotNone(bucket)
            self.assertEqual(bucket.name, f"{account.name} (budget)")
            self.assertTrue(bucket.is_system)
            self.assertEqual(bucket.account_group.account_type, ACCOUNT_TYPE_BUDGET)
            self.assertTrue(bucket.account_group.is_system)

    def test_assets_and_plain_equity_get_no_bucket(self):
        self.assertIsNone(bucket_of(self.checking))
        self.assertIsNone(bucket_of(self.opening))

    def test_one_unassigned_per_book(self):
        unassigned = unassigned_account(self.book)
        self.assertEqual(unassigned.name, "Unassigned")
        self.assertTrue(unassigned.is_system)
        self.assertEqual(buckets(self.book).filter(paired_account__isnull=True).count(), 1)
        # Unassigned, Salary, Groceries.
        self.assertEqual(buckets(self.book).count(), 3)

    def test_rename_follows_the_category(self):
        self.groceries.name = "Food"
        self.groceries.save()
        self.assertEqual(bucket_of(self.groceries).name, "Food (budget)")

    def test_moving_to_an_asset_group_removes_the_bucket(self):
        self.groceries.account_group = self.assets
        self.groceries.save()
        self.assertIsNone(bucket_of(self.groceries))

    def test_deleting_the_category_deletes_its_bucket(self):
        bucket = bucket_of(self.groceries)
        self.groceries.delete()
        self.assertFalse(Account.objects.filter(pk=bucket.pk).exists())

    def test_a_goal_gets_a_bucket_archived_with_it(self):
        goal = Goal.objects.create(book=self.book, name="Car", target_amount=Decimal("5000"))
        bucket = bucket_of(goal.account)
        self.assertIsNotNone(bucket)
        self.assertEqual(bucket.name, "Goal: Car (budget)")
        self.assertFalse(bucket.is_archived)

        goal.is_archived = True
        goal.save()
        bucket.refresh_from_db()
        self.assertTrue(bucket.is_archived)

    def test_deleting_a_goal_deletes_its_bucket(self):
        from .services import GoalService

        goal = Goal.objects.create(book=self.book, name="Trip", target_amount=Decimal("1000"))
        bucket = bucket_of(goal.account)
        GoalService(self.book).delete(goal)
        self.assertFalse(Account.objects.filter(pk=bucket.pk).exists())

    def test_sync_book_fills_gaps_from_bulk_inserts_and_is_idempotent(self):
        created = Account.objects.bulk_create(
            [Account(book=self.book, name="Rent", account_group=self.expenses)]  # no signal
        )
        stale = bucket_of(self.salary)
        Account.objects.filter(pk=stale.pk).update(name="Old name")
        sync_book(self.book)
        sync_book(self.book)
        self.assertEqual(bucket_of(created[0]).name, "Rent (budget)")
        self.assertEqual(bucket_of(self.salary).name, "Salary (budget)")
        self.assertEqual(buckets(self.book).count(), 4)

    def test_a_template_chart_gets_its_buckets(self):
        team = Team.objects.create(name="Template", slug="template-buckets")
        book = team.default_book
        Account.objects.filter(book=book).delete()
        AccountGroup.objects.filter(book=book).delete()
        apply_template(book, PERSONAL_BUDGET_TEMPLATE)
        categories = Account.objects.filter(book=book, account_group__account_type__in=["income", "expense"])
        self.assertTrue(categories.exists())
        for category in categories:
            self.assertIsNotNone(bucket_of(category), category.name)
        self.assertIsNotNone(unassigned_account(book))


class BucketMigrationTest(BucketFixture):
    """The backfill migration's own functions, run against today's models."""

    def setUp(self):
        from importlib import import_module

        self.migration = import_module("apps.budget.migrations.0009_budget_buckets_backfill")

    def test_backfill_is_idempotent_and_reversible(self):
        self.migration.remove(django_apps, None)
        self.assertFalse(buckets(self.book).exists())
        self.assertFalse(AccountGroup.objects.filter(book=self.book, account_type=ACCOUNT_TYPE_BUDGET).exists())

        self.migration.backfill(django_apps, None)
        self.migration.backfill(django_apps, None)
        self.assertEqual(buckets(self.book).count(), 3)
        self.assertIsNotNone(bucket_of(self.groceries))
        self.assertIsNotNone(unassigned_account(self.book))


class LedgerGuardTest(BucketFixture):
    def test_a_bucket_cannot_appear_in_a_real_transaction(self):
        with self.assertRaises(BudgetAccountError):
            self.entry((self.checking, "50", "0"), (bucket_of(self.groceries), "0", "50"))

    def test_a_budget_entry_cannot_hold_a_category(self):
        with self.assertRaises(BudgetAccountError):
            self.entry(
                (unassigned_account(self.book), "50", "0"),
                (self.groceries, "0", "50"),
                source=JournalEntry.SOURCE_BUDGET,
            )

    def test_a_budget_entry_cannot_hold_a_goal_account(self):
        goal = Goal.objects.create(book=self.book, name="House", target_amount=Decimal("1000"))
        with self.assertRaises(BudgetAccountError):
            self.entry(
                (unassigned_account(self.book), "50", "0"), (goal.account, "0", "50"), source=JournalEntry.SOURCE_BUDGET
            )

    def test_a_budget_entry_between_buckets_is_allowed(self):
        goal = Goal.objects.create(book=self.book, name="House", target_amount=Decimal("1000"))
        entry = self.entry(
            (unassigned_account(self.book), "80", "0"),
            (bucket_of(self.groceries), "0", "50"),
            (bucket_of(goal.account), "0", "30"),
            source=JournalEntry.SOURCE_BUDGET,
        )
        self.assertTrue(entry.is_balanced)

    def test_spending_from_a_goal_is_still_a_real_transaction(self):
        goal = Goal.objects.create(book=self.book, name="Bike", target_amount=Decimal("1000"))
        entry = self.entry((goal.account, "40", "0"), (self.checking, "0", "40"))
        self.assertEqual(entry.lines.count(), 2)

    def test_bulk_import_refuses_a_bucket(self):
        entry = JournalEntry.objects.create(book=self.book, entry_date=date(2026, 9, 1), description="import")
        lines = [
            JournalLine(book=self.book, journal_entry=entry, account=self.checking, dr_amount=Decimal("5")),
            JournalLine(book=self.book, journal_entry=entry, account=bucket_of(self.salary), cr_amount=Decimal("5")),
        ]
        with self.assertRaises(BudgetAccountError):
            JournalLine.objects.bulk_create_for_import(lines, {})
        self.assertFalse(JournalLine.objects.filter(journal_entry=entry).exists())


class LedgerGuardApiTest(BucketFixture):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_journal_entry_api_refuses_a_bucket(self):
        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/journal/api/journal-entries/",
                {
                    "entry_date": "2026-09-01",
                    "description": "Sneaky",
                    "lines": [
                        {"account": self.checking.pk, "dr_amount": "10.00", "cr_amount": "0.00"},
                        {"account": bucket_of(self.groceries).pk, "dr_amount": "0.00", "cr_amount": "10.00"},
                    ],
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("budget account", str(response.data))
        self.assertFalse(JournalEntry.objects.filter(description="Sneaky").exists())

    def test_feed_categorize_refuses_a_bucket(self):
        row = BankTransaction.objects.create(
            book=self.book,
            account=self.checking,
            posted_date=date(2026, 9, 2),
            description="Groceries",
            amount=Decimal("20.00"),
            source=BankTransaction.SOURCE_CSV,
        )
        with current_book(self.book):
            response = self.client.post(
                f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/categorize/",
                {"rows": [{"id": row.id}], "category_id": bucket_of(self.groceries).id},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        row.refresh_from_db()
        self.assertIsNone(row.journal_entry_id)


class BucketsHiddenTest(BucketFixture):
    def setUp(self):
        self.client.force_login(self.user)

    def url(self, name, *args):
        return reverse(name, args=[*self.book.url_args, *args])

    def test_pickers_never_offer_a_bucket(self):
        ids = {row["id"] for row in picker_accounts_data(self.book)}
        self.assertFalse(ids & set(buckets(self.book).values_list("pk", flat=True)))
        self.assertIn(self.groceries.pk, ids)

    def test_transactions_page_never_sends_a_bucket(self):
        response = self.client.get(self.url("journal:transactions_home"))
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.context["all_accounts"]}
        self.assertFalse(ids & set(buckets(self.book).values_list("pk", flat=True)))
        self.assertIn(self.opening.pk, ids)

    def test_accounts_board_and_group_list_leave_buckets_out(self):
        response = self.client.get(self.url("accounts:accounts_home"))
        self.assertEqual(response.status_code, 200)
        board = response.context["manage_props"]
        names = {
            account["name"] for kind in board["types"] for group in kind["groups"] for account in group["accounts"]
        }
        self.assertIn("Groceries", names)
        self.assertNotIn("Unassigned", names)
        groups = self.client.get(self.url("accounts:accountgroup_list")).context["object_list"]
        self.assertNotIn(ACCOUNT_TYPE_BUDGET, {group.account_type for group in groups})

    def test_a_bucket_has_no_page(self):
        response = self.client.get(self.url("accounts:account_detail", bucket_of(self.groceries).pk))
        self.assertEqual(response.status_code, 404)

    def test_a_group_cannot_be_given_the_budget_type(self):
        form = AccountGroupForm(data={"name": "Sneaky", "account_type": ACCOUNT_TYPE_BUDGET}, book=self.book)
        self.assertFalse(form.is_valid())
        self.assertIn("account_type", form.errors)

    def test_board_cannot_create_an_account_in_the_budget_group(self):
        group = bucket_of(self.groceries).account_group
        response = self.client.post(
            self.url("accounts:api_create_account"),
            {"name": "Sneaky", "group_id": group.pk},
            content_type="application/json",
        )
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(Account.objects.filter(book=self.book, name="Sneaky").exists())
