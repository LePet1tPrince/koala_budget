"""
Tests for the deterministic category-to-account suggestion function.

`suggest_account_for_category` is a pure heuristic, so these tests exercise it
directly without going through the upload pipeline.
"""

from django.test import TestCase

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    Account,
    AccountGroup,
)
from apps.bank_feed.services.csv_upload import suggest_account_for_category
from apps.teams.models import Team


class SuggestAccountForCategoryTest(TestCase):
    """Unit tests for suggest_account_for_category."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Suggest Team", slug="suggest-team")
        cls.income_group = AccountGroup.objects.create(
            team=cls.team, name="Income", account_type=ACCOUNT_TYPE_INCOME
        )
        cls.expense_group = AccountGroup.objects.create(
            team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        cls.asset_group = AccountGroup.objects.create(
            team=cls.team, name="Assets", account_type=ACCOUNT_TYPE_ASSET
        )

        cls.interest_income = Account.objects.create(
            team=cls.team, name="Interest Income", account_group=cls.income_group
        )
        cls.interest_expense = Account.objects.create(
            team=cls.team, name="Interest Expense", account_group=cls.expense_group
        )
        cls.groceries = Account.objects.create(
            team=cls.team, name="Groceries", account_group=cls.expense_group
        )
        cls.restaurants = Account.objects.create(
            team=cls.team, name="Restaurants", account_group=cls.expense_group
        )

    @property
    def accounts(self):
        return list(Account.objects.filter(team=self.team).select_related("account_group"))

    def test_exact_name_match(self):
        result = suggest_account_for_category("Groceries", self.accounts)
        self.assertEqual(result, self.groceries)

    def test_case_insensitive_match(self):
        result = suggest_account_for_category("groceries", self.accounts)
        self.assertEqual(result, self.groceries)

    def test_substring_plural_match(self):
        # "Restaurant" should match "Restaurants" via substring containment.
        result = suggest_account_for_category("Restaurant", self.accounts)
        self.assertEqual(result, self.restaurants)

    def test_interest_prefers_income_when_inflow(self):
        # Money came in -> "Interest" should resolve to Interest Income.
        result = suggest_account_for_category("Interest", self.accounts, prefer_inflow=True)
        self.assertEqual(result, self.interest_income)

    def test_interest_prefers_expense_when_outflow(self):
        # Money went out -> "Interest" should resolve to Interest Expense.
        result = suggest_account_for_category("Interest", self.accounts, prefer_inflow=False)
        self.assertEqual(result, self.interest_expense)

    def test_no_match_returns_none(self):
        result = suggest_account_for_category("Cryptocurrency Mining", self.accounts)
        self.assertIsNone(result)

    def test_blank_category_returns_none(self):
        self.assertIsNone(suggest_account_for_category("", self.accounts))
        self.assertIsNone(suggest_account_for_category("   ", self.accounts))

    def test_is_deterministic(self):
        # Same inputs always produce the same suggestion.
        first = suggest_account_for_category("Interest", self.accounts, prefer_inflow=True)
        second = suggest_account_for_category("Interest", self.accounts, prefer_inflow=True)
        self.assertEqual(first, second)
