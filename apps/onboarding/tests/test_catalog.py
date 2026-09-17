"""
Tests for the question catalog.

The catalog is meant to be edited -- questions added, cut, reordered -- so these
tests are the safety net that makes editing it safe. They assert the catalog is
*coherent*, not that it currently holds any particular number of questions:
hardcoding a count here would mean every trim breaks a test for no reason.
"""

from django.test import SimpleTestCase

from apps.onboarding.coa_rules import BASE_GRANT
from apps.onboarding.questions import (
    CURRENCY,
    MULTI,
    PHASE_ORDER,
    QUESTION_CATALOG,
    SINGLE,
    active_phases,
    catalog_payload,
    get_question,
    questions_for_phase,
    required_question_ids,
    validate_catalog,
)


class CatalogCoherenceTest(SimpleTestCase):
    def test_catalog_is_valid(self):
        """Ids unique, options present and unique, dependencies resolvable."""
        self.assertEqual(validate_catalog(), [])

    def test_every_question_is_in_a_known_phase(self):
        for question in QUESTION_CATALOG:
            with self.subTest(question=question.id):
                self.assertIn(question.phase, PHASE_ORDER)

    def test_every_phase_is_reachable(self):
        """A phase in PHASE_ORDER with no questions would be a dead step."""
        self.assertEqual(set(active_phases()), {q.phase for q in QUESTION_CATALOG})

    def test_option_grants_reference_declared_groups(self):
        """
        Every account an option can create names a group that something declares.

        This is what stops a cut question from orphaning an account: if the only
        grant that declared a group is removed, the accounts still pointing at it
        surface here.
        """
        declared = {g.name for g in BASE_GRANT.groups}
        for question in QUESTION_CATALOG:
            for option in question.options:
                declared.update(g.name for g in option.grant.groups)

        for question in QUESTION_CATALOG:
            for option in question.options:
                for account in option.grant.accounts:
                    with self.subTest(option=f"{question.id}:{option.value}", account=account.name):
                        self.assertIn(account.group, declared)

    def test_required_questions_can_be_answered(self):
        """A required question the user cannot answer would deadlock the flow."""
        for question_id in required_question_ids():
            question = get_question(question_id)
            with self.subTest(question=question_id):
                self.assertTrue(
                    question.options or question.kind in (CURRENCY,),
                    f"{question_id} is required but offers no way to answer it",
                )

    def test_required_questions_offer_a_catch_all(self):
        """
        Every required question needs an honest answer for someone none of its
        options describe, or the flow deadlocks for them. Adding a new required
        question without an escape fails here.
        """
        for question in QUESTION_CATALOG:
            if not question.required or not question.options:
                continue
            with self.subTest(question=question.id):
                self.assertTrue(
                    any(option.catch_all for option in question.options),
                    f"{question.id} is required but offers no catch-all option",
                )

    def test_catch_all_options_are_answerable_without_lying(self):
        """
        A catch-all must not be a grant in disguise: picking "none of these"
        should not quietly create accounts the user did not ask for. The one
        allowed exception is a catch-all that names what it creates -- income's
        "Something else" really does mean an Other Income account.
        """
        for question in QUESTION_CATALOG:
            for option in question.options:
                if not option.catch_all or option.grant.accounts:
                    continue
                with self.subTest(question=question.id, option=option.value):
                    self.assertEqual(option.grant.groups, ())


class CatalogPayloadTest(SimpleTestCase):
    def test_payload_covers_every_question(self):
        payload = catalog_payload()
        self.assertEqual([p["id"] for p in payload], [q.id for q in QUESTION_CATALOG])

    def test_payload_carries_no_chart_of_accounts_rules(self):
        """The client renders questions; what they create is the server's business."""
        for entry in catalog_payload():
            for option in entry["options"]:
                with self.subTest(question=entry["id"], option=option["value"]):
                    self.assertEqual(set(option), {"value", "label", "help_text"})

    def test_payload_is_json_serializable(self):
        """Lazy translation proxies must be resolved, or json.dumps blows up."""
        import json

        json.dumps(catalog_payload())

    def test_phase_questions_follow_catalog_order(self):
        for phase in active_phases():
            in_phase = [q.id for q in QUESTION_CATALOG if q.phase == phase]
            with self.subTest(phase=phase):
                self.assertEqual([q.id for q in questions_for_phase(phase)], in_phase)


class CatalogIsEditableTest(SimpleTestCase):
    """
    The point of the catalog's design: the question set can change without any
    other module needing to know. These tests fail loudly if that stops being true.
    """

    def test_no_question_is_named_outside_the_catalog(self):
        """
        Grants may depend on another question, but only through `requires`, which
        `validate_catalog` checks. Nothing else in the package may hardcode a
        question id, or cutting that question would leave a silent dead rule.
        """
        import pathlib

        package = pathlib.Path(__file__).resolve().parent.parent
        ids = {q.id for q in QUESTION_CATALOG}
        offenders = []

        for path in package.rglob("*.py"):
            if path.name in ("questions.py",) or "tests" in path.parts or "migrations" in path.parts:
                continue
            text = path.read_text()
            for question_id in ids:
                if f'"{question_id}"' in text or f"'{question_id}'" in text:
                    offenders.append(f"{path.relative_to(package)} hardcodes question id {question_id!r}")

        self.assertEqual(offenders, [])

    def test_single_and_multi_are_the_only_option_bearing_kinds(self):
        for question in QUESTION_CATALOG:
            if question.options:
                with self.subTest(question=question.id):
                    self.assertIn(question.kind, (SINGLE, MULTI))
