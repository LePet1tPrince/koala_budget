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

# The jobs a viewer can hide whole, as `job:<key>` in the hidden set.
JOB_KEYS = ("goals", "envelopes", "unassigned")


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


def dollar_flow(unassigned, balances, goal_url=None, hidden=()):
    """
    The graph, its layout, a plain breakdown and the filter options for one month.

    `unassigned` is `compute_unassigned(..., detail=True)`; `balances` is
    `account_balances()` for the same month. `hidden` is a set of option values
    (see `_filters`) the viewer has switched off:

    - **Accounts** (assets, debts) leave the picture, and Net worth becomes the net
      worth of the accounts shown: "what if I left the house out?" The jobs keep
      their full claims, so what the shown accounts can't cover appears as the gap.
    - **Jobs, goals, budget groups and categories** leave the picture too, but the
      money they hold doesn't become free: it goes to one neutral "Hidden" node, so
      Unassigned stays the real figure.

    Returns {'empty': True, ...} when there is nothing to draw.
    """
    hidden = set(hidden)
    graph = _Graph()
    jobs_hidden = {job for job in JOB_KEYS if f"job:{job}" in hidden}

    # --- What you have: accounts → Assets → Net worth / Debts --------------------
    # A card in credit holds money for you and an overdrawn account is owed, so
    # each side is by sign, not by account type.
    all_holds = [{"key": f"acct:{a.pk}", "label": a.name, "amount": v} for a, v in balances if v > 0]
    all_owes = [{"key": f"acct:{a.pk}", "label": a.name, "amount": -v} for a, v in balances if v < 0]
    holds = [i for i in all_holds if i["key"] not in hidden]
    owes = [i for i in all_owes if i["key"] not in hidden]
    accounts_filtered = len(holds) < len(all_holds) or len(owes) < len(all_owes)
    total_held = sum((i["amount"] for i in holds), ZERO)
    total_owed = sum((i["amount"] for i in owes), ZERO)
    net_worth = total_held - total_owed

    assets = graph.node("assets", _("Assets"), total_held, COL_ASSETS, "assets") if total_held else None
    for idx, item in enumerate(
        _fold(holds, MAX_ASSETS, lambda n: ngettext("%(n)d other account", "%(n)d other accounts", n) % {"n": n})
    ):
        key = graph.node(f"asset:{idx}", item["label"], item["amount"], COL_ACCOUNTS, "asset")
        graph.link(key, assets, item["amount"])

    # --- The claims, all of them and the ones shown -------------------------------
    all_goals = [
        {
            "key": f"goal:{g['goal'].pk}",
            "label": g["name"],
            "amount": g["amount"],
            "url": goal_url(g["goal"]) if goal_url else None,
        }
        for g in unassigned.detail.get("goals", [])
        if g["amount"] > 0
    ]
    all_groups = _envelope_groups([e for e in unassigned.detail.get("envelopes", []) if e["amount"] > 0])
    goal_items = [] if "goals" in jobs_hidden else [g for g in all_goals if g["key"] not in hidden]
    groups = []
    if "envelopes" not in jobs_hidden:
        for group in all_groups:
            entries = [c for c in group["entries"] if c["key"] not in hidden]
            if group["key"] not in hidden and entries:
                groups.append({**group, "entries": entries, "amount": sum((c["amount"] for c in entries), ZERO)})
    goals_shown = sum((g["amount"] for g in goal_items), ZERO)
    envelopes_shown = sum((g["amount"] for g in groups), ZERO)

    # Every claim counts against net worth, shown or not: hiding a goal doesn't free its money.
    claims = unassigned.goals + unassigned.envelopes
    free = max(net_worth - claims, ZERO)  # unfiltered, exactly max(Unassigned, 0)
    hidden_amount = claims - goals_shown - envelopes_shown + (free if "unassigned" in jobs_hidden else ZERO)

    # --- Net worth, and any gap, are what the jobs share -------------------------
    worth = (
        graph.node("net_worth", _("Net worth"), net_worth, COL_WORTH, "net_worth") if assets and net_worth > 0 else None
    )
    # The jobs claim more than there is: the gap is its own source. Unfiltered, with
    # a positive net worth, it is exactly the Over-assigned figure.
    gap = max(claims - max(net_worth, ZERO), ZERO)
    if gap:
        if accounts_filtered:
            label = _("Not covered")
        elif net_worth < 0:
            label = _("Promised, not backed")
        else:
            label = unassigned.label
        graph.node("gap", label, gap, COL_WORTH, "gap")

    debts = graph.node("debts", _("Owed on debts"), total_owed, COL_WORTH, "debts") if total_owed else None
    if assets:
        graph.link(assets, worth, max(net_worth, ZERO))
        graph.link(assets, debts, min(total_held, total_owed))
    if total_owed > total_held:
        graph.node("debt_beyond", _("Debt beyond assets"), total_owed - total_held, COL_ASSETS, "gap")
        graph.link("debt_beyond", debts, total_owed - total_held)

    # --- The jobs ---------------------------------------------------------------
    free_label = _("Unassigned, these accounts") if accounts_filtered else unassigned.label
    sinks = []
    if goals_shown > 0:
        sinks.append((graph.node("goals", _("Goals"), goals_shown, COL_JOBS, "goals"), goals_shown))
    if envelopes_shown > 0:
        key = graph.node("envelopes", _("Budget envelopes"), envelopes_shown, COL_JOBS, "envelopes")
        sinks.append((key, envelopes_shown))
    if free > 0 and "unassigned" not in jobs_hidden:
        sinks.append((graph.node("unassigned", free_label, free, COL_JOBS, "unassigned"), free))
    if hidden_amount > 0:
        sinks.append((graph.node("hidden", _("Hidden"), hidden_amount, COL_JOBS, "hidden"), hidden_amount))
    _fill(graph, [(worth, max(net_worth, ZERO)), ("gap", gap)], sinks)

    for idx, item in enumerate(
        _fold(owes, MAX_DEBTS, lambda n: ngettext("%(n)d other debt", "%(n)d other debts", n) % {"n": n})
    ):
        key = graph.node(f"debt:{idx}", item["label"], item["amount"], COL_JOBS, "debt")
        graph.link(debts, key, item["amount"])

    # --- Each goal, each envelope -------------------------------------------------
    for idx, item in enumerate(
        _fold(goal_items, MAX_GOALS, lambda n: ngettext("%(n)d more goal", "%(n)d more goals", n) % {"n": n})
    ):
        key = graph.node(f"goal:{idx}", item["label"], item["amount"], COL_ITEMS, "goal", item.get("url"))
        graph.link("goals", key, item["amount"])

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

    filters = _filters(all_holds, all_owes, all_goals, all_groups, unassigned, hidden)
    filter_state = {
        "filters": filters,
        "hidden": [o["value"] for level in filters for o in level["options"] if o["hidden"]],
    }
    # Nothing but unbacked claims flowing into Hidden is nothing to look at.
    if all(link["source"] == "gap" and link["target"] == "hidden" for link in graph.links):
        return {"empty": True, **filter_state}

    layout = _layout(graph)
    total = sum((amount for _key, amount in sinks), ZERO)
    breakdown = {
        "holds": holds,
        "owes": owes,
        "total_held": total_held,
        "total_owed": total_owed,
        "net_worth": net_worth,
        # Net worth above is of the accounts shown; this is the whole book's.
        "book_net_worth": unassigned.net_worth if accounts_filtered else None,
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
        "jobs": _jobs(goal_items, groups, free, free_label, hidden_amount, total, jobs_hidden),
    }
    return {"empty": False, **layout, "breakdown": breakdown, **filter_state}


