"""
The Dollar Flow: net worth broken down account by account, then every dollar of it
followed to its job -- each goal, each budget category, Unassigned.

    asset accounts → Assets → Net worth ─┬→ Goals            → each goal
                            ╰→ Debts ─┐  ├→ Budget envelopes → expense group → category
                                      │  ╰→ Unassigned
                                      ╰→ each debt

Every figure comes from `compute_unassigned(detail=True)` and the month-end balances
behind its net worth, so the picture adds up to the same Unassigned as every other
screen. Three rules keep it honest:

- **Conservation.** Every node's inflow equals its outflow. Assets less Debts is Net
  worth, and Net worth is what the jobs share. When the jobs claim more than that
  (Unassigned negative), the gap enters as its own source, drawn in the error
  colour, rather than being scaled away.
- **Pairing is by order, not by account.** Money is fungible: the picture says
  how much of what you have sits in each job, not which account holds it. Net worth
  fills the jobs in order, then the gap covers the rest.
- **Expected income is not money yet.** Like Unassigned itself, the flow counts
  income only once it is in net worth. Expected income is reported beside it in the
  breakdown, with how much of any gap it would cover.

Geometry is computed here, like `allocation_bar`, and drawn as plain SVG by
`templates/reports/components/dollar_flow.html`: no chart library, the theme's own
colours, and a `<title>` on every node and ribbon.
"""

from decimal import Decimal

from django.db.models import Sum
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY, Account
from apps.budget.unassigned import EXPECTED_INCOME_LABEL
from apps.utils.months import add_months

ZERO = Decimal("0")

# Geometry, in SVG user units. The drawing scales with its container; below
# MIN_WIDTH_PX the wrapper scrolls sideways instead of shrinking the text.
NODE_WIDTH = 12
COLUMN_STEP = 168
LABEL_ROOM = 160
COLUMNS = 6
WIDTH = (COLUMNS - 1) * COLUMN_STEP + NODE_WIDTH + LABEL_ROOM
BAR_HEIGHT = 420  # the tallest column's bars, end to end, before gaps
MIN_SLOT = 34  # a node's vertical room: two lines of label
GAP = 8
MIN_BAR = 2  # a non-zero node is never drawn thinner than this
MAX_LABEL = 22  # characters before a label is truncated (the <title> has it all)
MIN_WIDTH_PX = 880

# Longer lists fold their tail into one "N more" node. The breakdown lists everything.
MAX_ASSETS = 8
MAX_DEBTS = 6
MAX_GOALS = 10
MAX_CATEGORIES = 6

COL_ACCOUNTS, COL_ASSETS, COL_WORTH, COL_JOBS, COL_ITEMS, COL_CATEGORIES = range(COLUMNS)


def account_balances(book, month):
    """
    Each asset and liability account's balance at the end of `month`, signed as its
    contribution to net worth (assets dr − cr, debts the same, so negative). The
    same lines `NetWorthService.get_net_worth` sums, so the total is that figure.
    """
    from apps.journal.models import JournalLine, counted_entries

    rows = (
        JournalLine.objects.filter(
            book=book,
            journal_entry__entry_date__lt=add_months(month.replace(day=1), 1),
            account__account_group__account_type__in=(ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY),
        )
        .filter(counted_entries("journal_entry__"))
        .values("account_id")
        .annotate(dr=Sum("dr_amount"), cr=Sum("cr_amount"))
    )
    balances = {r["account_id"]: (r["dr"] or ZERO) - (r["cr"] or ZERO) for r in rows}
    accounts = Account.objects.filter(book=book, pk__in=balances.keys()).select_related("account_group")
    ordered = sorted(accounts, key=lambda a: (a.account_group.sort_order, a.sort_order, a.name))
    return [(account, balances[account.pk]) for account in ordered if balances[account.pk]]


def _truncate(text):
    text = str(text)
    return text if len(text) <= MAX_LABEL else f"{text[: MAX_LABEL - 1].rstrip()}…"


