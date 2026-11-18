"""Confirm, override, dismiss, undo -- and what the rule learns from them."""

from apps.audit.models import AuditEvent
from apps.journal.models import JournalLine
from apps.rules import constants
from apps.rules.models import Rule, RuleMatch
from apps.rules.services import apply, feedback

from .base import RulesTestCase


class SuggestionOutcomesTest(RulesTestCase):
    def setUp(self):
        super().setUp()
        self.suggest = self.rule()
        self.row = self.tx("insurance", "145.00")
        apply.run(self.book, [self.row])
        self.match = RuleMatch.objects.get(transaction=self.row)

    def test_accept_posts_what_was_offered(self):
        feedback.accept(self.match)
        self.assertEqual(self.category_of(self.row), self.insurance)
        self.match.refresh_from_db()
        self.suggest.refresh_from_db()
        self.assertEqual(self.match.status, RuleMatch.STATUS_CONFIRMED)
        self.assertEqual((self.suggest.times_confirmed, self.suggest.confirm_streak), (1, 1))

    def test_categorizing_the_same_way_in_the_feed_confirms(self):
        response = self.api.patch(
            self.url("bankfeed/api/feed/batch_edit/"),
            {"ids": [self.row.pk], "category_id": self.insurance.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 204, response.content)
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, RuleMatch.STATUS_CONFIRMED)

    def test_categorizing_differently_overrides_and_resets_the_streak(self):
        Rule.objects.filter(pk=self.suggest.pk).update(confirm_streak=3)
        response = self.api.post(
            self.url("bankfeed/api/feed/categorize/"),
            {"rows": [{"id": self.row.pk}], "category_id": self.groceries.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 204, response.content)
        self.match.refresh_from_db()
        self.suggest.refresh_from_db()
        self.assertEqual(self.match.status, RuleMatch.STATUS_OVERRIDDEN)
        self.assertEqual((self.suggest.times_overridden, self.suggest.confirm_streak), (1, 0))

    def test_dismiss_restores_names_and_leaves_the_row_alone_for_good(self):
        Rule.objects.filter(pk=self.suggest.pk).update(payee_name="State Farm")
        apply.refresh(self.book)
        self.row.refresh_from_db()
        self.assertEqual(self.row.merchant_name, "State Farm")
        feedback.dismiss(RuleMatch.objects.get(transaction=self.row))
        self.row.refresh_from_db()
        self.assertIsNone(self.row.merchant_name)
        apply.refresh(self.book)
        self.assertEqual(RuleMatch.objects.get(transaction=self.row).status, RuleMatch.STATUS_DISMISSED)

    def test_graduation_is_offered_after_the_streak_and_declining_is_final(self):
        Rule.objects.filter(pk=self.suggest.pk).update(confirm_streak=constants.GRADUATE_STREAK - 1)
        self.assertEqual(feedback.graduation_offers(self.book), [])
        feedback.accept(self.match)
        self.assertEqual([r.pk for r in feedback.graduation_offers(self.book)], [self.suggest.pk])

        response = self.api.post(self.url(f"rules/api/rules/{self.suggest.pk}/graduate/"), {"accept": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(feedback.graduation_offers(self.book), [])

    def test_accepting_graduation_switches_to_auto_post(self):
        response = self.api.post(self.url(f"rules/api/rules/{self.suggest.pk}/graduate/"), {"accept": True})
        self.assertEqual(response.status_code, 200)
        self.suggest.refresh_from_db()
        self.assertEqual(self.suggest.mode, Rule.MODE_AUTO_POST)


class AutoPostOutcomesTest(RulesTestCase):
    def setUp(self):
        super().setUp()
        self.auto = self.rule(mode=Rule.MODE_AUTO_POST, payee_name="Insurer")
        self.row = self.tx("insurance", "145.00", payee="INS*CO")
        apply.run(self.book, [self.row])
        self.match = RuleMatch.objects.get(transaction=self.row)

    def test_undo_uncategorizes_and_restores_names(self):
        feedback.undo(self.match)
        self.row.refresh_from_db()
        self.assertIsNone(self.row.journal_entry_id)
        self.assertEqual(self.row.merchant_name, "INS*CO")
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, RuleMatch.STATUS_OVERRIDDEN)
        self.assertTrue(self.match.was_auto_posted)

    def test_undo_is_refused_on_a_reconciled_row(self):
        self.row.refresh_from_db()
        self.assertTrue(self.row.journal_entry_id)
        JournalLine.objects.filter(journal_entry=self.row.journal_entry, account=self.chequing).update(
            is_reconciled=True
        )
        response = self.api.post(self.url(f"rules/api/matches/{self.row.pk}/undo/"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.category_of(self.row), self.insurance)

    def test_undo_is_refused_in_a_closed_period(self):
        self.book.locked_through = self.row.posted_date
        self.book.save()
        response = self.api.post(self.url(f"rules/api/matches/{self.row.pk}/undo/"))
        self.assertEqual(response.status_code, 409)

    def test_two_overrides_in_the_last_ten_demote_the_rule(self):
        feedback.undo(self.match)
        self.auto.refresh_from_db()
        self.assertEqual(self.auto.mode, Rule.MODE_AUTO_POST)

        second = self.tx("insurance", "145.00")
        apply.run(self.book, [second])
        response = self.api.post(
            self.url("bankfeed/api/feed/categorize/"),
            {"rows": [{"id": second.pk}], "category_id": self.groceries.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.auto.refresh_from_db()
        self.assertEqual(self.auto.mode, Rule.MODE_SUGGEST)
        self.assertIsNotNone(self.auto.demoted_at)
        self.assertTrue(AuditEvent.objects.filter(book=self.book, event_type=AuditEvent.RULE_DEMOTED).exists())

    def test_re_saving_unchanged_keeps_the_auto_post(self):
        feedback.record([self.row])
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, RuleMatch.STATUS_AUTO_POSTED)
