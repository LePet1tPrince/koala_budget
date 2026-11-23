"""
The pickers the feed pages and the transaction editor load (`feed/pickers/`,
`journal/api/transactions/pickers/`), which replaced their `json_script` props.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_BUDGET,
    ACCOUNT_TYPE_EXPENSE,
    Account,
    AccountGroup,
    Payee,
)
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser


class PickersTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Pickers", slug="pickers")
        cls.book = cls.team.default_book
        cls.admin = CustomUser.objects.create_user(username="pick-admin", password="pass")
        cls.member = CustomUser.objects.create_user(username="pick-member", password="pass")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        spend = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.buckets = AccountGroup.objects.create(book=cls.book, name="Buckets", account_type=ACCOUNT_TYPE_BUDGET)
        cls.chequing = Account.objects.create(book=cls.book, name="Chequing", account_group=banks, has_feed=True)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=spend)
        cls.bucket = Account.objects.create(book=cls.book, name="Groceries bucket", account_group=cls.buckets)
        Payee.objects.create(book=cls.book, name="Metro")

        other_team = Team.objects.create(name="Other", slug="other-pickers")
        cls.outsider = CustomUser.objects.create_user(username="pick-outsider", password="pass")
        other_team.members.add(cls.outsider, through_defaults={"role": ROLE_ADMIN})

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(user=self.member)

    def feed(self):
        return self.api.get(reverse("bank_feed:bank-feed-pickers", args=self.book.url_args))

    def transactions(self):
        return self.api.get(reverse("journal:transaction-pickers", args=self.book.url_args))

    def test_feed_pickers(self):
        response = self.feed()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        names = [a["name"] for a in data["accounts"]]
        self.assertEqual(names, sorted(names))
        self.assertIn("Groceries", names)
        self.assertNotIn("Groceries bucket", names)
        self.assertIn("is_goal", data["accounts"][0])
        self.assertEqual([p["name"] for p in data["payees"]], ["Metro"])
        self.assertNotIn(self.buckets.id, {g["id"] for g in data["account_groups"]})
        self.assertEqual({g["name"] for g in data["account_groups"]}, {"Banks", "Spending"})

    def test_transaction_pickers(self):
        response = self.transactions()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        names = [a["name"] for a in data["accounts"]]
        self.assertIn("Chequing", names)
        self.assertNotIn("Groceries bucket", names)
        self.assertEqual([p["name"] for p in data["payees"]], ["Metro"])

    def test_strangers_and_anonymous_are_refused(self):
        self.api.force_authenticate(user=self.outsider)
        self.assertIn(self.feed().status_code, (403, 404))
        self.assertIn(self.transactions().status_code, (403, 404))
        self.api.force_authenticate(user=None)
        self.assertIn(self.feed().status_code, (401, 403))
        self.assertIn(self.transactions().status_code, (401, 403))

    def test_pages_carry_no_picker_props(self):
        self.client.force_login(self.member)
        for name in ("bank_feed:bank_feed_home", "bank_feed:categorize_mode", "journal:transactions_home"):
            with self.subTest(name):
                response = self.client.get(reverse(name, args=self.book.url_args))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="book-base"')
                self.assertNotContains(response, 'id="all-accounts"')
                self.assertNotContains(response, 'id="all-payees"')

    def test_create_account_validates(self):
        url = reverse("bank_feed:bank-feed-create-account", args=self.book.url_args)
        response = self.api.post(url, {"name": "", "account_group_id": self.buckets.id}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.api.post(url, {"name": "Rent", "account_group_id": self.buckets.id}, format="json")
        self.assertEqual(response.status_code, 404)  # a budget bucket group is not offered
