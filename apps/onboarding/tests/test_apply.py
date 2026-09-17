"""
The generated template must survive contact with the database.

`test_builder.py` checks the shape of what comes out of `build_template`; this
checks that the template engine can actually apply it -- the two halves of the
contract that would otherwise only meet in production.
"""

from django.test import TestCase

from apps.accounts.models import Account, AccountGroup
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry
from apps.onboarding.questions import QUESTION_CATALOG
from apps.onboarding.services.builder import build_template
from apps.teams.models import Team
from apps.teams.services.template_engine import apply_template


def _answer_everything() -> dict:
    return {q.id: [o.value for o in q.options] for q in QUESTION_CATALOG if q.options}


class ApplyGeneratedTemplateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.team = Team.objects.create(name="Generated", slug="generated")

    def test_minimal_answers_apply(self):
        apply_template(team=self.team, template=build_template({}))

        self.assertTrue(Account.objects.filter(team=self.team).exists())
        self.assertTrue(AccountGroup.objects.filter(team=self.team).exists())

    def test_maximal_answers_apply(self):
        """Every option at once is the widest the chart can get."""
        template = build_template(_answer_everything())
        apply_template(team=self.team, template=template)

        self.assertEqual(
            Account.objects.filter(team=self.team).count(),
            len(template["accounts"]),
        )
        self.assertEqual(
            AccountGroup.objects.filter(team=self.team).count(),
            len(template["account_groups"]),
        )

    def test_creates_no_transactions(self):
        """Same guarantee as the static template -- a new team's ledger is empty."""
        apply_template(team=self.team, template=build_template(_answer_everything()))

        self.assertFalse(BankTransaction.objects.filter(team=self.team).exists())
        self.assertFalse(JournalEntry.objects.filter(team=self.team).exists())

    def test_is_idempotent(self):
        """A double submit must not double the chart of accounts."""
        template = build_template(_answer_everything())
        apply_template(team=self.team, template=template)
        apply_template(team=self.team, template=template)

        self.assertEqual(Account.objects.filter(team=self.team).count(), len(template["accounts"]))

    def test_re_running_with_wider_answers_merges(self):
        """Changing an answer during review adds; it never destroys."""
        apply_template(team=self.team, template=build_template({"savings": ["tfsa"]}))
        apply_template(team=self.team, template=build_template({"savings": ["tfsa", "rrsp"]}))

        names = set(Account.objects.filter(team=self.team).values_list("name", flat=True))
        self.assertIn("TFSA", names)
        self.assertIn("RRSP", names)

    def test_sort_order_reaches_the_database(self):
        """Account numbers drive board and report ordering."""
        apply_template(team=self.team, template=build_template({}))

        chequing = Account.objects.get(team=self.team, name="Chequing Account")
        savings = Account.objects.get(team=self.team, name="Savings Account")
        self.assertEqual(chequing.sort_order, 1000)
        self.assertLess(chequing.sort_order, savings.sort_order)

    def test_account_types_come_from_their_group(self):
        """Type is derived from the group, so a misfiled account is a real bug."""
        apply_template(team=self.team, template=build_template(_answer_everything()))

        by_name = {a.name: a for a in Account.objects.filter(team=self.team).select_related("account_group")}
        self.assertEqual(by_name["Chequing Account"].account_group.account_type, "asset")
        self.assertEqual(by_name["Mortgage"].account_group.account_type, "liability")
        self.assertEqual(by_name["Salary Income"].account_group.account_type, "income")
        self.assertEqual(by_name["Groceries"].account_group.account_type, "expense")

    def test_teams_are_isolated(self):
        other = Team.objects.create(name="Other", slug="other-generated")
        apply_template(team=self.team, template=build_template({"savings": ["tfsa"]}))

        self.assertFalse(Account.objects.filter(team=other).exists())
