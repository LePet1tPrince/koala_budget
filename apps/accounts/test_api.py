"""
The accounts API (`apps/accounts/api.py`): the ModelViewSets over accounts, groups,
payees and institutions, the institution checklist, and an account's activity and
charts. The board's writes are in `tests.AccountsBoardApiTest`.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.books.tests.factories import second_book
from apps.budget.ledger import set_budget
from apps.journal.models import JournalEntry, JournalLine
from apps.onboarding.services.opening import OpeningRow, create_opening_balances
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser

from .models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_BUDGET,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
    Institution,
    Payee,
)


class AccountsApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Api Team", slug="api-team")
        cls.book = cls.team.default_book
        cls.admin = CustomUser.objects.create_user(username="admin@example.com", password="pass")
        cls.member = CustomUser.objects.create_user(username="member@example.com", password="pass")
        cls.outsider = CustomUser.objects.create_user(username="outsider@example.com", password="pass")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        Team.objects.create(name="Elsewhere", slug="elsewhere").members.add(
            cls.outsider, through_defaults={"role": ROLE_ADMIN}
        )

        cls.bank = Institution.objects.create(book=cls.book, name="First Bank")
        cls.bank_group = AccountGroup.objects.create(book=cls.book, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        cls.card_group = AccountGroup.objects.create(book=cls.book, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY)
        cls.living = AccountGroup.objects.create(book=cls.book, name="Living", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.checking = Account.objects.create(
            book=cls.book, name="Checking", account_group=cls.bank_group, institution=cls.bank, has_feed=True
        )
        cls.card = Account.objects.create(book=cls.book, name="Visa", account_group=cls.card_group)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=cls.living)
        cls.grocer = Payee.objects.create(book=cls.book, name="Grocer")

        cls.other_book = second_book(cls.team)
        cls.other_group = AccountGroup.objects.create(
            book=cls.other_book, name="Their bank", account_type=ACCOUNT_TYPE_ASSET
        )
        cls.other_account = Account.objects.create(book=cls.other_book, name="Theirs", account_group=cls.other_group)
        cls.other_institution = Institution.objects.create(book=cls.other_book, name="Their Bank")

    def setUp(self):
        self.client.force_login(self.admin)

    def url(self, name, *args, book=None):
        return reverse(f"accounts:{name}", args=[*(book or self.book).url_args, *args])

    def spend(self, amount, on=date(2026, 3, 10), payee=None, account=None, category=None):
        entry = JournalEntry.objects.create(book=self.book, entry_date=on, description="Shop", payee=payee)
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=category or self.groceries, dr_amount=Decimal(amount)
        )
        JournalLine.objects.create(
            book=self.book, journal_entry=entry, account=account or self.checking, cr_amount=Decimal(amount)
        )
        return entry


class AccountViewSetTest(AccountsApiTestCase):
    def test_list_reads_the_books_accounts_with_balances(self):
        self.spend("40.00", account=self.card)
        rows = {row["name"]: row for row in self.client.get(self.url("account-list")).json()}
        self.assertEqual(set(rows), {"Checking", "Visa", "Groceries"})
        self.assertNotIn("Theirs", rows)
        visa = rows["Visa"]
        self.assertEqual(visa["balance"], "-40.00")  # dr - cr
        self.assertEqual(visa["natural_balance"], "40.00")  # owed reads positive
        self.assertEqual(visa["account_type"], ACCOUNT_TYPE_LIABILITY)
        self.assertEqual(rows["Checking"]["institution_name"], "First Bank")

    def test_list_filters_by_type_and_leaves_budget_buckets_out(self):
        set_budget(self.book, self.groceries, date(2026, 3, 1), Decimal("100"))
        names = [row["name"] for row in self.client.get(self.url("account-list"), {"account_type": "expense"}).json()]
        self.assertEqual(names, ["Groceries"])
        all_types = {row["account_type"] for row in self.client.get(self.url("account-list")).json()}
        self.assertNotIn(ACCOUNT_TYPE_BUDGET, all_types)

    def test_retrieve_carries_the_page_extras(self):
        data = self.client.get(self.url("account-detail", self.checking.pk)).json()
        self.assertEqual(data["name"], "Checking")
        self.assertTrue(data["reconcilable"])
        self.assertIsNone(data["feeds_goal"])

    def test_create_defaults_the_feed_and_goes_to_the_bottom_of_its_group(self):
        response = self.client.post(
            self.url("account-list"),
            {"name": " Savings ", "account_group": self.bank_group.pk, "institution": self.bank.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        account = Account.objects.get(book=self.book, name="Savings")
        self.assertTrue(account.has_feed)
        self.assertEqual(account.institution, self.bank)
        self.assertEqual(account.sort_order, 1)  # after Checking
        self.assertEqual(response.json()["natural_balance"], "0.00")

        response = self.client.post(
            self.url("account-list"), {"name": "Rent", "account_group": self.living.pk}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(Account.objects.get(book=self.book, name="Rent").has_feed)

    def test_a_member_may_create_but_not_edit_or_delete(self):
        self.client.force_login(self.member)
        response = self.client.post(
            self.url("account-list"), {"name": "Mine", "account_group": self.living.pk}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        detail = self.url("account-detail", self.groceries.pk)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertEqual(self.client.patch(detail, {"name": "Food"}, content_type="application/json").status_code, 403)
        self.assertEqual(self.client.delete(detail).status_code, 403)
        self.groceries.refresh_from_db()
        self.assertEqual(self.groceries.name, "Groceries")

    def test_validation_is_the_forms(self):
        cases = [
            # Unique within its type, as AccountForm says
            ({"name": "Groceries", "account_group": self.living.pk}, "name"),
            # Only assets and liabilities are held at an institution
            ({"name": "Fuel", "account_group": self.living.pk, "institution": self.bank.pk}, "institution"),
            # Another book's group, and the budget group, do not exist here
            ({"name": "Sneaky", "account_group": self.other_group.pk}, "account_group"),
            ({"name": "Blank", "account_group": self.bank_group.pk, "institution": self.other_institution.pk}, None),
        ]
        budget_group = AccountGroup.objects.filter(book=self.book, account_type=ACCOUNT_TYPE_BUDGET).first()
        if budget_group is None:
            set_budget(self.book, self.groceries, date(2026, 3, 1), Decimal("1"))
            budget_group = AccountGroup.objects.get(book=self.book, account_type=ACCOUNT_TYPE_BUDGET)
        cases.append(({"name": "Bucket", "account_group": budget_group.pk}, "account_group"))
        for body, field in cases:
            with self.subTest(body=body):
                response = self.client.post(self.url("account-list"), body, content_type="application/json")
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(field or "institution", response.json())
        # The same name is fine under another type
        response = self.client.post(
            self.url("account-list"),
            {"name": "Groceries", "account_group": self.bank_group.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_update_renames_and_moving_to_an_expense_drops_the_institution(self):
        detail = self.url("account-detail", self.checking.pk)
        response = self.client.patch(detail, {"name": "Everyday"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Everyday")
        response = self.client.patch(detail, {"account_group": self.living.pk}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.checking.refresh_from_db()
        self.assertEqual(self.checking.account_group, self.living)
        self.assertIsNone(self.checking.institution)

    def test_delete_follows_the_pages_rules(self):
        self.spend("5.00")
        response = self.client.delete(self.url("account-detail", self.groceries.pk))
        self.assertEqual(response.status_code, 400)
        self.assertIn("delete all associated transactions", response.json()["non_field_errors"][0])
        self.assertTrue(Account.objects.filter(pk=self.groceries.pk).exists())

        equity = AccountGroup.objects.create(
            book=self.book, name="Equity", account_type=ACCOUNT_TYPE_EQUITY, is_system=True
        )
        system = Account.objects.create(
            book=self.book, name="Reconciliation Adjustments", account_group=equity, is_system=True
        )
        self.assertEqual(self.client.delete(self.url("account-detail", system.pk)).status_code, 400)

        # Only its own opening balance: deleted with it
        savings = Account.objects.create(book=self.book, name="Savings", account_group=self.bank_group)
        create_opening_balances(self.book, [OpeningRow(account=savings, amount=Decimal("100.00"))], date.today())
        self.assertEqual(self.client.delete(self.url("account-detail", savings.pk)).status_code, 204)
        self.assertFalse(Account.objects.filter(pk=savings.pk).exists())
        self.assertFalse(JournalLine.objects.filter(account_id=savings.pk).exists())

    def test_another_books_account_is_a_404(self):
        for name in ("account-detail", "account-activity", "account-charts"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name, self.other_account.pk)).status_code, 404)
        response = self.client.patch(
            self.url("account-detail", self.other_account.pk), {"name": "Mine"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 404)

    def test_outsiders_and_anonymous_are_refused(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url("account-list")).status_code, 403)
        self.client.logout()
        self.assertIn(self.client.get(self.url("account-list")).status_code, (401, 403))
        response = self.client.post(
            self.url("account-list"), {"name": "Anon", "account_group": self.living.pk}, content_type="application/json"
        )
        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(Account.objects.filter(name="Anon").exists())


class AccountActivityApiTest(AccountsApiTestCase):
    def test_activity_signs_amounts_and_runs_a_balance(self):
        self.spend("30.00", on=date(2026, 2, 20))
        entry = self.spend("12.50", on=date(2026, 3, 5), payee=self.grocer)
        data = self.client.get(
            self.url("account-activity", self.checking.pk), {"start_date": "2026-03-01", "end_date": "2026-03-31"}
        ).json()
        self.assertTrue(data["is_balance_account"])
        self.assertEqual(data["starting_balance"], "-30.00")
        self.assertEqual(data["ending_balance"], "-42.50")
        self.assertEqual(data["total"], "-12.50")
        [row] = data["transactions"]
        self.assertEqual(row["entry_id"], entry.pk)
        self.assertEqual(row["date"], "2026-03-05")
        self.assertEqual(row["payee_id"], self.grocer.pk)
        self.assertEqual(row["payee_name"], "Grocer")
        self.assertEqual(row["amount"], "-12.50")
        self.assertEqual(row["balance"], "-42.50")
        self.assertEqual(row["contra_accounts"], [{"id": self.groceries.pk, "name": "Groceries"}])
        self.assertTrue(row["editable"])
        self.assertEqual(row["source"], JournalEntry.SOURCE_MANUAL)

    def test_an_expense_has_no_running_balance(self):
        self.spend("12.50", on=date(2026, 3, 5))
        data = self.client.get(
            self.url("account-activity", self.groceries.pk), {"start_date": "2026-03-01", "end_date": "2026-03-31"}
        ).json()
        self.assertFalse(data["is_balance_account"])
        self.assertIsNone(data["starting_balance"])
        self.assertEqual(data["total"], "12.50")
        self.assertIsNone(data["transactions"][0]["balance"])

    def test_the_range_defaults_to_the_books_and_is_validated(self):
        response = self.client.get(self.url("account-activity", self.checking.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["end_date"], date.today().isoformat())
        for params in (
            {"start_date": "2026-03-01"},
            {"start_date": "March", "end_date": "2026-03-31"},
            {"start_date": "2026-03-31", "end_date": "2026-03-01"},
        ):
            with self.subTest(params=params):
                response = self.client.get(self.url("account-charts", self.checking.pk), params)
                self.assertEqual(response.status_code, 400)

    def test_a_member_reads_the_charts(self):
        self.client.force_login(self.member)
        set_budget(self.book, self.groceries, date(2026, 3, 1), Decimal("50.00"))
        self.spend("20.00", on=date(2026, 3, 5))
        charts = self.client.get(
            self.url("account-charts", self.groceries.pk), {"start_date": "2026-02-01", "end_date": "2026-03-31"}
        ).json()
        self.assertIsNone(charts["balance"])
        self.assertEqual(charts["budget"]["months"], ["2026-02", "2026-03"])
        self.assertEqual(charts["budget"]["budgeted"], ["0.00", "50.00"])
        self.assertEqual(charts["budget"]["actual"], ["0.00", "20.00"])
        self.assertEqual(charts["budget"]["available"], ["0.00", "30.00"])

    def test_income_has_no_budget_chart_when_the_book_budgets_landed_money_only(self):
        salary_group = AccountGroup.objects.create(book=self.book, name="Pay", account_type=ACCOUNT_TYPE_INCOME)
        salary = Account.objects.create(book=self.book, name="Salary", account_group=salary_group)
        self.book.budget_future_income = False
        self.book.save()
        charts = self.client.get(self.url("account-charts", salary.pk)).json()
        self.assertEqual(charts, {"balance": None, "budget": None})


class AccountGroupViewSetTest(AccountsApiTestCase):
    def test_list_counts_accounts_and_leaves_the_budget_group_out(self):
        set_budget(self.book, self.groceries, date(2026, 3, 1), Decimal("1"))
        rows = {row["name"]: row for row in self.client.get(self.url("account-group-list")).json()}
        self.assertEqual(rows["Bank"]["account_count"], 1)
        self.assertNotIn(ACCOUNT_TYPE_BUDGET, {row["account_type"] for row in rows.values()})
        self.assertNotIn("Their bank", rows)

    def test_create_goes_to_the_bottom_of_its_type(self):
        AccountGroup.objects.filter(pk=self.bank_group.pk).update(sort_order=4)
        response = self.client.post(
            self.url("account-group-list"),
            {"name": "Property", "account_type": "asset"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["sort_order"], 5)

    def test_names_are_unique_and_budget_is_not_a_type(self):
        for body in ({"name": " Bank ", "account_type": "asset"}, {"name": "Envelopes", "account_type": "budget"}):
            with self.subTest(body=body):
                response = self.client.post(self.url("account-group-list"), body, content_type="application/json")
                self.assertEqual(response.status_code, 400)
        # Renaming to its own name is not a clash
        response = self.client.patch(
            self.url("account-group-detail", self.bank_group.pk), {"name": "Bank"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

    def test_type_is_fixed_while_the_group_holds_accounts(self):
        response = self.client.patch(
            self.url("account-group-detail", self.living.pk),
            {"account_type": "income"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("account_type", response.json())
        empty = AccountGroup.objects.create(book=self.book, name="Spare", account_type=ACCOUNT_TYPE_EXPENSE)
        response = self.client.patch(
            self.url("account-group-detail", empty.pk), {"account_type": "income"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_is_refused_while_it_holds_accounts(self):
        response = self.client.delete(self.url("account-group-detail", self.living.pk))
        self.assertEqual(response.status_code, 400)
        self.assertIn("still has 1 account", response.json()["non_field_errors"][0])
        empty = AccountGroup.objects.create(book=self.book, name="Spare", account_type=ACCOUNT_TYPE_EXPENSE)
        self.assertEqual(self.client.delete(self.url("account-group-detail", empty.pk)).status_code, 204)
        system = AccountGroup.objects.create(
            book=self.book, name="System", account_type=ACCOUNT_TYPE_EQUITY, is_system=True
        )
        self.assertEqual(self.client.delete(self.url("account-group-detail", system.pk)).status_code, 400)

    def test_another_books_group_is_a_404(self):
        self.assertEqual(self.client.get(self.url("account-group-detail", self.other_group.pk)).status_code, 404)
        self.assertEqual(self.client.delete(self.url("account-group-detail", self.other_group.pk)).status_code, 404)
        self.assertTrue(AccountGroup.objects.filter(pk=self.other_group.pk).exists())


class PayeeViewSetTest(AccountsApiTestCase):
    def test_list_shows_usage(self):
        self.spend("5.00", on=date(2026, 3, 1), payee=self.grocer)
        self.spend("6.00", on=date(2026, 3, 9), payee=self.grocer)
        [row] = self.client.get(self.url("payee-list")).json()
        self.assertEqual(row["transaction_count"], 2)
        self.assertEqual(row["first_used"], "2026-03-01")
        self.assertEqual(row["last_used"], "2026-03-09")

    def test_create_rename_and_duplicate(self):
        response = self.client.post(self.url("payee-list"), {"name": " Baker "}, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["name"], "Baker")
        response = self.client.post(self.url("payee-list"), {"name": "Grocer"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["name"][0])

    def test_a_payee_on_a_transaction_cannot_be_deleted(self):
        self.spend("5.00", payee=self.grocer)
        response = self.client.delete(self.url("payee-detail", self.grocer.pk))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Rename it instead", response.json()["non_field_errors"][0])
        unused = Payee.objects.create(book=self.book, name="Unused")
        self.assertEqual(self.client.delete(self.url("payee-detail", unused.pk)).status_code, 204)

    def test_a_member_cannot_rename(self):
        self.client.force_login(self.member)
        response = self.client.patch(
            self.url("payee-detail", self.grocer.pk), {"name": "Mine"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)


class InstitutionViewSetTest(AccountsApiTestCase):
    def test_crud(self):
        response = self.client.post(
            self.url("institution-list"), {"name": "Credit Union"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            self.url("institution-list"), {"name": "First Bank"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        rows = {row["name"]: row for row in self.client.get(self.url("institution-list")).json()}
        self.assertEqual(rows["First Bank"]["account_count"], 1)
        self.assertNotIn("Their Bank", rows)
        # Deleting keeps its accounts, unlinked
        self.assertEqual(self.client.delete(self.url("institution-detail", self.bank.pk)).status_code, 204)
        self.checking.refresh_from_db()
        self.assertIsNone(self.checking.institution)

    def test_checklist_lists_assets_and_liabilities(self):
        data = self.client.get(self.url("institution-accounts", self.bank.pk)).json()
        self.assertEqual([s["account_type"] for s in data["sections"]], ["asset", "liability"])
        choices = {c["name"]: c for s in data["sections"] for g in s["groups"] for c in g["choices"]}
        self.assertEqual(set(choices), {"Checking", "Visa"})
        self.assertTrue(choices["Checking"]["linked"])
        self.assertFalse(choices["Visa"]["linked"])

    def test_checklist_links_and_unlinks(self):
        elsewhere = Institution.objects.create(book=self.book, name="Other Bank")
        Account.objects.filter(pk=self.card.pk).update(institution=elsewhere)
        response = self.client.post(
            self.url("institution-accounts", self.bank.pk),
            {"account_ids": [self.card.pk, self.groceries.pk, self.other_account.pk]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.checking.refresh_from_db()
        self.card.refresh_from_db()
        self.groceries.refresh_from_db()
        self.other_account.refresh_from_db()
        self.assertIsNone(self.checking.institution)  # unticked: unlinked
        self.assertEqual(self.card.institution, self.bank)  # moved here
        self.assertIsNone(self.groceries.institution)  # not offered: untouched
        self.assertIsNone(self.other_account.institution)  # another book's: untouched
        choices = {c["name"]: c for s in response.json()["sections"] for g in s["groups"] for c in g["choices"]}
        self.assertTrue(choices["Visa"]["linked"])

    def test_checklist_validation_and_permissions(self):
        url = self.url("institution-accounts", self.bank.pk)
        self.assertEqual(
            self.client.post(url, {"account_ids": "all"}, content_type="application/json").status_code, 400
        )
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"account_ids": []}, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.checking.refresh_from_db()
        self.assertEqual(self.checking.institution, self.bank)
        self.client.force_login(self.admin)
        response = self.client.get(self.url("institution-accounts", self.other_institution.pk))
        self.assertEqual(response.status_code, 404)
