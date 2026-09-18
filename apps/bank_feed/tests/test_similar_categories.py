"""
Tests for similar-transaction category suggestions.

Covers the matcher itself (payee, description and fuzzy tiers, and what is kept
out of the history) and the endpoint that serves it.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.similar_transactions import (
    MATCH_DESCRIPTION,
    MATCH_PAYEE,
    MATCH_SIMILAR,
    build_history_index,
    signature_tokens,
    suggest_categories,
    suggest_categories_for,
)
from apps.journal.models import JournalEntry, JournalLine
from apps.teams.context import current_team
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser


class SimilarCategoriesTestMixin:
    """Shared fixtures: one bank account and a few expense categories."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Similar Team", slug="similar-team")
        cls.user = CustomUser.objects.create_user(username="similaruser", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})

        asset_group = AccountGroup.objects.create(team=cls.team, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        expense_group = AccountGroup.objects.create(team=cls.team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.bank_account = Account.objects.create(
            team=cls.team, name="Checking", account_group=asset_group, has_feed=True
        )
        cls.coffee = Account.objects.create(team=cls.team, name="Coffee", account_group=expense_group)
        cls.groceries = Account.objects.create(team=cls.team, name="Groceries", account_group=expense_group)
        cls.dining = Account.objects.create(team=cls.team, name="Dining", account_group=expense_group)

    def _categorized(self, category, *, merchant="", description="", posted_date=None, **kwargs):
        posted_date = posted_date or date.today()
        entry = JournalEntry.objects.create(
            team=self.team,
            entry_date=posted_date,
            description=description or merchant,
            status=kwargs.pop("entry_status", JournalEntry.STATUS_POSTED),
        )
        JournalLine.objects.create(
            journal_entry=entry,
            team=self.team,
            account=self.bank_account,
            dr_amount=Decimal("0"),
            cr_amount=Decimal("10"),
        )
        JournalLine.objects.create(
            journal_entry=entry,
            team=self.team,
            account=category,
            dr_amount=Decimal("10"),
            cr_amount=Decimal("0"),
        )
        return BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=posted_date,
            description=description or merchant,
            merchant_name=merchant or None,
            amount=Decimal("10.00"),
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
            **kwargs,
        )

    def _uncategorized(self, *, merchant="", description="", posted_date=None):
        return BankTransaction.objects.create(
            team=self.team,
            account=self.bank_account,
            posted_date=posted_date or date.today(),
            description=description or merchant,
            merchant_name=merchant or None,
            amount=Decimal("10.00"),
            source=BankTransaction.SOURCE_CSV,
        )

    def _suggest(self, transaction):
        return suggest_categories_for(transaction, build_history_index(self.team))


class SignatureTokensTest(TestCase):
    """Unit tests for the description tokenizer."""

    def test_drops_digits_short_words_and_bank_noise(self):
        self.assertEqual(
            signature_tokens("POS DEBIT CARD 4417 BLUE BOTTLE"),
            {"blue", "bottle"},
        )

    def test_punctuation_is_a_separator(self):
        self.assertEqual(signature_tokens("SQ *BLUE-BOTTLE"), {"blue", "bottle"})


class SuggestCategoriesForTest(SimilarCategoriesTestMixin, TestCase):
    """The matcher's tiers, counts and ranking."""

    def test_counts_transactions_with_the_same_payee(self):
        for _ in range(3):
            self._categorized(self.coffee, merchant="Blue Bottle")

        suggestions = self._suggest(self._uncategorized(merchant="Blue Bottle"))

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["category_id"], self.coffee.id)
        self.assertEqual(suggestions[0]["category_name"], "Coffee")
        self.assertEqual(suggestions[0]["count"], 3)
        self.assertEqual(suggestions[0]["match_type"], MATCH_PAYEE)
        self.assertEqual(suggestions[0]["payee"], "Blue Bottle")

    def test_payee_match_ignores_case_and_punctuation(self):
        self._categorized(self.coffee, merchant="BLUE BOTTLE, INC.")

        suggestions = self._suggest(self._uncategorized(merchant="blue bottle inc"))

        self.assertEqual([s["category_id"] for s in suggestions], [self.coffee.id])
        self.assertEqual(suggestions[0]["match_type"], MATCH_PAYEE)

    def test_matches_on_description_when_there_is_no_payee(self):
        self._categorized(self.groceries, description="WHOLEFDS MKT")

        suggestions = self._suggest(self._uncategorized(description="WHOLEFDS MKT"))

        self.assertEqual([s["category_id"] for s in suggestions], [self.groceries.id])
        self.assertEqual(suggestions[0]["match_type"], MATCH_DESCRIPTION)

    def test_matches_descriptions_that_differ_only_in_their_numbers(self):
        """A terminal id changes on every visit; the merchant does not."""
        self._categorized(self.coffee, description="SQ *BLUE BOTTLE 4417")

        suggestions = self._suggest(self._uncategorized(description="SQ *BLUE BOTTLE 9920"))

        self.assertEqual([s["category_id"] for s in suggestions], [self.coffee.id])
        self.assertEqual(suggestions[0]["match_type"], MATCH_SIMILAR)

    def test_unrelated_descriptions_do_not_match(self):
        self._categorized(self.groceries, description="WHOLEFDS MKT")

        self.assertEqual(self._suggest(self._uncategorized(description="SHELL OIL")), [])

    def test_ranks_payee_matches_above_fuzzy_ones_then_by_count(self):
        self._categorized(self.dining, merchant="Blue Bottle Cafe")
        for _ in range(2):
            self._categorized(self.coffee, description="SQ *BLUE BOTTLE 4417")

        suggestions = self._suggest(self._uncategorized(merchant="Blue Bottle Cafe"))

        self.assertEqual([s["category_id"] for s in suggestions], [self.dining.id, self.coffee.id])
        self.assertEqual(suggestions[0]["match_type"], MATCH_PAYEE)
        self.assertEqual(suggestions[1]["match_type"], MATCH_SIMILAR)
        self.assertEqual(suggestions[1]["count"], 2)

    def test_competing_categories_for_one_payee_are_ranked_by_count(self):
        self._categorized(self.dining, merchant="Blue Bottle")
        for _ in range(2):
            self._categorized(self.coffee, merchant="Blue Bottle")

        suggestions = self._suggest(self._uncategorized(merchant="Blue Bottle"))

        self.assertEqual(
            [(s["category_id"], s["count"]) for s in suggestions], [(self.coffee.id, 2), (self.dining.id, 1)]
        )

    def test_uncategorized_history_is_not_evidence(self):
        self._uncategorized(merchant="Blue Bottle")

        self.assertEqual(self._suggest(self._uncategorized(merchant="Blue Bottle")), [])

    def test_voided_archived_and_mirror_transactions_are_excluded(self):
        self._categorized(self.coffee, merchant="Blue Bottle", entry_status=JournalEntry.STATUS_VOID)
        self._categorized(self.coffee, merchant="Blue Bottle", is_archived=True)
        self._categorized(self.coffee, merchant="Blue Bottle", is_transfer_mirror=True)

        self.assertEqual(self._suggest(self._uncategorized(merchant="Blue Bottle")), [])

    def test_archived_category_accounts_are_not_suggested(self):
        self._categorized(self.coffee, merchant="Blue Bottle")
        self.coffee.is_archived = True
        self.coffee.save()

        self.assertEqual(self._suggest(self._uncategorized(merchant="Blue Bottle")), [])

    def test_a_transaction_is_not_evidence_about_itself(self):
        already_categorized = self._categorized(self.coffee, merchant="Blue Bottle")

        self.assertEqual(self._suggest(already_categorized), [])

    def test_only_the_top_matches_are_returned(self):
        for category in (self.coffee, self.groceries, self.dining):
            self._categorized(category, merchant="Blue Bottle")
        fourth = Account.objects.create(team=self.team, name="Zebra", account_group=self.coffee.account_group)
        self._categorized(fourth, merchant="Blue Bottle")

        self.assertEqual(len(self._suggest(self._uncategorized(merchant="Blue Bottle"))), 3)

    def test_another_teams_history_is_not_used(self):
        other_team = Team.objects.create(name="Other", slug="other-team")
        other_group = AccountGroup.objects.create(team=other_team, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        other_expenses = AccountGroup.objects.create(
            team=other_team, name="Expenses", account_type=ACCOUNT_TYPE_EXPENSE
        )
        other_bank = Account.objects.create(team=other_team, name="Checking", account_group=other_group, has_feed=True)
        other_category = Account.objects.create(team=other_team, name="Coffee", account_group=other_expenses)
        entry = JournalEntry.objects.create(
            team=other_team, entry_date=date.today(), description="Blue Bottle", status=JournalEntry.STATUS_POSTED
        )
        JournalLine.objects.create(
            journal_entry=entry, team=other_team, account=other_bank, dr_amount=Decimal("0"), cr_amount=Decimal("10")
        )
        JournalLine.objects.create(
            journal_entry=entry,
            team=other_team,
            account=other_category,
            dr_amount=Decimal("10"),
            cr_amount=Decimal("0"),
        )
        BankTransaction.objects.create(
            team=other_team,
            account=other_bank,
            posted_date=date.today(),
            description="Blue Bottle",
            merchant_name="Blue Bottle",
            amount=Decimal("10.00"),
            source=BankTransaction.SOURCE_CSV,
            journal_entry=entry,
        )

        self.assertEqual(self._suggest(self._uncategorized(merchant="Blue Bottle")), [])

    def test_batch_indexes_history_once_for_every_transaction(self):
        self._categorized(self.coffee, merchant="Blue Bottle")
        self._categorized(self.groceries, merchant="Wholefoods")
        first = self._uncategorized(merchant="Blue Bottle")
        second = self._uncategorized(merchant="Wholefoods")
        third = self._uncategorized(merchant="Nobody Knows")

        results = suggest_categories(self.team, [first, second, third])

        self.assertEqual(results[first.id][0]["category_id"], self.coffee.id)
        self.assertEqual(results[second.id][0]["category_id"], self.groceries.id)
        self.assertNotIn(third.id, results)


class SimilarCategoriesEndpointTest(SimilarCategoriesTestMixin, TestCase):
    """The similar_categories API action."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = f"/a/{self.team.slug}/bankfeed/api/feed/similar_categories/"

    def _get(self, ids):
        with current_team(self.team):
            return self.client.get(self.url, {"ids": ids})

    def test_returns_ranked_suggestions_with_counts(self):
        for _ in range(2):
            self._categorized(self.coffee, merchant="Blue Bottle", posted_date=date.today() - timedelta(days=7))
        target = self._uncategorized(merchant="Blue Bottle")

        response = self._get(str(target.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            [
                {
                    "transaction_id": target.id,
                    "category_id": self.coffee.id,
                    "category_name": "Coffee",
                    "count": 2,
                    "match_type": MATCH_PAYEE,
                    "payee": "Blue Bottle",
                }
            ],
        )

    def test_results_follow_the_requested_order(self):
        self._categorized(self.coffee, merchant="Blue Bottle")
        self._categorized(self.groceries, merchant="Wholefoods")
        first = self._uncategorized(merchant="Blue Bottle")
        second = self._uncategorized(merchant="Wholefoods")

        response = self._get(f"{second.id},{first.id}")

        self.assertEqual([row["transaction_id"] for row in response.data], [second.id, first.id])

    def test_transactions_with_no_match_are_simply_absent(self):
        target = self._uncategorized(merchant="Nobody Knows")

        response = self._get(str(target.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_blank_ids_returns_empty(self):
        with current_team(self.team):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_non_numeric_ids_are_rejected(self):
        response = self._get("12,abc")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_too_many_ids_are_rejected(self):
        response = self._get(",".join(str(i) for i in range(1, 60)))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_another_teams_transaction_ids_are_ignored(self):
        other_team = Team.objects.create(name="Other", slug="other-endpoint-team")
        other_group = AccountGroup.objects.create(team=other_team, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        other_bank = Account.objects.create(team=other_team, name="Checking", account_group=other_group, has_feed=True)
        foreign = BankTransaction.objects.create(
            team=other_team,
            account=other_bank,
            posted_date=date.today(),
            description="Blue Bottle",
            merchant_name="Blue Bottle",
            amount=Decimal("10.00"),
            source=BankTransaction.SOURCE_CSV,
        )
        self._categorized(self.coffee, merchant="Blue Bottle")

        response = self._get(str(foreign.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_denied_for_anonymous(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url, {"ids": "1"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
