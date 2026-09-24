"""
Tests for team bootstrap (apply_template).

The point of these tests is that bootstrap creates *structure only*. New teams
used to be seeded with 18 months of invented bank transactions, which meant a
user's first import landed on top of fabricated history and their net worth
chart was fiction. These tests lock that seed out.
"""

from django.test import TestCase

from apps.accounts.models import Account, AccountGroup, Payee
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry
from apps.teams.models import Team
from apps.teams.services.template_budget import PERSONAL_BUDGET_TEMPLATE
from apps.teams.services.template_engine import apply_template


class ApplyTemplateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Bootstrap Team", slug="bootstrap-team")
        cls.book = cls.team.default_book

    def test_creates_structure(self):
        apply_template(book=self.book, template=PERSONAL_BUDGET_TEMPLATE)

        self.assertEqual(
            AccountGroup.objects.filter(book=self.book).count(),
            len(PERSONAL_BUDGET_TEMPLATE["account_groups"]),
        )
        self.assertEqual(
            Account.objects.filter(book=self.book).count(),
            len(PERSONAL_BUDGET_TEMPLATE["accounts"]),
        )
        self.assertEqual(
            Payee.objects.filter(book=self.book).count(),
            len(PERSONAL_BUDGET_TEMPLATE["payees"]),
        )

    def test_creates_no_transactions(self):
        """A brand new team starts with an empty ledger -- no invented history."""
        apply_template(book=self.book, template=PERSONAL_BUDGET_TEMPLATE)

        self.assertFalse(BankTransaction.objects.filter(book=self.book).exists())
        self.assertFalse(JournalEntry.objects.filter(book=self.book).exists())

    def test_is_idempotent(self):
        apply_template(book=self.book, template=PERSONAL_BUDGET_TEMPLATE)
        apply_template(book=self.book, template=PERSONAL_BUDGET_TEMPLATE)

        self.assertEqual(
            Account.objects.filter(book=self.book).count(),
            len(PERSONAL_BUDGET_TEMPLATE["accounts"]),
        )

    def test_template_declares_no_sample_transactions(self):
        """Guard the data as well as the engine -- neither half may bring the seed back."""
        self.assertNotIn("sample_transactions", PERSONAL_BUDGET_TEMPLATE)
