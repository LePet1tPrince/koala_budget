"""
Tests for turning answers into a chart of accounts.

`build_template` is a pure function, so these are `SimpleTestCase` -- no database
needed. The test that it actually applies cleanly lives in `test_apply.py`, which
does touch the database.
"""

from django.test import SimpleTestCase

from apps.onboarding.coa_rules import BASE_GRANT
from apps.onboarding.questions import QUESTION_CATALOG, Question
from apps.onboarding.services.builder import build_template, unanswered_required


def _answer_everything() -> dict:
    """Select every option of every question -- the maximal chart of accounts."""
    answers = {}
    for question in QUESTION_CATALOG:
        if question.options:
            answers[question.id] = [option.value for option in question.options]
    return answers


def _names(template: dict) -> list[str]:
    return [a["name"] for a in template["accounts"]]


class BaseTemplateTest(SimpleTestCase):
    def test_empty_answers_still_produce_a_usable_chart(self):
        """Someone who skips every question still needs books to work in."""
        template = build_template({})

        self.assertEqual(set(_names(template)), {a.name for a in BASE_GRANT.accounts})
        self.assertTrue(template["account_groups"])
        self.assertTrue(template["payees"])

    def test_base_includes_the_equity_offset_account(self):
        """Opening balances and reconciliation both post against it."""
        template = build_template({})
        system = [a for a in template["accounts"] if a["is_system"]]
        self.assertTrue(system, "no system equity account in the base chart")

    def test_chequing_has_a_feed(self):
        """Task 1 uploads a CSV to a feed account, so one must exist from the start."""
        template = build_template({})
        self.assertTrue([a for a in template["accounts"] if a["has_feed"]])


class GrantsTest(SimpleTestCase):
    def test_selected_option_adds_its_accounts(self):
        template = build_template({"housing": "rent"})
        self.assertIn("Rent", _names(template))
        self.assertIn("Tenant Insurance", _names(template))

    def test_unselected_option_adds_nothing(self):
        template = build_template({"housing": "rent"})
        self.assertNotIn("Mortgage", _names(template))

    def test_mortgage_creates_both_the_liability_and_the_expense(self):
        template = build_template({"housing": "mortgage"})
        names = _names(template)
        self.assertIn("Mortgage", names)
        self.assertIn("Mortgage Interest", names)

    def test_multi_select_accumulates(self):
        template = build_template({"savings": ["tfsa", "rrsp"]})
        names = _names(template)
        self.assertIn("TFSA", names)
        self.assertIn("RRSP", names)
        self.assertNotIn("RESP", names)

    def test_a_single_value_is_accepted_where_a_list_was_expected(self):
        """Clients send a bare string for a one-item multi-select often enough."""
        template = build_template({"savings": "tfsa"})
        self.assertIn("TFSA", _names(template))


class DependentGrantTest(SimpleTestCase):
    def test_dependency_fires_when_satisfied(self):
        template = build_template({"income_sources": ["employment"], "household_shape": "partner"})
        self.assertIn("Salary Income — Partner", _names(template))

    def test_dependency_stays_quiet_when_unsatisfied(self):
        """A partner's salary account is noise for a household with no employment income."""
        template = build_template({"income_sources": ["pension"], "household_shape": "partner"})
        self.assertNotIn("Salary Income — Partner", _names(template))


class DeduplicationTest(SimpleTestCase):
    def test_two_answers_wanting_the_same_account_produce_one(self):
        """A mortgage and a rental property both want Property Tax."""
        template = build_template({"housing": "mortgage", "income_sources": ["rental"]})
        names = _names(template)
        self.assertEqual(names.count("Property Tax"), 1)

    def test_maximal_answers_have_no_duplicates(self):
        template = build_template(_answer_everything())

        names = _names(template)
        self.assertEqual(len(names), len(set(names)), "duplicate account names in the maximal chart")

        groups = [g["name"] for g in template["account_groups"]]
        self.assertEqual(len(groups), len(set(groups)), "duplicate group names in the maximal chart")

    def test_two_cars_produce_one_vehicle_account(self):
        template = build_template({"transport": ["car_loan", "car_owned"]})
        self.assertEqual(_names(template).count("Vehicle"), 1)
        # The loan still comes along -- it was earned by the first option.
        self.assertIn("Car Loan", _names(template))


class IntegrityTest(SimpleTestCase):
    def test_every_account_names_a_declared_group(self):
        """The engine looks groups up by name, so a miss would be a KeyError."""
        template = build_template(_answer_everything())
        declared = {g["name"] for g in template["account_groups"]}
        for account in template["accounts"]:
            with self.subTest(account=account["name"]):
                self.assertIn(account["group"], declared)

    def test_no_empty_groups(self):
        """A group with nothing in it is clutter on the accounts board."""
        template = build_template(_answer_everything())
        used = {a["group"] for a in template["accounts"]}
        for group in template["account_groups"]:
            with self.subTest(group=group["name"]):
                self.assertIn(group["name"], used)

    def test_accounts_carry_sort_order(self):
        """Account numbers drive board order, so they must survive into the template."""
        template = build_template(_answer_everything())
        numbered = [a for a in template["accounts"] if a["number"] is not None]
        self.assertTrue(numbered)
        for account in numbered:
            with self.subTest(account=account["name"]):
                self.assertEqual(account["sort_order"], account["number"])

    def test_is_deterministic(self):
        answers = _answer_everything()
        self.assertEqual(build_template(answers), build_template(answers))


class UnknownAnswerTest(SimpleTestCase):
    """
    Answers outlive the catalog that produced them. A stored answer naming a
    question or option that no longer exists must be ignored, not raise -- the
    whole point of making the catalog editable.
    """

    def test_unknown_question_is_ignored(self):
        self.assertEqual(build_template({"a_question_we_deleted": "yes"}), build_template({}))

    def test_unknown_option_is_ignored(self):
        self.assertEqual(build_template({"housing": "houseboat"}), build_template({}))

    def test_unknown_option_among_known_ones_is_dropped(self):
        template = build_template({"savings": ["tfsa", "crypto_mattress"]})
        self.assertIn("TFSA", _names(template))

    def test_wrong_type_is_ignored(self):
        self.assertEqual(build_template({"savings": 42}), build_template({}))
        self.assertEqual(build_template({"savings": [1, 2]}), build_template({}))


class RequiredAnswersTest(SimpleTestCase):
    def test_empty_answers_are_all_missing(self):
        required = {q.id for q in QUESTION_CATALOG if q.required}
        self.assertEqual(set(unanswered_required({})), required)

    def test_answering_everything_leaves_nothing_missing(self):
        self.assertEqual(unanswered_required(_answer_everything()), [])

    def test_an_unknown_option_does_not_count_as_answered(self):
        """Otherwise a junk payload would satisfy a required question."""
        answers = _answer_everything()
        first_required: Question = next(q for q in QUESTION_CATALOG if q.required)
        answers[first_required.id] = ["not_a_real_option"]
        self.assertIn(first_required.id, unanswered_required(answers))
