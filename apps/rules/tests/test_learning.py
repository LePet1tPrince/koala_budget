"""The nightly learner: propose a rule only for a consistent, uncovered merchant."""

from apps.bank_feed.services.categorize import create_entry
from apps.books.context import current_book
from apps.rules.models import RuleProposal
from apps.rules.services.learning import propose
from apps.rules.tasks import learn_rules

from .base import RulesTestCase


class LearningTest(RulesTestCase):
    def history(self, payee, categories):
        with current_book(self.book):
            for category in categories:
                create_entry(self.tx(f"{payee} 1234", "8.00", payee=payee), category)

    def test_four_of_four_is_proposed(self):
        self.history("Corner Store", [self.groceries] * 4)
        self.assertEqual(propose(self.book), 1)
        proposal = RuleProposal.objects.get(book=self.book)
        self.assertEqual(
            (proposal.value, proposal.category, proposal.direction, proposal.evidence_count),
            ("corner store", self.groceries, "out", 4),
        )

    def test_three_of_four_is_not(self):
        self.history("Corner Store", [self.groceries] * 3 + [self.dining])
        self.assertEqual(propose(self.book), 0)

    def test_too_few_is_not(self):
        self.history("Corner Store", [self.groceries] * 3)
        self.assertEqual(propose(self.book), 0)

    def test_a_dismissed_proposal_is_never_resurrected(self):
        self.history("Corner Store", [self.groceries] * 4)
        propose(self.book)
        RuleProposal.objects.update(status=RuleProposal.STATUS_DISMISSED)
        self.history("Corner Store", [self.groceries] * 2)
        propose(self.book)
        self.assertEqual(RuleProposal.objects.get().status, RuleProposal.STATUS_DISMISSED)

    def test_a_merchant_a_rule_already_covers_is_not_proposed(self):
        self.history("Corner Store", [self.groceries] * 4)
        self.rule(conditions=[{"field": "payee", "op": "contains", "value": "corner"}], category=self.groceries)
        self.assertEqual(propose(self.book), 0)

    def test_a_stale_open_proposal_is_dropped(self):
        self.history("Corner Store", [self.groceries] * 4)
        propose(self.book)
        self.rule(conditions=[{"field": "payee", "op": "contains", "value": "corner"}], category=self.groceries)
        propose(self.book)
        self.assertFalse(RuleProposal.objects.exists())

    def test_the_task_covers_active_books(self):
        self.history("Corner Store", [self.groceries] * 4)
        self.assertEqual(learn_rules(), 1)