def _filters(holds, owes, goals, groups, unassigned, hidden):
    """
    One level per column of the drawing, each a list of options whose `value` is
    what `hidden` holds. A level with nothing in it is left out.
    """

    def option(value, label, amount, note=None):
        return {"value": value, "label": str(label), "amount": amount, "note": note, "hidden": value in hidden}

    claims = unassigned.goals + unassigned.envelopes
    jobs = [
        (f"job:{key}", label, amount)
        for key, label, amount in (
            ("goals", _("Goals"), unassigned.goals),
            ("envelopes", _("Budget envelopes"), unassigned.envelopes),
            ("unassigned", unassigned.label, max(unassigned.net_worth - claims, ZERO)),
        )
        if amount > 0
    ]
    levels = [
        ("assets", _("Assets"), [option(i["key"], i["label"], i["amount"]) for i in holds]),
        ("debts", _("Debts"), [option(i["key"], i["label"], i["amount"]) for i in owes]),
        ("jobs", _("Jobs"), [option(*job) for job in jobs]),
        ("goals", _("Goals"), [option(g["key"], g["label"], g["amount"]) for g in goals]),
        ("groups", _("Budget groups"), [option(g["key"], g["label"], g["amount"]) for g in groups]),
        (
            "categories",
            _("Categories"),
            [option(c["key"], c["label"], c["amount"], g["label"]) for g in groups for c in g["entries"]],
        ),
    ]
    return [
        {
            "key": key,
            "label": str(label),
            "options": options,
            "hidden_count": sum(1 for o in options if o["hidden"]),
        }
        for key, label, options in levels
        if options
    ]


def _envelope_groups(envelopes):
    """Envelopes by expense group, groups and categories largest first."""
    groups = {}
    for e in envelopes:
        account = e["account"]
        group = groups.setdefault(
            account.account_group_id,
            {"key": f"group:{account.account_group_id}", "label": e["group"], "amount": ZERO, "entries": []},
        )
        group["amount"] += e["amount"]
        group["entries"].append({"key": f"cat:{account.pk}", "label": e["name"], "amount": e["amount"]})
    ordered = sorted(groups.values(), key=lambda g: g["amount"], reverse=True)
    for group in ordered:
        group["entries"].sort(key=lambda i: i["amount"], reverse=True)
    return ordered


def _jobs(goal_items, groups, free, free_label, hidden_amount, total, jobs_hidden):
    """Every job shown and what's in it, unfolded, each with its share of the whole."""
    jobs = []
    if goal_items:
        items = sorted(goal_items, key=lambda i: i["amount"], reverse=True)
        amount = sum((i["amount"] for i in items), ZERO)
        jobs.append(
            {
                "key": "goals",
                "label": _("Goals"),
                "amount": amount,
                "pct": _pct(amount, total),
                "entries": [{**i, "pct": _pct(i["amount"], total)} for i in items],
            }
        )
    if groups:
        amount = sum((g["amount"] for g in groups), ZERO)
        jobs.append(
            {
                "key": "envelopes",
                "label": _("Budget envelopes"),
                "amount": amount,
                "pct": _pct(amount, total),
                "groups": [{**g, "pct": _pct(g["amount"], total)} for g in groups],
            }
        )
    if free > 0 and "unassigned" not in jobs_hidden:
        jobs.append({"key": "unassigned", "label": str(free_label), "amount": free, "pct": _pct(free, total)})
    if hidden_amount > 0:
        jobs.append({"key": "hidden", "label": _("Hidden"), "amount": hidden_amount, "pct": _pct(hidden_amount, total)})
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
