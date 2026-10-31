"""The rules API and page: CRUD, validation, reorder, preview, apply, draft, permissions."""

from apps.audit.models import AuditEvent
from apps.bank_feed.services.categorize import categorize_single
from apps.budget.buckets import budget_group
from apps.categorization.models import CategorizationRule

from .base import RuleTestCase


class RuleCrudTest(RuleTestCase):
    def create(self, **body):
        payload = {"description_match": "words", "description_value": "blue bottle", "category": self.coffee.id}
        payload.update(body)
        return self.client.post(self.url("api/rules/"), payload, format="json")

    def test_create_names_the_rule_and_appends_it(self):
        self.rule(name="First")
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["name"], "blue bottle → Coffee")
        self.assertEqual(body["priority"], 1)
        self.assertEqual(body["category_name"], "Coffee")
        self.assertTrue(
            AuditEvent.objects.filter(event_type=AuditEvent.CATEGORIZATION_RULE_CHANGED, metadata__action="created")
        )

    def test_a_clashing_generated_name_gets_a_number(self):
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().json()["name"], "blue bottle → Coffee (2)")

    def test_validation(self):
        cases = {
            "nothing to match": {"description_match": "", "description_value": ""},
            "budget bucket": {"category": budget_group(self.book).accounts.first().id},
            "own account": {"category": self.chequing.id, "account": self.chequing.id},
            "income as scope": {"account": self.salary.id},
            "taken name": {"name": "Taken"},
        }
        self.rule(name="Taken")
        for label, body in cases.items():
            with self.subTest(label):
                self.assertEqual(self.create(**body).status_code, 400)

    def test_an_archived_category_is_refused(self):
        self.coffee.is_archived = True
        self.coffee.save()
        try:
            self.assertEqual(self.create().status_code, 400)
        finally:
            self.coffee.is_archived = False
            self.coffee.save()

    def test_update_and_delete(self):
        rule = self.rule()
        response = self.client.patch(self.url(f"api/rules/{rule.id}/"), {"is_enabled": False}, format="json")
        self.assertEqual(response.status_code, 200)
        rule.refresh_from_db()
        self.assertFalse(rule.is_enabled)
        self.assertEqual(self.client.delete(self.url(f"api/rules/{rule.id}/")).status_code, 204)
        self.assertFalse(CategorizationRule.objects.filter(pk=rule.pk).exists())

    def test_a_deleted_category_leaves_the_rule_flagged(self):
        spare = self.coffee.__class__.objects.create(
            book=self.book, name="Spare", account_group=self.coffee.account_group
        )
        rule = self.rule(category=spare)
        spare.delete()
        rule.refresh_from_db()
        self.assertIsNone(rule.category_id)
        body = self.client.get(self.url(f"api/rules/{rule.id}/")).json()
        self.assertIn("deleted", body["problem"])
        self.assertFalse(CategorizationRule.objects.filter(pk=rule.pk).usable().exists())
        self.assertEqual(self.client.post(self.url(f"api/rules/{rule.id}/apply/")).status_code, 400)

    def test_list_counts_rows_each_rule_still_holds(self):
        rule = self.rule()
        self.row("BLUE BOTTLE 1")
        self.row("BLUE BOTTLE 2")
        self.client.post(self.url(f"api/rules/{rule.id}/apply/"))
        [listed] = self.client.get(self.url("api/rules/")).json()
        self.assertEqual(listed["applied_count"], 2)


class RuleActionsTest(RuleTestCase):
    def test_reorder_needs_every_rule_once(self):
        a, b, c = self.rule(name="a"), self.rule(name="b"), self.rule(name="c")
        bad = self.client.post(self.url("api/rules/reorder/"), {"ids": [a.id, b.id]}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post(self.url("api/rules/reorder/"), {"ids": [c.id, a.id, b.id]}, format="json")
        self.assertEqual(ok.status_code, 204)
        self.assertEqual(list(CategorizationRule.objects.in_order().values_list("name", flat=True)), ["c", "a", "b"])

    def test_preview_of_an_unsaved_rule_writes_nothing(self):
        self.row("BLUE BOTTLE 1")
        response = self.client.post(
            self.url("api/rules/preview/"),
            {"description_match": "contains", "description_value": "blue bottle"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(CategorizationRule.objects.count(), 0)

    def test_preview_of_a_half_typed_rule_is_empty_not_an_error(self):
        response = self.client.post(self.url("api/rules/preview/"), {"description_match": "words"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)
        self.assertIn("errors", response.json())

    def test_test_and_apply(self):
        rule = self.rule()
        row = self.row("BLUE BOTTLE")
        self.assertEqual(self.client.get(self.url(f"api/rules/{rule.id}/test/")).json()["count"], 1)
        response = self.client.post(self.url(f"api/rules/{rule.id}/apply/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["categorized_ids"], [row.id])
        self.assertEqual(self.category_of(row), self.coffee)

    def test_draft_from_a_row_with_a_payee(self):
        row = self.row("SQ *BLUE BOTTLE 4417", merchant="Blue Bottle")
        body = self.client.get(self.url("api/rules/draft/"), {"transaction": row.id, "category": self.coffee.id}).json()
        self.assertEqual((body["payee_match"], body["payee_value"]), ("equals", "Blue Bottle"))
        self.assertEqual(body["direction"], "outflow")
        self.assertEqual(body["category"], self.coffee.id)
        self.assertEqual(body["name"], "Blue Bottle → Coffee")

    def test_draft_from_a_row_without_one_uses_the_descriptions_words(self):
        row = self.row("SQ *BLUE BOTTLE 4417", amount="-5")
        categorize_single(row, self.coffee)
        body = self.client.get(self.url("api/rules/draft/"), {"transaction": row.id}).json()
        self.assertEqual((body["description_match"], body["description_value"]), ("words", "blue bottle"))
        self.assertEqual(body["direction"], "inflow")
        self.assertEqual(body["category"], self.coffee.id)


class PermissionTest(RuleTestCase):
    def test_a_member_reads_but_cannot_write(self):
        rule = self.rule()
        self.client.force_authenticate(user=self.member)
        self.assertEqual(self.client.get(self.url("api/rules/")).status_code, 200)
        self.assertEqual(self.client.get(self.url(f"api/rules/{rule.id}/test/")).status_code, 200)
        writes = [
            ("post", "api/rules/", {"description_match": "contains", "description_value": "x", "category": 1}),
            ("patch", f"api/rules/{rule.id}/", {"is_enabled": False}),
            ("delete", f"api/rules/{rule.id}/", None),
            ("post", f"api/rules/{rule.id}/apply/", None),
            ("post", "api/rules/reorder/", {"ids": [rule.id]}),
            ("post", "api/rules/preview/", {}),
        ]
        for method, path, body in writes:
            with self.subTest(path=path, method=method):
                response = getattr(self.client, method)(self.url(path), body, format="json")
                self.assertEqual(response.status_code, 403)
        rule.refresh_from_db()
        self.assertTrue(rule.is_enabled)

    def test_anonymous_is_refused(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(self.url("api/rules/")).status_code, (401, 403))

    def test_the_page_renders_for_a_member(self):
        self.client.force_login(self.member)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "rules-props")
        self.assertContains(response, "Categorization rules")
