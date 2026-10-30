"""Shared fixtures for the Plaid tests: a book with a checking account linked to a Plaid item."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.plaid.models import PlaidAccount, PlaidItem
from apps.teams.models import Team
from apps.teams.roles import ROLE_ADMIN, ROLE_MEMBER
from apps.users.models import CustomUser


class PlaidBookTestCase(TestCase):
    """A team whose book has a checking account fed by one Plaid item."""

    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Plaid Team", slug="plaid-team")
        cls.book = cls.team.default_book
        cls.admin = CustomUser.objects.create_user(username="plaid-admin", password="pass")
        cls.team.members.add(cls.admin, through_defaults={"role": ROLE_ADMIN})
        cls.member = CustomUser.objects.create_user(username="plaid-member", password="pass")
        cls.team.members.add(cls.member, through_defaults={"role": ROLE_MEMBER})
        cls.outsider = CustomUser.objects.create_user(username="plaid-outsider", password="pass")

        banks = AccountGroup.objects.create(book=cls.book, name="Banks", account_type=ACCOUNT_TYPE_ASSET)
        cls.checking = Account.objects.create(book=cls.book, name="Checking", account_group=banks, has_feed=True)
        cls.savings = Account.objects.create(book=cls.book, name="Savings", account_group=banks, has_feed=True)
        spending = AccountGroup.objects.create(book=cls.book, name="Spending", account_type=ACCOUNT_TYPE_EXPENSE)
        cls.groceries = Account.objects.create(book=cls.book, name="Groceries", account_group=spending)
        cls.dining = Account.objects.create(book=cls.book, name="Dining", account_group=spending)

    def setUp(self):
        self.item = PlaidItem.objects.create(
            book=self.book,
            plaid_item_id="item-1",
            access_token="access-sandbox-1",
            institution_name="RBC Royal Bank",
            institution_id="ins_rbc",
            cursor="c0",
        )
        self.plaid_checking = PlaidAccount.objects.create(
            book=self.book,
            item=self.item,
            account=self.checking,
            plaid_account_id="acc-checking",
            name="Chequing",
            mask="1234",
            subtype="checking",
            type="depository",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def url(self, path):
        return f"/a/{self.team.slug}/{self.book.slug}/plaid/api/{path}"