def _fold(items, limit, other_label):
    """Largest first; past `limit`, the tail becomes one item. Items are (label, amount, extra) dicts."""
    items = sorted(items, key=lambda i: i["amount"], reverse=True)
    if len(items) <= limit:
        return items
    head, tail = items[: limit - 1], items[limit - 1 :]
    return [*head, {"label": other_label(len(tail)), "amount": sum((i["amount"] for i in tail), ZERO), "folded": True}]


def _pct(part, whole):
    return float(part / whole * 100) if whole > 0 else 0.0


class _Graph:
    """Nodes and links in drawing order. A node's links out are added in its targets' order."""

    def __init__(self):
        self.nodes = {}
        self.links = []

    def node(self, key, label, amount, column, kind, url=None):
        self.nodes[key] = {
            "key": key,
            "label": str(label),
            "short": _truncate(label),
            "amount": amount,
            "column": column,
            "kind": kind,
            "url": url,
            "order": len(self.nodes),
        }
        return key

    def link(self, source, target, amount):
        if amount > 0:
            self.links.append({"source": source, "target": target, "amount": amount})


def _fill(graph, sources, sinks):
    """Pair sources with sinks in order, each giving until it runs out: totals must match."""
    sources = [[key, amount] for key, amount in sources if amount > 0]
    sinks = [[key, amount] for key, amount in sinks if amount > 0]
    i = j = 0
    while i < len(sources) and j < len(sinks):
        amount = min(sources[i][1], sinks[j][1])
        graph.link(sources[i][0], sinks[j][0], amount)
        sources[i][1] -= amount
        sinks[j][1] -= amount
        if sources[i][1] <= 0:
            i += 1
        if sinks[j][1] <= 0:
            j += 1


