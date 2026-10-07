"""
The Inbox table paged on the server (`services/feed_query.py`).

The filter semantics are ported from the client (`LineTable.jsx`), so these tests
pin them as a table: which rows each view / quick filter shows, what the badge
counts are, how each column sorts, and that paging, "select all matching" and
"which page is this row on" all describe the same ordered set.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
)
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services import feed_query
from apps.bank_feed.services.categorize import categorize_single
from apps.bank_feed.services.splits import apply_splits
from apps.bank_feed.services.transfer_mirror import sync_transfer
from apps.books.context import current_book
from apps.journal.models import JournalLine
from apps.journal.services import voiding
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN
from apps.users.models import CustomUser

D = Decimal


class FeedFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Feed Team", slug="feed-team")
        cls.book = cls.team.default_book
        cls.user = CustomUser.objects.create_user(username="feeder", password="pass")
        cls.team.members.add(cls.user, through_defaults={"role": ROLE_ADMIN})
        banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET, sort_order=0)
        cards = AccountGroup.objects.create(
            book=cls.book, name="Cards", account_type=ACCOUNT_TYPE_LIABILITY, sort_order=0
        )
        spend = AccountGroup.objects.create(book=cls.book, name="Spend", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.checking = Account.objects.create(
            book=cls.book, name="Checking", account_group=banks, has_feed=True, sort_order=0
        )
        cls.savings = Account.objects.create(
            book=cls.book, name="Savings", account_group=banks, has_feed=True, sort_order=1
        )
        cls.card = Account.objects.create(book=cls.book, name="Visa", account_group=cards, has_feed=True)
        cls.hidden = Account.objects.create(book=cls.book, name="Hidden", account_group=banks, has_feed=False)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=spend)
        cls.dining = Account.objects.create(book=cls.book, name="Dining", account_group=spend)
        cls.rent = Account.objects.create(book=cls.book, name="Rent", account_group=spend)

        def row(account, amount, day, description, **kwargs):
            return BankTransaction.objects.create(
                book=cls.book,
                account=account,
                amount=D(amount),
                posted_date=date(2026, 3, day),
                description=description,
                merchant_name=kwargs.pop("merchant", description),
                source=BankTransaction.SOURCE_CSV,
                **kwargs,
            )

        def categorized(tx, category, reconciled=False):
            categorize_single(tx, category)
            if reconciled:
                JournalLine.objects.filter(journal_entry_id=tx.journal_entry_id, account_id=tx.account_id).update(
                    is_reconciled=True
                )
            tx.refresh_from_db()
            return tx

        cls.uncategorized = row(cls.checking, "12.00", 1, "Waiting")
        cls.groceries_tx = categorized(row(cls.checking, "40.00", 2, "Market"), cls.groceries)
        cls.reconciled = categorized(row(cls.checking, "25.00", 3, "Cafe"), cls.dining, reconciled=True)
        cls.income = categorized(row(cls.savings, "-100.00", 4, "Interest", merchant=None), cls.groceries)
        split = categorized(row(cls.checking, "60.00", 5, "Split shop"), cls.groceries)
        apply_splits(split, [(cls.groceries, D("45.00")), (cls.dining, D("15.00"))], total=D("60.00"))
        split.refresh_from_db()
        cls.split = split
        cls.transfer = categorized(row(cls.checking, "200.00", 6, "Card payment"), cls.card)
        cls.mirror = BankTransaction.objects.get(journal_entry=cls.transfer.journal_entry, is_transfer_mirror=True)
        cls.void = row(cls.card, "9.00", 7, "Duplicate")
        voiding.void(rows=[cls.void])
        cls.hidden_tx = row(cls.hidden, "5.00", 8, "Not in the Inbox")
        # A possible duplicate transfer: out of checking, into savings, same amount, a day apart.
        cls.pair_out = row(cls.checking, "300.00", 10, "To savings")
        cls.pair_in = row(cls.savings, "-300.00", 11, "From checking")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def url(self, path=""):
        return f"/a/{self.team.slug}/{self.book.slug}/bankfeed/api/feed/{path}"

    def get(self, path="", **params):
        with current_book(self.book):
            return self.client.get(self.url(path), params)

    def ids(self, **params):
        params.setdefault("page_size", 200)
        resp = self.get(**params)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        return [int(r["id"]) for r in resp.data["results"]]


class FilterTest(FeedFixture):
    def test_no_account_means_every_feed_account_and_nothing_hidden(self):
        ids = set(self.ids())
        self.assertNotIn(self.hidden_tx.id, ids)
        self.assertIn(self.mirror.id, ids)  # both legs of a transfer, each in its own account
        self.assertIn(self.transfer.id, ids)

    def test_account_list(self):
        ids = set(self.ids(account=f"{self.savings.id},{self.card.id}"))
        self.assertEqual(ids, {self.income.id, self.mirror.id, self.void.id, self.pair_in.id})

    def test_a_named_account_is_shown_even_when_hidden_from_the_inbox(self):
        self.assertEqual(self.ids(account=self.hidden.id), [self.hidden_tx.id])

    def test_views_and_quick_filters(self):
        active = {
            self.uncategorized.id,
            self.groceries_tx.id,
            self.reconciled.id,
            self.income.id,
            self.split.id,
            self.transfer.id,
            self.mirror.id,
            self.pair_out.id,
            self.pair_in.id,
        }
        cases = {
            "active": ({"view": "active"}, active),
            "voided": ({"view": "voided"}, {self.void.id}),
            "to review": ({"view": "active", "to_review": 1}, active - {self.reconciled.id}),
            "reconciled": ({"view": "active", "reconciled": 1}, {self.reconciled.id}),
            # A split has an entry: it is categorized, whatever its null category says.
            "uncategorized": (
                {"view": "active", "uncategorized": 1},
                {self.uncategorized.id, self.pair_out.id, self.pair_in.id},
            ),
            "uncategorized + to review": (
                {"view": "active", "uncategorized": 1, "to_review": 1},
                {self.uncategorized.id, self.pair_out.id, self.pair_in.id},
            ),
            "dates": (
                {"view": "active", "start_date": "2026-03-02", "end_date": "2026-03-04"},
                {self.groceries_tx.id, self.reconciled.id, self.income.id},
            ),
            "transfers": ({"view": "active", "transfers": 1}, {self.pair_out.id, self.pair_in.id}),
            "ids": ({"ids": f"{self.void.id},{self.split.id}"}, {self.void.id, self.split.id}),
        }
        for name, (params, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(set(self.ids(**params)), expected)

    def test_categorize_modes_request_is_unchanged(self):
        """`?uncategorized=1` alone: no void rows, default page size of 200."""
        resp = self.get(uncategorized=1)
        ids = {int(r["id"]) for r in resp.data["results"]}
        self.assertEqual(ids, {self.uncategorized.id, self.pair_out.id, self.pair_in.id})
        self.assertNotIn("counts", resp.data)

    def test_bad_params_are_refused(self):
        for params in (
            {"to_review": 1, "reconciled": 1},
            {"page_size": 30},
            {"sort": "amount"},
            {"view": "archived"},
            {"account": "one,two"},
            {"start_date": "March"},
        ):
            with self.subTest(params):
                self.assertEqual(self.get(**params).status_code, status.HTTP_400_BAD_REQUEST)


class CountsTest(FeedFixture):
    def test_counts_ignore_quick_filters_dates_and_view(self):
        expected = {"to_review": 8, "reconciled": 1, "uncategorized": 3, "voided": 1}
        for params in ({}, {"view": "voided"}, {"view": "active", "reconciled": 1, "start_date": "2026-03-20"}):
            with self.subTest(params):
                resp = self.get(counts=1, **params)
                self.assertEqual(resp.data["counts"], expected)

    def test_counts_follow_the_account_filter(self):
        resp = self.get(counts=1, account=self.card.id)
        self.assertEqual(resp.data["counts"], {"to_review": 1, "reconciled": 0, "uncategorized": 0, "voided": 1})


class SortTest(FeedFixture):
    def test_default_is_newest_first(self):
        dates = [r["posted_date"] for r in self.get(view="active", page_size=200).data["results"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_category_sorts_by_what_the_cell_shows(self):
        rows = {
            int(r["id"]): r
            for r in self.get(view="active", account=self.checking.id, sort="category", page_size=200).data["results"]
        }
        order = self.ids(view="active", account=self.checking.id, sort="category")
        labels = []
        for row_id in order:
            row = rows[row_id]
            if row["is_split"]:
                labels.append("split")
            else:
                labels.append((row["category"] or {}).get("name", "").lower())
        self.assertEqual(labels, sorted(labels))
        self.assertEqual(labels[0], "")  # uncategorized first

    def test_a_split_mirror_sorts_as_its_splits_account(self):
        apply_splits(
            self.split,
            [(self.groceries, D("40.00")), (self.savings, D("20.00"))],
            total=D("60.00"),
        )
        sync_transfer(self.split)
        mirror = BankTransaction.objects.get(journal_entry=self.split.journal_entry, is_transfer_mirror=True)
        rows = feed_query.ordered(
            feed_query.filtered(self.book, feed_query.FeedParams(accounts=(self.savings.id,), sort="category")),
            feed_query.FeedParams(sort="category"),
        )
        labels = {r.pk: r._category_sort for r in rows}
        self.assertEqual(labels[mirror.pk], "checking")

    def test_every_key_both_directions_pages_through_every_row_once(self):
        expected = set(self.ids(view="active"))
        for key in feed_query.SORT_KEYS:
            for direction in ("asc", "desc"):
                with self.subTest(key=key, dir=direction):
                    seen = []
                    page = 1
                    while True:
                        resp = self.get(view="active", sort=key, dir=direction, page_size=10, page=page)
                        seen += [int(r["id"]) for r in resp.data["results"]]
                        if not resp.data["next"]:
                            break
                        page += 1
                    self.assertEqual(len(seen), len(set(seen)))
                    self.assertEqual(set(seen), expected)

    def test_amount_columns(self):
        inflow_first = self.ids(view="active", sort="inflow", dir="desc")
        self.assertEqual(inflow_first[0], self.pair_in.id)  # $300 in
        outflow_first = self.ids(view="active", sort="outflow", dir="desc")
        self.assertEqual(outflow_first[0], self.pair_out.id)  # $300 out

    def test_account_sorts_in_board_order(self):
        order = self.ids(sort="account")
        accounts = [BankTransaction.objects.get(pk=i).account_id for i in order]
        # assets (checking, savings by sort_order) before liabilities (card)
        first_card = accounts.index(self.card.id)
        self.assertTrue(all(a == self.card.id for a in accounts[first_card:]))
        self.assertLess(accounts.index(self.checking.id), accounts.index(self.savings.id))


class QueryCountTest(FeedFixture):
    def test_a_page_costs_the_same_however_large_the_book(self):
        def queries():
            with CaptureQueriesContext(connection) as ctx:
                # Newest first: the fillers below are older, so page 1 holds the same kinds of
                # rows both times and only the size of the book changes.
                self.assertEqual(self.get(view="active", page_size=10, counts=1).status_code, 200)
            return len(ctx.captured_queries)

        small = queries()
        for i in range(60):
            BankTransaction.objects.create(
                book=self.book,
                account=self.checking,
                amount=D("1.00"),
                posted_date=date(2025, 1, 1) + timedelta(days=i),
                description=f"Filler {i}",
            )
        self.assertEqual(queries(), small)


class SelectionTest(FeedFixture):
    def test_every_match_in_the_shape_the_batch_bar_reads(self):
        resp = self.get("selection/", view="active", account=self.checking.id)
        self.assertEqual(resp.status_code, 200)
        by_id = {r["id"]: r for r in resp.data["results"]}
        self.assertEqual(resp.data["count"], len(by_id))
        self.assertEqual(set(by_id), set(self.ids(view="active", account=self.checking.id)))

        self.assertTrue(by_id[self.reconciled.id]["is_reconciled"])
        self.assertEqual(by_id[self.reconciled.id]["outflow"], "25.00")
        self.assertIsNone(by_id[self.uncategorized.id]["category"])
        self.assertIsNone(by_id[self.split.id]["category"])
        self.assertTrue(by_id[self.split.id]["is_split"])
        self.assertEqual(by_id[self.groceries_tx.id]["category"], {"id": self.groceries.id})
        self.assertEqual(by_id[self.groceries_tx.id]["account"], {"id": self.checking.id})

    def test_too_many_matches_are_refused_with_the_count(self):
        with mock.patch.object(feed_query, "MAX_IDS", 3):
            resp = self.get("selection/", view="active")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["count"], 9)


class LocateTest(FeedFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Enough rows that the fixture's spread over several pages of 10, whatever the sort.
        BankTransaction.objects.bulk_create(
            BankTransaction(
                book=cls.book,
                account=cls.savings,
                amount=D(f"{i + 1}.00"),
                posted_date=date(2026, 3, 1) + timedelta(days=i % 20),
                description=f"Filler {i:02d}",
                merchant_name=f"Filler {i:02d}",
                source=BankTransaction.SOURCE_CSV,
            )
            for i in range(25)
        )

    def test_the_page_a_row_is_on_matches_the_list(self):
        for params in ({}, {"sort": "payee"}, {"sort": "category", "dir": "desc"}, {"sort": "inflow"}):
            order = self.ids(view="active", **params)
            for target in (self.pair_in, self.split, self.uncategorized, self.groceries_tx):
                with self.subTest(params=params, row=target.description):
                    resp = self.get("locate/", view="active", page_size=10, row=target.id, **params)
                    self.assertEqual(resp.data["page"], order.index(target.id) // 10 + 1)
        # The fixture really is spread: a row past the first page is located past it.
        self.assertGreater(self.get("locate/", view="active", page_size=10, row=self.uncategorized.id).data["page"], 1)

    def test_the_other_leg_of_a_transfer(self):
        resp = self.get(
            "locate/",
            view="active",
            page_size=10,
            journal_entry=self.transfer.journal_entry_id,
            in_account=self.card.id,
        )
        self.assertEqual(resp.data["id"], self.mirror.id)
        self.assertIsNotNone(resp.data["page"])

    def test_a_row_the_filters_hide_has_no_page(self):
        resp = self.get("locate/", view="active", row=self.void.id)
        self.assertEqual(resp.data, {"id": self.void.id, "page": None, "is_void": True})

    def test_an_unknown_row(self):
        self.assertEqual(self.get("locate/", row=999999).data["id"], None)
        self.assertEqual(self.get("locate/").status_code, 400)


class BatchAcrossAccountsTest(FeedFixture):
    def patch(self, data):
        with current_book(self.book):
            return self.client.patch(self.url("batch_edit/"), data, format="json")

    def test_category_on_both_legs_of_a_transfer_leaves_the_mirror_to_follow(self):
        resp = self.patch({"ids": [self.transfer.id, self.mirror.id], "category_id": self.savings.id})
        self.assertEqual(resp.status_code, 204, resp.data)
        self.transfer.refresh_from_db()
        self.assertTrue(
            BankTransaction.objects.filter(
                journal_entry=self.transfer.journal_entry, account=self.savings, is_transfer_mirror=True
            ).exists()
        )
        self.assertFalse(BankTransaction.objects.filter(pk=self.mirror.pk, account=self.card).exists())

    def test_a_mirror_alone_cannot_take_a_spending_category(self):
        resp = self.patch({"ids": [self.mirror.id], "category_id": self.groceries.id})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["refused"][0]["id"], self.mirror.id)

    def test_moving_a_row_into_its_own_category_account_is_refused(self):
        resp = self.patch({"ids": [self.transfer.id, self.groceries_tx.id], "account_id": self.card.id})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual([r["id"] for r in resp.data["refused"]], [self.transfer.id])
        self.groceries_tx.refresh_from_db()
        self.assertEqual(self.groceries_tx.account_id, self.checking.id)  # nothing written

    def test_refusals_name_every_row(self):
        resp = self.patch({"ids": [self.split.id, self.void.id, self.groceries_tx.id], "category_id": self.rent.id})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual({r["id"] for r in resp.data["refused"]}, {self.split.id, self.void.id})

    def test_duplicate_skips_mirror_legs(self):
        with current_book(self.book):
            resp = self.client.post(
                self.url("batch_duplicate/"), {"ids": [self.mirror.id, self.groceries_tx.id]}, format="json"
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r["description"] for r in resp.data], ["Market"])

    def test_more_than_the_cap_is_refused(self):
        resp = self.patch({"ids": list(range(1, 1002)), "payee": "x"})
        self.assertEqual(resp.status_code, 400)
