"""The rules API: CRUD, permissions, Test rule, explain, drafts, matches, and the feed's view of rules."""

from apps.accounts.models import Account, AccountGroup
from apps.bank_feed.services.categorize import create_entry
from apps.books.context import current_book
from apps.books.helpers import create_book
from apps.rules.models import Rule, RuleMatch, RuleProposal
from apps.rules.services import apply

from .base import RulesTestCase

EXAMPLE = {
    "name": "Car insurance",
    "direction": "out",
    "match": "all",
    "conditions": [
        {"field": "amount", "op": "gt", "value": "120"},
        {"field": "description", "op": "contains", "value": "INSURANCE"},
    ],
    "action": "category",
    "mode": "suggest",
}


class RuleCrudTest(RulesTestCase):
    def test_create_the_example_rule_and_it_suggests_at_once(self):
        row = self.tx("ACME INSURANCE", "145.00")
        response = self.api.post(
            self.url("rules/api/rules/"), {**EXAMPLE, "category": self.insurance.pk}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["problem"], "")
        self.assertEqual(RuleMatch.objects.get(transaction=row).status, RuleMatch.STATUS_SUGGESTED)

    def test_list_is_in_priority_order(self):
        self.rule(name="B", priority=1)
        self.rule(name="A", priority=0)
        response = self.api.get(self.url("rules/api/rules/"))
        self.assertEqual([r["name"] for r in response.data], ["A", "B"])

    def test_new_rules_go_above_broader_ones(self):
        broad = self.rule(name="Broad", conditions=[{"field": "description", "op": "contains", "value": "a"}])
        response = self.api.post(
            self.url("rules/api/rules/"),
            {**EXAMPLE, "accounts": [self.chequing.pk], "category": self.insurance.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        broad.refresh_from_db()
        self.assertEqual((response.data["priority"], broad.priority), (0, 1))

    def test_reorder(self):
        a, b = self.rule(name="A", priority=0), self.rule(name="B", priority=1)
        response = self.api.post(self.url("rules/api/rules/reorder/"), {"ids": [b.pk, a.pk]}, format="json")
        self.assertEqual([r["name"] for r in response.data], ["B", "A"])

    def test_update_and_delete(self):
        rule = self.rule()
        response = self.api.patch(self.url(f"rules/api/rules/{rule.pk}/"), {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.api.delete(self.url(f"rules/api/rules/{rule.pk}/")).status_code, 204)
        self.assertFalse(Rule.objects.filter(pk=rule.pk).exists())

    def test_validation(self):
        cases = {
            "transfer auto-post": {**EXAMPLE, "category": self.savings.pk, "mode": "auto_post"},
            "no category": {**EXAMPLE},
            "nothing narrows": {**EXAMPLE, "category": self.insurance.pk, "conditions": [], "direction": "any"},
            "bad condition": {
                **EXAMPLE,
                "category": self.insurance.pk,
                "conditions": [{"field": "amount", "op": "contains", "value": "x"}],
            },
            "split not 100": {
                **EXAMPLE,
                "action": "split",
                "splits": [
                    {"category": self.groceries.pk, "percent": "50"},
                    {"category": self.dining.pk, "percent": "40"},
                ],
            },
            "split with a transfer": {
                **EXAMPLE,
                "action": "split",
                "splits": [
                    {"category": self.groceries.pk, "percent": "50"},
                    {"category": self.savings.pk, "percent": "50"},
                ],
            },
            "rename with nothing": {**EXAMPLE, "action": "rename"},
            "account without a feed": {**EXAMPLE, "category": self.insurance.pk, "accounts": [self.groceries.pk]},
        }
        for label, body in cases.items():
            with self.subTest(label):
                response = self.api.post(self.url("rules/api/rules/"), body, format="json")
                self.assertEqual(response.status_code, 400, response.content)

    def test_a_transfer_rule_may_suggest(self):
        response = self.api.post(self.url("rules/api/rules/"), {**EXAMPLE, "category": self.savings.pk}, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_duplicate_name(self):
        self.rule(name="Car insurance")
        response = self.api.post(
            self.url("rules/api/rules/"), {**EXAMPLE, "category": self.insurance.pk}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_another_books_category_is_refused(self):
        other = create_book(self.team, "Other")
        group = AccountGroup.objects.create(book=other, name="X", account_type="expense")
        theirs = Account.objects.create(book=other, name="Theirs", account_group=group)
        response = self.api.post(self.url("rules/api/rules/"), {**EXAMPLE, "category": theirs.pk}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_rules_page_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url("rules/"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "rules-props")


class RulePermissionTest(RulesTestCase):
    def setUp(self):
        super().setUp()
        self.api.force_authenticate(user=self.member)

    def test_a_member_reads_but_cannot_write_rules(self):
        rule = self.rule()
        self.assertEqual(self.api.get(self.url("rules/api/rules/")).status_code, 200)
        body = {**EXAMPLE, "name": "New", "category": self.insurance.pk}
        self.assertEqual(self.api.post(self.url("rules/api/rules/"), body, format="json").status_code, 403)
        self.assertEqual(self.api.patch(self.url(f"rules/api/rules/{rule.pk}/"), {"name": "x"}).status_code, 403)
        self.assertEqual(self.api.delete(self.url(f"rules/api/rules/{rule.pk}/")).status_code, 403)
        self.assertEqual(self.api.post(self.url("rules/api/rules/reorder/"), {"ids": [rule.pk]}).status_code, 403)

    def test_a_member_accepts_suggestions(self):
        self.rule()
        row = self.tx("insurance")
        apply.run(self.book, [row])
        response = self.api.post(self.url("rules/api/matches/accept/"), {"transaction_ids": [row.pk]}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["accepted"], [row.pk])

    def test_a_stranger_gets_nothing(self):
        from apps.users.models import CustomUser

        stranger = CustomUser.objects.create_user(username="stranger@example.com", password="pass")
        self.api.force_authenticate(user=stranger)
        self.assertIn(self.api.get(self.url("rules/api/rules/")).status_code, (403, 404))


class TestRuleEndpointTest(RulesTestCase):
    def test_pending_backtest_and_conflicts(self):
        pending = self.tx("ACME INSURANCE", "145.00")
        self.tx("Groceries", "145.00")
        agree, differ = self.tx("ACME INSURANCE", "130.00"), self.tx("ACME INSURANCE", "130.00")
        with current_book(self.book):
            create_entry(agree, self.insurance)
            create_entry(differ, self.groceries)
        response = self.api.post(
            self.url("rules/api/rules/test/"), {**EXAMPLE, "category": self.insurance.pk}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["pending"]["count"], 1)
        self.assertEqual(response.data["pending"]["rows"][0]["id"], pending.pk)
        self.assertEqual(
            {k: response.data["backtest"][k] for k in ("matched", "agree", "differ")},
            {"matched": 2, "agree": 1, "differ": 1},
        )
        self.assertEqual(response.data["backtest"]["differ_rows"][0]["id"], differ.pk)
        self.assertFalse(response.data["conflicts"]["dead"])

    def test_a_shadowed_rule_is_dead(self):
        broad = self.rule(name="Every insurance", priority=0)
        self.tx("ACME INSURANCE", "145.00")
        response = self.api.post(
            self.url("rules/api/rules/test/"),
            {**EXAMPLE, "category": self.groceries.pk, "priority": 1},
            format="json",
        )
        conflicts = response.data["conflicts"]
        self.assertTrue(conflicts["dead"])
        self.assertEqual(conflicts["shadowed_by"][0]["rule_id"], broad.pk)

    def test_an_overlapping_rule_names_who_it_takes_from(self):
        broad = self.rule(name="Every insurance", category=self.groceries, priority=0)
        self.tx("ACME INSURANCE", "145.00")
        response = self.api.post(
            self.url("rules/api/rules/test/"),
            {**EXAMPLE, "category": self.insurance.pk, "priority": 0},
            format="json",
        )
        self.assertEqual(response.data["conflicts"]["takes_from"][0]["rule_id"], broad.pk)
        self.assertEqual(response.data["pending"]["count"], 1)

    def test_explain(self):
        row = self.tx("ACME INSURANCE", "99.00")
        response = self.api.post(
            self.url("rules/api/rules/explain/"),
            {"rule": {**EXAMPLE, "category": self.insurance.pk}, "transaction_id": row.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.data["matched"])
        self.assertEqual([c["passed"] for c in response.data["conditions"]], [False, True])


class DraftFromTransactionTest(RulesTestCase):
    def categorize(self, row, category):
        with current_book(self.book):
            create_entry(row, category)

    def test_offered_when_it_would_cover_two_rows(self):
        self.tx("SQ *BLUE BOTTLE 9920", "5.00", payee=None)
        row = self.tx("SQ *BLUE BOTTLE 4417", "5.50", payee=None)
        self.categorize(row, self.dining)
        response = self.api.post(self.url("rules/api/rules/draft_from_transaction/"), {"transaction_id": row.pk})
        self.assertTrue(response.data["offer"], response.data)
        self.assertEqual(response.data["rule"]["conditions"][0]["value"], "sq blue bottle")
        self.assertEqual(response.data["rule"]["direction"], "out")

    def test_not_offered_for_a_one_off(self):
        row = self.tx("ONE OFF THING", "5.00")
        self.categorize(row, self.dining)
        response = self.api.post(self.url("rules/api/rules/draft_from_transaction/"), {"transaction_id": row.pk})
        self.assertFalse(response.data["offer"])

    def test_declining_is_remembered(self):
        self.tx("COFFEE CO", "5.00", payee="Coffee Co")
        row = self.tx("COFFEE CO", "5.00", payee="Coffee Co")
        self.categorize(row, self.dining)
        first = self.api.post(self.url("rules/api/rules/draft_from_transaction/"), {"transaction_id": row.pk})
        self.assertTrue(first.data["offer"])
        self.api.post(
            self.url("rules/api/rules/decline_draft/"),
            {"signature": first.data["rule"]["signature"], "category": self.dining.pk},
            format="json",
        )
        again = self.api.post(self.url("rules/api/rules/draft_from_transaction/"), {"transaction_id": row.pk})
        self.assertEqual((again.data["offer"], again.data["reason"]), (False, "declined"))


class FeedIntegrationTest(RulesTestCase):
    def feed(self, **params):
        return self.api.get(self.url("bankfeed/api/feed/"), {"account": self.chequing.pk, **params})

    def test_rows_carry_their_rule_match_and_can_be_filtered(self):
        self.rule()
        self.rule(
            name="Groceries auto",
            conditions=[{"field": "description", "op": "contains", "value": "grocer"}],
            category=self.groceries,
            mode=Rule.MODE_AUTO_POST,
        )
        suggested, posted, plain = self.tx("insurance"), self.tx("grocer"), self.tx("other")
        apply.run(self.book, [suggested, posted, plain])

        rows = {int(r["id"]): r for r in self.feed(counts=1).data["results"]}
        self.assertEqual(rows[suggested.pk]["rule_match"]["status"], "suggested")
        self.assertEqual(rows[suggested.pk]["rule_match"]["category_name"], "Car Insurance")
        self.assertEqual(rows[posted.pk]["rule_match"]["status"], "auto_posted")
        self.assertIsNone(rows[plain.pk]["rule_match"])

        response = self.feed(rule="suggested", counts=1)
        self.assertEqual([int(r["id"]) for r in response.data["results"]], [suggested.pk])
        self.assertEqual(response.data["counts"]["rule_suggested"], 1)
        self.assertEqual(response.data["counts"]["rule_auto_posted"], 1)
        self.assertEqual([int(r["id"]) for r in self.feed(rule="auto_posted").data["results"]], [posted.pk])
        self.assertEqual(self.feed(rule="nonsense").status_code, 400)

    def test_accept_all(self):
        self.rule()
        rows = [self.tx("insurance"), self.tx("insurance")]
        apply.run(self.book, rows)
        response = self.api.post(
            self.url("rules/api/matches/accept/"), {"transaction_ids": [r.pk for r in rows]}, format="json"
        )
        self.assertEqual(sorted(response.data["accepted"]), sorted(r.pk for r in rows))
        for row in rows:
            self.assertEqual(self.category_of(row), self.insurance)

    def test_accept_names_a_refused_row_and_does_the_rest(self):
        self.rule()
        locked, fine = self.tx("insurance"), self.tx("insurance")
        apply.run(self.book, [locked, fine])
        from datetime import timedelta

        locked.posted_date = locked.posted_date - timedelta(days=10)
        locked.save()
        self.book.locked_through = locked.posted_date
        self.book.save()
        response = self.api.post(
            self.url("rules/api/matches/accept/"), {"transaction_ids": [locked.pk, fine.pk]}, format="json"
        )
        self.assertEqual(response.data["accepted"], [fine.pk])
        self.assertEqual(response.data["refused"][0]["id"], locked.pk)

    def test_prompts(self):
        response = self.api.get(self.url("rules/api/rules/prompts/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["graduation"], [])
        self.assertTrue(response.data["can_edit"])


class ProposalApiTest(RulesTestCase):
    def test_accepting_a_proposal_returns_a_draft_and_saving_marks_it_accepted(self):
        proposal = RuleProposal.objects.create(
            book=self.book,
            signature="payee:corner store",
            field="payee",
            value="corner store",
            direction="out",
            category=self.groceries,
            evidence_count=5,
            consistency="1.000",
        )
        listed = self.api.get(self.url("rules/api/proposals/"))
        self.assertEqual([p["id"] for p in listed.data], [proposal.pk])
        draft = self.api.post(self.url(f"rules/api/proposals/{proposal.pk}/accept/")).data
        self.assertEqual(draft["origin"], "learned")
        response = self.api.post(self.url("rules/api/rules/"), draft, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, RuleProposal.STATUS_ACCEPTED)

    def test_dismiss(self):
        proposal = RuleProposal.objects.create(
            book=self.book, signature="payee:x", field="payee", value="x", category=self.groceries
        )
        self.assertEqual(self.api.post(self.url(f"rules/api/proposals/{proposal.pk}/dismiss/")).status_code, 204)
        self.assertEqual(self.api.get(self.url("rules/api/proposals/")).data, [])