def dollar_flow(unassigned, balances, goal_url=None):
    """
    The graph, its layout and a plain breakdown for one month.

    `unassigned` is `compute_unassigned(..., detail=True)`; `balances` is
    `account_balances()` for the same month. Returns {'empty': True} when there is
    nothing to draw.
    """
    graph = _Graph()

    # --- What you have: accounts → Assets → Net worth / Debts --------------------
    # A card in credit holds money for you and an overdrawn account is owed, so
    # each side is by sign, not by account type.
    holds = [{"label": a.name, "amount": v, "account": a} for a, v in balances if v > 0]
    owes = [{"label": a.name, "amount": -v, "account": a} for a, v in balances if v < 0]
    total_held = sum((i["amount"] for i in holds), ZERO)
    total_owed = sum((i["amount"] for i in owes), ZERO)
    net_worth = total_held - total_owed

    assets = graph.node("assets", _("Assets"), total_held, COL_ASSETS, "assets") if total_held else None
    for idx, item in enumerate(
        _fold(holds, MAX_ASSETS, lambda n: ngettext("%(n)d other account", "%(n)d other accounts", n) % {"n": n})
    ):
        key = graph.node(f"asset:{idx}", item["label"], item["amount"], COL_ACCOUNTS, "asset")
        graph.link(key, assets, item["amount"])

    # --- Net worth, and any gap, are what the jobs share -------------------------
    worth = (
        graph.node("net_worth", _("Net worth"), net_worth, COL_WORTH, "net_worth") if assets and net_worth > 0 else None
    )
    goals_left = [g for g in unassigned.detail.get("goals", []) if g["amount"] > 0]
    envelopes = [e for e in unassigned.detail.get("envelopes", []) if e["amount"] > 0]
    claims = unassigned.goals + unassigned.envelopes
    free = max(unassigned.amount, ZERO)
    # The jobs claim more than there is: the gap is its own source. With a positive
    # net worth it is exactly the Over-assigned figure.
    gap = max(claims + free - max(net_worth, ZERO), ZERO)
    if gap:
        label = unassigned.label if net_worth >= 0 else _("Promised, not backed")
        graph.node("gap", label, gap, COL_WORTH, "gap")

    debts = graph.node("debts", _("Owed on debts"), total_owed, COL_WORTH, "debts") if total_owed else None
    if assets:
        graph.link(assets, worth, max(net_worth, ZERO))
        graph.link(assets, debts, min(total_held, total_owed))
    if total_owed > total_held:
        graph.node("debt_beyond", _("Debt beyond assets"), total_owed - total_held, COL_ASSETS, "gap")
        graph.link("debt_beyond", debts, total_owed - total_held)

    # --- The jobs ---------------------------------------------------------------
    sinks = []
    if unassigned.goals > 0:
        sinks.append((graph.node("goals", _("Goals"), unassigned.goals, COL_JOBS, "goals"), unassigned.goals))
    if unassigned.envelopes > 0:
        key = graph.node("envelopes", _("Budget envelopes"), unassigned.envelopes, COL_JOBS, "envelopes")
        sinks.append((key, unassigned.envelopes))
    if free > 0:
        sinks.append((graph.node("unassigned", unassigned.label, free, COL_JOBS, "unassigned"), free))
    _fill(graph, [(worth, max(net_worth, ZERO)), ("gap", gap)], sinks)

    for idx, item in enumerate(
        _fold(owes, MAX_DEBTS, lambda n: ngettext("%(n)d other debt", "%(n)d other debts", n) % {"n": n})
    ):
        key = graph.node(f"debt:{idx}", item["label"], item["amount"], COL_JOBS, "debt")
        graph.link(debts, key, item["amount"])

    # --- Each goal, each envelope -------------------------------------------------
    goal_items = [
        {"label": g["name"], "amount": g["amount"], "url": goal_url(g["goal"]) if goal_url else None}
        for g in goals_left
    ]
    for idx, item in enumerate(
        _fold(goal_items, MAX_GOALS, lambda n: ngettext("%(n)d more goal", "%(n)d more goals", n) % {"n": n})
    ):
        key = graph.node(f"goal:{idx}", item["label"], item["amount"], COL_ITEMS, "goal", item.get("url"))
        graph.link("goals", key, item["amount"])

    groups = _envelope_groups(envelopes)
    for g_idx, group in enumerate(groups):
        group_key = graph.node(f"group:{g_idx}", group["label"], group["amount"], COL_ITEMS, "group")
        graph.link("envelopes", group_key, group["amount"])
        for c_idx, item in enumerate(
            _fold(
                group["entries"],
                MAX_CATEGORIES,
                lambda n: ngettext("%(n)d more category", "%(n)d more categories", n) % {"n": n},
            )
        ):
            key = graph.node(f"category:{g_idx}:{c_idx}", item["label"], item["amount"], COL_CATEGORIES, "category")
            graph.link(group_key, key, item["amount"])

    if not graph.links:
        return {"empty": True}

    layout = _layout(graph)
    total = sum((amount for _key, amount in sinks), ZERO)
    breakdown = {
        "holds": holds,
        "owes": owes,
        "total_held": total_held,
        "total_owed": total_owed,
        "net_worth": net_worth,
        "gap": gap,
        "gap_label": graph.nodes["gap"]["label"] if gap else None,
        # Beside the flow, never in it; only for books that budget income ahead.
        "expected": {
            "label": str(EXPECTED_INCOME_LABEL),
            "amount": unassigned.income_due,
            "covers": min(unassigned.income_due, gap),
        }
        if unassigned.expects_income
        else None,
        "total": total,
        "jobs": _jobs(graph, goal_items, groups, free, total, unassigned),
    }
    return {"empty": False, **layout, "breakdown": breakdown}


def _envelope_groups(envelopes):
    """Envelopes by expense group, groups and categories largest first."""
    groups = {}
    for e in envelopes:
        account = e.get("account")
        key = account.account_group_id if account is not None else e["group"]
        group = groups.setdefault(key, {"label": e["group"], "amount": ZERO, "entries": []})
        group["amount"] += e["amount"]
        group["entries"].append({"label": e["name"], "amount": e["amount"]})
    ordered = sorted(groups.values(), key=lambda g: g["amount"], reverse=True)
    for group in ordered:
        group["entries"].sort(key=lambda i: i["amount"], reverse=True)
    return ordered


