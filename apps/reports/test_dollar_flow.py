"""Tests for the Dollar Flow on the Budget & Goals report (apps/reports/dollar_flow.py)."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EXPENSE, Account, AccountGroup
from apps.budget.ledger import set_budget
from apps.budget.unassigned import Unassigned, compute_unassigned
from apps.teams.models import Team

from .consolidated import budget_goals_report
from .dollar_flow import MAX_CATEGORIES, account_balances, dollar_flow
from .test_consolidated import ConsolidatedReportsBase, PlanFixture

D = Decimal
JUNE = date(2026, 6, 1)


def balances(**amounts):
    """(account, signed balance) pairs from name=amount; a namespace stands in for the account."""
    return [(SimpleNamespace(pk=100 + i, name=name), D(str(v))) for i, (name, v) in enumerate(amounts.items())]


def unassigned(net_worth, goals=(), envelopes=(), income_due="0", expects_income=False):
    goals = [{"name": n, "amount": D(str(a)), "goal": SimpleNamespace(pk=200 + i)} for i, (n, a) in enumerate(goals)]
    group_ids = {}
    envelopes = [
        {
            "name": n,
            "group": g,
            "amount": D(str(a)),
            "account": SimpleNamespace(pk=300 + i, account_group_id=group_ids.setdefault(g, 400 + len(group_ids))),
        }
        for i, (n, g, a) in enumerate(envelopes)
    ]
    result = Unassigned(
        month=JUNE,
        net_worth=D(str(net_worth)),
        income_due=D(income_due),
        envelopes=sum((e["amount"] for e in envelopes if e["amount"] > 0), D("0")),
        goals=sum((g["amount"] for g in goals if g["amount"] > 0), D("0")),
        expects_income=expects_income,
    )
    result.detail.update({"goals": goals, "envelopes": envelopes})
    return result


class FlowAssertions:
    def assertConserved(self, flow):
        """Every node that both receives and gives passes on exactly what it receives."""
        ins, outs = defaultdict(D), defaultdict(D)
        for link in flow["links"]:
            outs[link["source"]] += link["amount"]
            ins[link["target"]] += link["amount"]
        for node in flow["nodes"]:
            key = node["key"]
            if key in ins and key in outs:
                self.assertEqual(ins[key], outs[key], key)
            # A node's size is what flows through it.
            self.assertEqual(node["amount"], ins.get(key) or outs.get(key), key)

    def assertNoOverlap(self, flow):
        by_column = defaultdict(list)
        for node in flow["nodes"]:
            by_column[node["column"]].append(node)
        for nodes in by_column.values():
            nodes.sort(key=lambda n: n["y"])
            for above, below in zip(nodes, nodes[1:], strict=False):
                self.assertGreaterEqual(below["y"], above["y"] + above["h"], (above["key"], below["key"]))

    def keys(self, flow):
        return {n["key"]: n for n in flow["nodes"]}

    def option(self, flow, level, label):
        """The filter value for `label` in `level` ('assets', 'goals', 'categories', ...)."""
        (lvl,) = [lvl for lvl in flow["filters"] if lvl["key"] == level]
        (opt,) = [o for o in lvl["options"] if o["label"] == label]
        return opt["value"]


class DollarFlowShapeTest(FlowAssertions, SimpleTestCase):
    def test_net_worth_to_every_job(self):
        u = unassigned(
            1000,
            goals=[("Car", 300)],
            envelopes=[("Food", "Home", 150), ("Rent", "Home", 250), ("Gas", "Auto", 50)],
        )
        flow = dollar_flow(u, balances(Checking=1200, Visa=-200))
        self.assertFalse(flow["empty"])
        self.assertConserved(flow)
        self.assertNoOverlap(flow)
        nodes = self.keys(flow)
        self.assertEqual(nodes["assets"]["amount"], D("1200"))
        self.assertEqual(nodes["debts"]["amount"], D("200"))
        self.assertEqual(nodes["net_worth"]["amount"], D("1000"))
        self.assertEqual(nodes["goals"]["amount"], D("300"))
        self.assertEqual(nodes["envelopes"]["amount"], D("450"))
        self.assertEqual(nodes["unassigned"]["amount"], u.amount)
        self.assertNotIn("gap", nodes)
        # Groups largest first, categories largest first within them.
        self.assertEqual(nodes["group:0"]["label"], "Home")
        self.assertEqual(nodes["category:0:0"]["label"], "Rent")
        breakdown = flow["breakdown"]
        self.assertEqual(breakdown["total"], D("1000"))
        self.assertEqual([j["key"] for j in breakdown["jobs"]], ["goals", "envelopes", "unassigned"])
        self.assertAlmostEqual(sum(j["pct"] for j in breakdown["jobs"]), 100.0)

    def test_over_assigned_enters_as_its_own_source(self):
        u = unassigned(500, goals=[("Car", 400)], envelopes=[("Food", "Home", 300)])
        flow = dollar_flow(u, balances(Checking=500))
        self.assertConserved(flow)
        nodes = self.keys(flow)
        self.assertEqual(nodes["gap"]["amount"], -u.amount)  # $200 over-assigned
        self.assertEqual(nodes["gap"]["label"], str(u.label))
        self.assertNotIn("unassigned", nodes)
        # Net worth fills the first jobs; the gap covers the last.
        gap_links = [link for link in flow["links"] if link["source"] == "gap"]
        self.assertEqual([(link["target"], link["amount"]) for link in gap_links], [("envelopes", D("200"))])
        self.assertEqual(flow["breakdown"]["total"], D("700"))

    def test_expected_income_stays_out_of_the_flow(self):
        """Unassigned v4: income counts once it is in net worth; Expected income sits beside."""
        u = unassigned(100, envelopes=[("Food", "Home", 250)], income_due="300", expects_income=True)
        flow = dollar_flow(u, balances(Checking=100))
        self.assertConserved(flow)
        nodes = self.keys(flow)
        self.assertNotIn("income_due", nodes)
        self.assertNotIn("unassigned", nodes)
        self.assertEqual(nodes["gap"]["amount"], -u.amount)  # 150 over-assigned
        self.assertEqual(flow["breakdown"]["total"], D("250"))
        expected = flow["breakdown"]["expected"]
        self.assertEqual(expected["amount"], D("300"))
        self.assertEqual(expected["covers"], D("150"))

    def test_no_expected_income_line_unless_the_book_budgets_income(self):
        flow = dollar_flow(unassigned(100, envelopes=[("Food", "Home", 50)]), balances(Checking=100))
        self.assertIsNone(flow["breakdown"]["expected"])

    def test_debt_beyond_assets(self):
        u = unassigned(-400, envelopes=[("Food", "Home", 100)])
        flow = dollar_flow(u, balances(Checking=100, Loan=-500))
        self.assertConserved(flow)
        nodes = self.keys(flow)
        self.assertNotIn("net_worth", nodes)
        self.assertEqual(nodes["debt_beyond"]["amount"], D("400"))
        self.assertEqual(nodes["debts"]["amount"], D("500"))
        self.assertEqual(nodes["gap"]["amount"], D("100"))
        self.assertEqual(flow["breakdown"]["net_worth"], D("-400"))

    def test_expected_income_does_not_pay_debt_beyond_assets(self):
        u = unassigned(-100, envelopes=[("Food", "Home", 50)], income_due="300", expects_income=True)
        flow = dollar_flow(u, balances(Loan=-100))
        self.assertConserved(flow)
        nodes = self.keys(flow)
        self.assertNotIn("unassigned", nodes)
        self.assertEqual(nodes["gap"]["amount"], D("50"))
        self.assertEqual(flow["breakdown"]["expected"]["covers"], D("50"))

    def test_sides_are_by_sign_not_type(self):
        """A card in credit is money you hold; an overdrawn account is money you owe."""
        flow = dollar_flow(unassigned(30), balances(Checking=-20, Visa=50))
        self.assertConserved(flow)
        breakdown = flow["breakdown"]
        self.assertEqual([i["label"] for i in breakdown["holds"]], ["Visa"])
        self.assertEqual([i["label"] for i in breakdown["owes"]], ["Checking"])
        self.assertEqual(breakdown["net_worth"], D("30"))

    def test_long_lists_fold_in_the_drawing_but_not_the_breakdown(self):
        envelopes = [(f"Cat {i:02d}", "Home", 10 + i) for i in range(MAX_CATEGORIES + 4)]
        u = unassigned(1000, envelopes=envelopes)
        flow = dollar_flow(u, balances(Checking=1000))
        self.assertConserved(flow)
        self.assertNoOverlap(flow)
        drawn = [n for n in flow["nodes"] if n["kind"] == "category"]
        self.assertEqual(len(drawn), MAX_CATEGORIES)
        self.assertEqual(drawn[-1]["label"], "5 more categories")
        (job,) = [j for j in flow["breakdown"]["jobs"] if j["key"] == "envelopes"]
        self.assertEqual(len(job["groups"][0]["entries"]), len(envelopes))

    def test_overspent_claims_nothing(self):
        u = unassigned(100, goals=[("Trip", -20)], envelopes=[("Rent", "Home", -50), ("Food", "Home", 40)])
        flow = dollar_flow(u, balances(Checking=100))
        labels = {n["label"] for n in flow["nodes"]}
        self.assertNotIn("Rent", labels)
        self.assertNotIn("Trip", labels)
        self.assertIn("Food", labels)

    def test_long_labels_are_truncated_with_the_full_name_kept(self):
        name = "An extremely long category name"
        flow = dollar_flow(unassigned(100, envelopes=[(name, "Home", 40)]), balances(Checking=100))
        (node,) = [n for n in flow["nodes"] if n["kind"] == "category"]
        self.assertEqual(node["label"], name)
        self.assertTrue(node["short"].endswith("…"))
        self.assertLess(len(node["short"]), len(name))

    def test_nothing_to_draw(self):
        self.assertEqual(dollar_flow(unassigned(0), []), {"empty": True, "filters": [], "hidden": []})


class DollarFlowFilterTest(FlowAssertions, SimpleTestCase):
    """Each level can be switched off; the picture still adds up."""

    def setUp(self):
        self.u = unassigned(
            1000,
            goals=[("Car", 300), ("Trip", 100)],
            envelopes=[("Food", "Home", 150), ("Rent", "Home", 250), ("Gas", "Auto", 50)],
        )
        self.balances = balances(Checking=700, House=500, Visa=-200)
        self.full = dollar_flow(self.u, self.balances)

    def flow(self, *labels):
        """The flow with each (level, label) hidden."""
        return dollar_flow(self.u, self.balances, hidden={self.option(self.full, lvl, lbl) for lvl, lbl in labels})

    def test_every_level_is_offered(self):
        self.assertEqual(
            [lvl["key"] for lvl in self.full["filters"]], ["assets", "debts", "jobs", "goals", "groups", "categories"]
        )
        self.assertEqual(self.full["hidden"], [])
        categories = self.full["filters"][-1]["options"]
        self.assertEqual({o["note"] for o in categories}, {"Home", "Auto"})

    def test_hiding_an_asset_recomputes_net_worth_and_shows_the_gap(self):
        flow = self.flow(("assets", "House"))
        self.assertConserved(flow)
        self.assertNoOverlap(flow)
        nodes = self.keys(flow)
        self.assertEqual(nodes["net_worth"]["amount"], D("500"))  # 700 − 200
        self.assertEqual(nodes["gap"]["amount"], D("350"))  # 850 of claims, 500 to cover them
        self.assertEqual(nodes["gap"]["label"], "Not covered")
        self.assertNotIn("unassigned", nodes)
        self.assertNotIn("House", {n["label"] for n in flow["nodes"]})
        self.assertEqual(flow["breakdown"]["book_net_worth"], D("1000"))
        self.assertEqual(flow["hidden"], ["acct:101"])

    def test_hiding_a_debt_raises_what_the_accounts_shown_leave_free(self):
        flow = self.flow(("debts", "Visa"))
        self.assertConserved(flow)
        nodes = self.keys(flow)
        self.assertNotIn("debts", nodes)
        self.assertEqual(nodes["unassigned"]["amount"], D("350"))  # 1200 − 850
        self.assertEqual(nodes["unassigned"]["label"], "Unassigned, these accounts")

    def test_hiding_a_goal_moves_its_money_to_hidden_not_unassigned(self):
        flow = self.flow(("goals", "Car"))
        self.assertConserved(flow)
        nodes = self.keys(flow)
        self.assertEqual(nodes["goals"]["amount"], D("100"))
        self.assertEqual(nodes["hidden"]["amount"], D("300"))
        self.assertEqual(nodes["unassigned"]["amount"], self.u.amount)  # unchanged: 150
        self.assertIsNone(flow["breakdown"]["book_net_worth"])
        self.assertEqual([j["key"] for j in flow["breakdown"]["jobs"]], ["goals", "envelopes", "unassigned", "hidden"])

    def test_hiding_a_group_and_a_category(self):
        flow = self.flow(("groups", "Auto"), ("categories", "Rent"))
        self.assertConserved(flow)
        nodes = self.keys(flow)
        self.assertEqual(nodes["envelopes"]["amount"], D("150"))  # Food only
        self.assertEqual(nodes["hidden"]["amount"], D("300"))  # Rent 250 + Auto 50
        self.assertEqual([n["label"] for n in flow["nodes"] if n["kind"] == "category"], ["Food"])
        (groups,) = [lvl for lvl in flow["filters"] if lvl["key"] == "groups"]
        self.assertEqual(groups["hidden_count"], 1)

    def test_hiding_a_whole_job(self):
        flow = self.flow(("jobs", "Budget envelopes"), ("jobs", "Unassigned"))
        self.assertConserved(flow)
        nodes = self.keys(flow)
        self.assertNotIn("envelopes", nodes)
        self.assertNotIn("unassigned", nodes)
        self.assertEqual(nodes["hidden"]["amount"], D("600"))  # 450 envelopes + 150 unassigned
        self.assertEqual(nodes["goals"]["amount"], D("400"))

    def test_hiding_everything_on_the_left_still_draws_the_claims(self):
        flow = self.flow(("assets", "Checking"), ("assets", "House"), ("debts", "Visa"))
        self.assertConserved(flow)
        self.assertEqual(self.keys(flow)["gap"]["amount"], D("850"))

    def test_hiding_everything(self):
        hidden = {o["value"] for lvl in self.full["filters"] for o in lvl["options"]}
        flow = dollar_flow(self.u, self.balances, hidden=hidden)
        self.assertTrue(flow["empty"])
        self.assertEqual(len(flow["hidden"]), len(hidden))
        self.assertTrue(flow["filters"])

    def test_unknown_values_are_ignored(self):
        flow = dollar_flow(self.u, self.balances, hidden={"acct:999", "nonsense", "job:nope"})
        self.assertEqual(flow["hidden"], [])
        self.assertEqual([n["key"] for n in flow["nodes"]], [n["key"] for n in self.full["nodes"]])


class DollarFlowReportTest(FlowAssertions, PlanFixture):
    def test_matches_unassigned(self):
        flow = budget_goals_report(self.book, JUNE)["flow"]
        u = compute_unassigned(self.book, JUNE)
        self.assertConserved(flow)
        self.assertNoOverlap(flow)
        self.assertEqual(flow["breakdown"]["net_worth"], u.net_worth)
        nodes = self.keys(flow)
        self.assertEqual(nodes["goals"]["amount"], u.goals)
        self.assertEqual(nodes["envelopes"]["amount"], u.envelopes)
        # The fixture budgets $3,000 of salary and receives $2,500: Expected, not in the flow.
        self.assertEqual(flow["breakdown"]["expected"]["amount"], u.income_due)
        self.assertEqual(u.income_due, D("500.00"))
        self.assertNotIn("income_due", nodes)
        (goal,) = [n for n in flow["nodes"] if n["kind"] == "goal"]
        self.assertEqual(goal["label"], "Zq Car")
        self.assertEqual(goal["url"], self.goal.get_absolute_url())
        self.assertEqual([n["label"] for n in flow["nodes"] if n["kind"] == "category"], ["Zq Food"])

    def test_balances_sum_to_net_worth(self):
        total = sum((v for _a, v in account_balances(self.book, JUNE)), Decimal("0"))
        self.assertEqual(total, compute_unassigned(self.book, JUNE).net_worth)

    def test_renders_every_category_in_the_breakdown(self):
        response = self.client.get(self.url("budget_goals"), {"month": "2026-06"})
        self.assertContains(response, 'data-testid="dollar-flow-breakdown"')
        self.assertContains(response, 'data-testid="dollar-flow-category"', count=1)
        self.assertContains(response, 'data-testid="dollar-flow-node"')
        self.assertContains(response, 'data-testid="dollar-flow-expected"')
        self.assertContains(response, 'data-testid="dollar-flow-filters"')

    def test_hide_param_filters_and_survives_month_links(self):
        hide = f"cat:{self.food.pk}"
        response = self.client.get(self.url("budget_goals"), {"month": "2026-06", "hide": [hide, "bogus"]})
        self.assertEqual(response.status_code, 200)
        flow = response.context["flow"]
        self.assertEqual(flow["hidden"], [hide])
        self.assertNotIn("Zq Food", [n["label"] for n in flow["nodes"] if n["kind"] == "category"])
        self.assertEqual(response.context["flow_query"], f"hide=cat%3A{self.food.pk}")
        self.assertContains(response, f"?month=2026-05&hide=cat%3A{self.food.pk}")
        # Hiding a category doesn't change Unassigned.
        self.assertEqual(response.context["unassigned"].amount, compute_unassigned(self.book, JUNE).amount)


class DollarFlowIsolationTest(ConsolidatedReportsBase):
    def test_other_books_accounts_stay_out(self):
        other = Team.objects.create(name="Other", slug="other-flow").default_book
        group = AccountGroup.objects.create(book=other, name="Zq Other Bank", account_type=ACCOUNT_TYPE_ASSET)
        account = Account.objects.create(book=other, name="Zq Other Checking", account_group=group)
        expense_group = AccountGroup.objects.create(book=other, name="Zq Other Home", account_type=ACCOUNT_TYPE_EXPENSE)
        expense = Account.objects.create(book=other, name="Zq Other Food", account_group=expense_group)
        set_budget(other, expense, JUNE, Decimal("50"))
        from apps.journal.models import JournalEntry, JournalLine

        entry = JournalEntry.objects.create(book=other, entry_date=JUNE, description="t")
        JournalLine.objects.create(book=other, journal_entry=entry, account=account, dr_amount=Decimal("999"))
        JournalLine.objects.create(book=other, journal_entry=entry, account=expense, cr_amount=Decimal("999"))
        self.post(JUNE, self.bank, self.salary, "100.00")

        self.assertEqual([a.name for a, _v in account_balances(self.book, JUNE)], ["Zq Checking"])
        response = self.client.get(self.url("budget_goals"), {"month": "2026-06"})
        self.assertNotContains(response, "Zq Other")
