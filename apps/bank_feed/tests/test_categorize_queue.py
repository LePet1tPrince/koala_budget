"""
Categorize Mode's queue (`services/categorize_queue.py`, `feed/categorize_queue/`)
and its Undo (`feed/uncategorize/`).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import ACCOUNT_TYPE_ASSET, Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.categorize import create_entry
from apps.bank_feed.services.categorize_queue import build_queue, group_key
from apps.books.context import current_book
from apps.journal.models import JournalLine
from apps.rules.models import Rule, RuleMatch
from apps.rules.services import feedback
from apps.teams.models import Team
from apps.teams.roles import ROLE_MEMBER
from apps.users.models import CustomUser

from .test_similar_categories import SimilarCategoriesTestMixin


class QueueFixtures(SimilarCategoriesTestMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        asset_group = AccountGroup.objects.get(book=cls.book, name="Bank")
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=asset_group, has_feed=True)

    def _row(self, *, merchant="", description="", amount="10.00", account=None, days_ago=0):
        return BankTransaction.objects.create(
            book=self.book,
            account=account or self.bank_account,
            posted_date=date.today() - timedelta(days=days_ago),
            description=description or merchant,
            merchant_name=merchant or None,
            amount=Decimal(amount),
            source=BankTransaction.SOURCE_CSV,
        )

    def _rule_suggestion(self, tx, category, name="Coffee rule"):
        rule = Rule.objects.create(book=self.book, name=name, category=category)
        return RuleMatch.objects.create(
            book=self.book,
            transaction=tx,
            rule=rule,
            rule_name=name,
            status=RuleMatch.STATUS_SUGGESTED,
            category=category,
        )

    def _queue(self):
        rows = BankTransaction.objects.filter(book=self.book, journal_entry__isnull=True).order_by(
            "-posted_date", "-pk"
        )
        return build_queue(self.book, rows.select_related("rule_match__category"))


class GroupingTest(QueueFixtures, TestCase):
    def test_same_merchant_in_one_account_is_one_group_newest_first(self):
        old = self._row(merchant="Blue Bottle", days_ago=3)
        new = self._row(merchant="BLUE BOTTLE", days_ago=1)

        (group,) = self._queue()

        self.assertEqual(group["ids"], [new.id, old.id])

    def test_descriptions_differing_only_in_numbers_group_together(self):
        a = self._row(description="SQ *BLUE BOTTLE 4417")
        b = self._row(description="SQ *BLUE BOTTLE 9920")

        self.assertEqual(group_key(a), group_key(b))

    def test_money_in_and_money_out_are_kept_apart(self):
        purchase = self._row(merchant="Amazon", amount="25.00")
        refund = self._row(merchant="Amazon", amount="-25.00")

        self.assertNotEqual(group_key(purchase), group_key(refund))

    def test_accounts_are_kept_apart(self):
        a = self._row(merchant="Amazon")
        b = self._row(merchant="Amazon", account=self.savings)

        self.assertNotEqual(group_key(a), group_key(b))

    def test_generic_wording_is_never_grouped(self):
        # Every cheque has the same wording, whoever it paid.
        a = self._row(description="CHECK 1042")
        b = self._row(description="CHECK 1043")
        c = self._row(description="ATM WITHDRAWAL 0001")

        self.assertEqual(len(self._queue()), 3)
        self.assertTrue(group_key(a).startswith("row:"))
        self.assertTrue(group_key(c).startswith("row:"))
        self.assertNotEqual(group_key(a), group_key(b))

    def test_rows_with_different_rule_suggestions_are_kept_apart(self):
        a = self._row(merchant="Blue Bottle")
        b = self._row(merchant="Blue Bottle")
        self._rule_suggestion(a, self.coffee)

        self.assertNotEqual(group_key(a), group_key(b))


class SuggestionAndConfidenceTest(QueueFixtures, TestCase):
    def test_a_consistent_payee_history_is_confident(self):
        for _ in range(3):
            self._categorized(self.coffee, merchant="Blue Bottle", posted_date=date.today() - timedelta(days=9))
        self._row(merchant="Blue Bottle")

        (group,) = self._queue()

        self.assertTrue(group["confident"])
        self.assertEqual(group["suggestions"][0]["category_id"], self.coffee.id)
        self.assertEqual(group["suggestions"][0]["count"], 3)
        self.assertEqual(group["suggestions"][0]["match_type"], "payee")

    def test_one_earlier_filing_is_not_enough(self):
        self._categorized(self.coffee, merchant="Blue Bottle", posted_date=date.today() - timedelta(days=9))
        self._row(merchant="Blue Bottle")

        (group,) = self._queue()

        self.assertFalse(group["confident"])
        self.assertEqual(group["suggestions"][0]["category_id"], self.coffee.id)

    def test_a_divided_history_is_not_confident(self):
        for category in (self.coffee, self.coffee, self.dining, self.dining):
            self._categorized(category, merchant="Blue Bottle", posted_date=date.today() - timedelta(days=9))
        self._row(merchant="Blue Bottle")

        (group,) = self._queue()

        self.assertFalse(group["confident"])
        self.assertEqual({s["category_id"] for s in group["suggestions"]}, {self.coffee.id, self.dining.id})

    def test_a_fuzzy_match_is_not_confident(self):
        for _ in range(3):
            self._categorized(self.coffee, description="BLUE BOTTLE COFFEE ROASTERS OAKLAND")
        self._row(description="BLUE BOTTLE COFFEE ROASTERS")

        (group,) = self._queue()

        self.assertEqual(group["suggestions"][0]["match_type"], "similar")
        self.assertFalse(group["confident"])

    def test_a_rule_suggestion_supersedes_history_and_is_confident(self):
        for _ in range(3):
            self._categorized(self.dining, merchant="Blue Bottle", posted_date=date.today() - timedelta(days=9))
        tx = self._row(merchant="Blue Bottle")
        self._rule_suggestion(tx, self.coffee)

        (group,) = self._queue()

        self.assertTrue(group["confident"])
        self.assertEqual(
            group["suggestions"],
            [
                {
                    "category_id": self.coffee.id,
                    "category_name": "Coffee",
                    "count": None,
                    "match_type": "rule",
                    "payee": "",
                    "rule_name": "Coffee rule",
                }
            ],
        )

    def test_confident_groups_come_first_then_the_largest(self):
        for _ in range(3):
            self._categorized(self.coffee, merchant="Blue Bottle", posted_date=date.today() - timedelta(days=9))
        confident = self._row(merchant="Blue Bottle", days_ago=5)
        big = [self._row(merchant="Lyft", days_ago=d) for d in (1, 2)]
        single = self._row(merchant="Corner Store", days_ago=0)

        queue = self._queue()

        self.assertEqual(
            [g["ids"] for g in queue],
            [[confident.id], [big[0].id, big[1].id], [single.id]],
        )


class CategorizeQueueEndpointTest(QueueFixtures, TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/categorize_queue/"

    def _get(self, params=None):
        with current_book(self.book):
            return self.client.get(self.url, params or {})

    def test_lists_the_uncategorized_rows_in_groups(self):
        a = self._row(merchant="Lyft", days_ago=2)
        b = self._row(merchant="Lyft", days_ago=1)
        self._categorized(self.coffee, merchant="Blue Bottle")

        response = self._get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([g["ids"] for g in response.data["groups"]], [[b.id, a.id]])

    def test_scoped_to_an_account_and_dates(self):
        self._row(merchant="Lyft", days_ago=40)
        recent = self._row(merchant="Lyft", days_ago=1)
        self._row(merchant="Lyft", account=self.savings)

        response = self._get(
            {"account": str(self.bank_account.id), "start_date": (date.today() - timedelta(days=7)).isoformat()}
        )

        self.assertEqual([g["ids"] for g in response.data["groups"]], [[recent.id]])

    def test_void_rows_are_not_in_the_queue(self):
        self._row(merchant="Lyft")
        BankTransaction.objects.filter(book=self.book).update(is_void=True)

        self.assertEqual(self._get().data["groups"], [])

    def test_another_teams_rows_are_not_listed(self):
        other = Team.objects.create(name="Other", slug="other-queue")
        other_group = AccountGroup.objects.create(book=other.default_book, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        other_account = Account.objects.create(
            book=other.default_book, name="Theirs", account_group=other_group, has_feed=True
        )
        BankTransaction.objects.create(
            book=other.default_book,
            account=other_account,
            posted_date=date.today(),
            description="Lyft",
            amount=Decimal("5"),
            source=BankTransaction.SOURCE_CSV,
        )

        self.assertEqual(self._get({"account": str(other_account.id)}).data["groups"], [])

    def test_bad_dates_are_a_400(self):
        self.assertEqual(self._get({"start_date": "soon"}).status_code, status.HTTP_400_BAD_REQUEST)

    def test_denied_for_anonymous(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)


class UncategorizeEndpointTest(QueueFixtures, TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/uncategorize/"

    def _post(self, ids):
        with current_book(self.book):
            return self.client.post(self.url, {"ids": ids}, format="json")

    def _filed(self, category=None, **kwargs):
        tx = self._row(**kwargs)
        create_entry(tx, category or self.coffee)
        tx.refresh_from_db()
        return tx

    def test_puts_rows_back_to_uncategorized(self):
        a, b = self._filed(merchant="Lyft"), self._filed(merchant="Lyft")
        entry_ids = [a.journal_entry_id, b.journal_entry_id]

        response = self._post([a.id, b.id])

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BankTransaction.objects.filter(id__in=[a.id, b.id], journal_entry__isnull=False).exists())
        self.assertFalse(JournalLine.objects.filter(journal_entry_id__in=entry_ids).exists())

    def test_keeps_the_payee_and_description(self):
        tx = self._filed(merchant="Renamed by me", description="Edited")

        self._post([tx.id])

        tx.refresh_from_db()
        self.assertEqual((tx.merchant_name, tx.description), ("Renamed by me", "Edited"))

    def test_a_transfers_mirror_leg_goes_with_it(self):
        tx = self._filed(category=self.savings, merchant="To savings")
        self.assertTrue(BankTransaction.objects.filter(account=self.savings, is_transfer_mirror=True).exists())

        self._post([tx.id])

        self.assertFalse(BankTransaction.objects.filter(account=self.savings, is_transfer_mirror=True).exists())

    def test_an_uncategorized_row_is_left_alone(self):
        tx = self._row(merchant="Lyft")

        self.assertEqual(self._post([tx.id]).status_code, status.HTTP_204_NO_CONTENT)

    def test_a_reconciled_row_refuses_the_whole_batch(self):
        ok = self._filed(merchant="Lyft")
        reconciled = self._filed(merchant="Lyft")
        JournalLine.objects.filter(journal_entry=reconciled.journal_entry, account=self.bank_account).update(
            is_reconciled=True
        )

        response = self._post([ok.id, reconciled.id])

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual([r["id"] for r in response.data["refused"]], [reconciled.id])
        ok.refresh_from_db()
        self.assertIsNotNone(ok.journal_entry_id)

    def test_a_void_row_is_refused(self):
        tx = self._filed(merchant="Lyft")
        BankTransaction.objects.filter(pk=tx.pk).update(is_void=True)

        self.assertEqual(self._post([tx.id]).status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_closed_period_is_refused(self):
        tx = self._filed(merchant="Lyft")
        self.book.locked_through = date.today()
        self.book.save(update_fields=["locked_through"])

        response = self._post([tx.id])

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        tx.refresh_from_db()
        self.assertIsNotNone(tx.journal_entry_id)

    def test_another_teams_row_is_not_found(self):
        other = Team.objects.create(name="Other", slug="other-undo")
        other_group = AccountGroup.objects.create(book=other.default_book, name="Bank", account_type=ACCOUNT_TYPE_ASSET)
        other_account = Account.objects.create(
            book=other.default_book, name="Theirs", account_group=other_group, has_feed=True
        )
        theirs = BankTransaction.objects.create(
            book=other.default_book,
            account=other_account,
            posted_date=date.today(),
            description="Lyft",
            amount=Decimal("5"),
            source=BankTransaction.SOURCE_CSV,
        )

        self.assertEqual(self._post([theirs.id]).status_code, status.HTTP_404_NOT_FOUND)

    def test_a_confirmed_rule_suggestion_stands_again(self):
        tx = self._row(merchant="Blue Bottle")
        match = self._rule_suggestion(tx, self.coffee)
        create_entry(tx, self.coffee)
        feedback.record([tx])
        match.rule.refresh_from_db()
        self.assertEqual((match.rule.times_confirmed, match.rule.confirm_streak), (1, 1))

        self._post([tx.id])

        match.refresh_from_db()
        match.rule.refresh_from_db()
        self.assertEqual(match.status, RuleMatch.STATUS_SUGGESTED)
        self.assertIsNone(match.resolved_at)
        self.assertEqual((match.rule.times_confirmed, match.rule.confirm_streak), (0, 0))

    def test_an_overridden_rule_suggestion_stands_again(self):
        tx = self._row(merchant="Blue Bottle")
        match = self._rule_suggestion(tx, self.coffee)
        create_entry(tx, self.dining)
        feedback.record([tx])

        self._post([tx.id])

        match.refresh_from_db()
        match.rule.refresh_from_db()
        self.assertEqual(match.status, RuleMatch.STATUS_SUGGESTED)
        self.assertEqual(match.rule.times_overridden, 0)

    def test_a_member_may_undo(self):
        member = CustomUser.objects.create_user(username="undo-member", password="pass")
        self.team.members.add(member, through_defaults={"role": ROLE_MEMBER})
        self.client.force_authenticate(user=member)
        tx = self._filed(merchant="Lyft")

        self.assertEqual(self._post([tx.id]).status_code, status.HTTP_204_NO_CONTENT)

    def test_denied_for_anonymous(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post(self.url, {"ids": [1]}, format="json").status_code, status.HTTP_403_FORBIDDEN)