def _jobs(graph, goal_items, groups, free, total, unassigned):
    """Every job and what's in it, unfolded, each with its share of the whole."""
    jobs = []
    if unassigned.goals > 0:
        items = sorted(goal_items, key=lambda i: i["amount"], reverse=True)
        for item in items:
            item["pct"] = _pct(item["amount"], total)
        jobs.append(
            {
                "key": "goals",
                "label": graph.nodes["goals"]["label"],
                "amount": unassigned.goals,
                "pct": _pct(unassigned.goals, total),
                "entries": items,
            }
        )
    if unassigned.envelopes > 0:
        for group in groups:
            group["pct"] = _pct(group["amount"], total)
            for item in group["entries"]:
                item["pct"] = _pct(item["amount"], total)
        jobs.append(
            {
                "key": "envelopes",
                "label": graph.nodes["envelopes"]["label"],
                "amount": unassigned.envelopes,
                "pct": _pct(unassigned.envelopes, total),
                "groups": groups,
            }
        )
    if free > 0:
        jobs.append({"key": "unassigned", "label": str(unassigned.label), "amount": free, "pct": _pct(free, total)})
    return jobs


def _layout(graph):
    """
    Place nodes column by column. A node starts level with the slice of its first
    source that feeds it, or below the node before it, whichever is lower; so each
    node sits beside what it came from and nothing overlaps.
    """
    nodes = sorted(graph.nodes.values(), key=lambda n: (n["column"], n["order"]))
    column_totals = {}
    for node in nodes:
        column_totals[node["column"]] = column_totals.get(node["column"], ZERO) + node["amount"]
    biggest = max(column_totals.values())
    scale = BAR_HEIGHT / float(biggest) if biggest > 0 else 0.0

    outgoing, incoming = {}, {}
    for link in graph.links:
        outgoing.setdefault(link["source"], []).append(link)
        incoming.setdefault(link["target"], []).append(link)

    cursors = {}
    for node in nodes:
        node["h"] = max(float(node["amount"]) * scale, MIN_BAR)
        node["x"] = node["column"] * COLUMN_STEP
        node["label_x"] = node["x"] + NODE_WIDTH + 6
        wanted = min((link["sy"] for link in incoming.get(node["key"], []) if "sy" in link), default=0.0)
        node["y"] = max(cursors.get(node["column"], 0.0), wanted)
        cursors[node["column"]] = node["y"] + max(node["h"], MIN_SLOT) + GAP
        # Slices out, in link order; slices in are stacked as their sources are placed.
        offset = node["y"]
        for link in outgoing.get(node["key"], []):
            link["sy"] = offset
            link["h"] = float(link["amount"]) * scale
            offset += link["h"]

    for node in nodes:
        offset = node["y"]
        for link in incoming.get(node["key"], []):
            link["ty"] = offset
            offset += link["h"]
        node["label_y"] = node["y"] + node["h"] / 2 if node["h"] >= MIN_SLOT else node["y"] + MIN_SLOT / 2 - 2

    by_key = {n["key"]: n for n in nodes}
    links = []
    for link in graph.links:
        source, target = by_key[link["source"]], by_key[link["target"]]
        x0 = source["x"] + NODE_WIDTH
        x1 = target["x"]
        mid = (x0 + x1) / 2
        h = max(link["h"], 1.0)
        y0, y1 = link["sy"], link["ty"]
        links.append(
            {
                **link,
                "source_label": source["label"],
                "target_label": target["label"],
                "kind": _link_kind(source, target),
                "path": (
                    f"M{x0:.1f},{y0:.1f} C{mid:.1f},{y0:.1f} {mid:.1f},{y1:.1f} {x1:.1f},{y1:.1f} "
                    f"L{x1:.1f},{y1 + h:.1f} C{mid:.1f},{y1 + h:.1f} {mid:.1f},{y0 + h:.1f} {x0:.1f},{y0 + h:.1f} Z"
                ),
            }
        )
    height = max(cursors.values()) - GAP + 2
    return {
        "nodes": nodes,
        "links": links,
        "width": WIDTH,
        "height": round(height, 1),
        "node_width": NODE_WIDTH,
        "min_width_px": MIN_WIDTH_PX,
    }


def _link_kind(source, target):
    """A ribbon takes the colour of where the money goes, except into Net worth, which is neutral."""
    if target["kind"] in ("net_worth", "assets"):
        return "neutral" if source["kind"] != "gap" else "gap"
    if source["kind"] == "gap":
        return "gap"
    return {"goal": "goals", "group": "envelopes", "category": "envelopes", "debt": "debts"}.get(
        target["kind"], target["kind"]
    )
