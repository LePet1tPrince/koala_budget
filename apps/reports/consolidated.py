"""
Data for the three consolidated reports (docs/reports-consolidation.md):

- spending_report: Income & Spending -- money in/out over a range (Income Statement + Cash Flow)
- net_worth_report: Net Worth -- balances and their change over a range (Balance Sheet + Net Worth Trend)
- budget_goals_report: Budget & Goals -- where every dollar is going (Dollar Map + Goal Progress);
  per-category budget progress lives on the budget page itself

Each builder returns a plain dict for its template; the views only parse params.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.utils.translation import gettext as _

from .services import ReportService

ZERO = Decimal("0")


def months_between(start_date, end_date):
    """Calendar months the range touches, inclusive."""
    return (end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1


def bucket_for(start_date, end_date):
    """Chart/column period for a range: monthly up to two years, then quarterly, then yearly."""
    months = months_between(start_date, end_date)
    if months <= 24:
        return "month"
    if months <= 96:
        return "quarter"
    return "year"


def _pct(part, whole):
    return part / whole * 100 if whole else None


# --- A. Income & Spending ---------------------------------------------------------


def spending_report(book, start_date, end_date):
    period = bucket_for(start_date, end_date)
    data = ReportService(book).get_income_statement_data(start_date, end_date, period=period)
    goal_spending = data["goal_spending"]
    num_months = months_between(start_date, end_date)

    stats = {
        "income": data["total_income"],
        "expenses": data["total_expenses"],
        "goal_spending": goal_spending["total"],
        "net": data["net_profit"],
        "net_after_goals": data["net_after_goal_spending"],
        "savings_rate": _pct(data["net_profit"], data["total_income"]),
        "avg_net": data["net_after_goal_spending"] / num_months,
        "num_months": num_months,
    }

    has_activity = bool(data["income"] or data["expenses"] or goal_spending["items"])
    chart_data = None
    if has_activity:
        chart_data = {
            "labels": data["period_labels"],
            "income": [float(a) for a in data["total_income_per_period"]],
            "expenses": [float(a) for a in data["total_expenses_per_period"]],
            "goal_spending": [float(a) for a in goal_spending["per_period"]] if goal_spending["items"] else None,
            "net": [float(a) for a in data["net_after_goal_spending_per_period"]],
        }

    sankey_data = None
    if has_activity:
        sankey_data = {
            "income": [_sankey_item(item) for item in data["income"]],
            "expenses": [_sankey_item(item) for item in data["expenses"]],
            "income_groups": [{"name": g["group"].name, "amount": float(g["subtotal"])} for g in data["income_groups"]],
            "expense_groups": [
                {"name": g["group"].name, "amount": float(g["subtotal"])} for g in data["expense_groups"]
            ],
            "net_profit": float(data["net_profit"]),
            "goal_spending": float(goal_spending["total"]),
        }

    return {
        "data": data,
        "period": period,
        "stats": stats,
        "chart_data": chart_data,
        "sankey_data": sankey_data,
    }


def _sankey_item(item):
    return {"name": item["account"].name, "amount": float(item["amount"]), "group": item["account"].account_group.name}


# --- B. Net Worth -----------------------------------------------------------------


def net_worth_report(book, start_date, end_date):
    """
    Balances at the start and end of the range, per account, group and section, plus
    the month-end trend. `end_date` should already be capped at today by the caller.
    """
    service = ReportService(book)
    opening = service.get_balance_sheet_data(start_date - timedelta(days=1))
    closing = service.get_balance_sheet_data(end_date)
    trend = service.get_net_worth_trend_data_by_date_range(start_date, end_date)

    sections = [
        _balance_section("assets", opening["assets"], closing["assets"]),
        _balance_section("liabilities", opening["liabilities"], closing["liabilities"]),
    ]
    start_worth = opening["net_worth"]
    end_worth = closing["net_worth"]
    change = end_worth - start_worth

    stats = {
        "net_worth": end_worth,
        "start_net_worth": start_worth,
        "change": change,
        "pct_change": _pct(change, abs(start_worth)),
        "assets": closing["total_assets"],
        "liabilities": closing["total_liabilities"],
        "debt_ratio": _pct(closing["total_liabilities"], closing["total_assets"]),
        "num_months": len(trend),
    }
    chart_data = None
    if trend:
        chart_data = {
            "labels": [point["date"].isoformat() for point in trend],
            "net_worth": [float(point["net_worth"]) for point in trend],
            "assets": [float(point["assets"]) for point in trend],
            "liabilities": [float(point["liabilities"]) for point in trend],
        }
    composition_data = None
    if trend:
        composition_data = net_worth_composition(service, start_date, end_date)
        composition_data["net_worth"] = chart_data["net_worth"]
        if not composition_data["groups"]:
            composition_data = None
    return {"sections": sections, "stats": stats, "chart_data": chart_data, "composition_data": composition_data}


# Band counts per side. Each side has its own validated hue order in
# net-worth-composition-chart.js; a longer tail folds into "Other".
COMPOSITION_ASSET_BANDS = 5
COMPOSITION_LIABILITY_BANDS = 3


def net_worth_composition(service, start_date, end_date):
    """
    Month-end balance per account group, each signed as its contribution to net
    worth: assets as dr − cr, liabilities as −(amount owed). Summed across groups,
    each month is exactly net worth, so the chart can stack assets above zero and
    debts below it with the net-worth line running through. A group can cross zero
    (an overdrawn account, a card in credit); the chart splits those values by sign.

    Returns {'labels': [iso month-end, ...], 'groups': [{'name', 'type', 'values'}]},
    assets first (largest first), then liabilities (largest debt first).
    """
    data = service.get_balance_composition_data(start_date, end_date)
    assets = _fold_side(data["asset_groups"], COMPOSITION_ASSET_BANDS, _("Other assets"))
    liabilities = _fold_side(data["liability_groups"], COMPOSITION_LIABILITY_BANDS, _("Other debts"))
    groups = [{"name": g["name"], "type": "asset", "values": g["values"]} for g in assets]
    groups += [{"name": g["name"], "type": "liability", "values": [-v for v in g["values"]]} for g in liabilities]
    return {"labels": data["labels"], "groups": groups}


def _fold_side(series, limit, other_name):
    """Keep the `limit - 1` largest series (by latest absolute balance) and sum the rest into one."""
    if len(series) <= limit:
        return series
    ranked = sorted(series, key=lambda s: abs(s["values"][-1]), reverse=True)
    head, tail = ranked[: limit - 1], ranked[limit - 1 :]
    other = [sum(values) for values in zip(*(s["values"] for s in tail), strict=True)]
    return [*head, {"name": other_name, "values": other}]


def _balance_section(key, opening_items, closing_items):
    """Merge two balance-sheet item lists into group/account rows with start, end and change."""
    accounts = {}
    for item in opening_items:
        accounts.setdefault(item["account"].pk, {"account": item["account"], "start": ZERO, "end": ZERO})
        accounts[item["account"].pk]["start"] = item["amount"]
    for item in closing_items:
        accounts.setdefault(item["account"].pk, {"account": item["account"], "start": ZERO, "end": ZERO})
        accounts[item["account"].pk]["end"] = item["amount"]

    groups = {}
    for row in accounts.values():
        row["change"] = row["end"] - row["start"]
        group = row["account"].account_group
        group_data = groups.setdefault(group.pk, {"group": group, "rows": [], "start": ZERO, "end": ZERO})
        group_data["rows"].append(row)
        group_data["start"] += row["start"]
        group_data["end"] += row["end"]

    ordered = sorted(groups.values(), key=lambda g: (g["group"].sort_order, g["group"].name))
    for group_data in ordered:
        group_data["rows"].sort(key=lambda r: (r["account"].sort_order, r["account"].name))
        group_data["change"] = group_data["end"] - group_data["start"]
    start = sum((g["start"] for g in ordered), ZERO)
    end = sum((g["end"] for g in ordered), ZERO)
    return {"key": key, "groups": ordered, "start": start, "end": end, "change": end - start}


# --- C. Budget & Goals ------------------------------------------------------------


def budget_goals_report(book, month):
    """
    Where every dollar of net worth is going for one month: goals (each listed),
    budget envelopes (one total -- the per-category detail lives on the budget
    page) and what is still unassigned.
    """
    from apps.budget.services import GoalService
    from apps.budget.unassigned import allocation_bar, compute_unassigned, waterfall

    month = month.replace(day=1)
    unassigned = compute_unassigned(book, month, detail=True)
    goal_rows, goal_totals = GoalService(book).month_rows(month)
    goal_totals.update(
        {
            "allocated": sum((r["goal"].allocated for r in goal_rows), ZERO),
            "target": sum((r["goal"].target_amount for r in goal_rows), ZERO),
            # Open-ended goals (no target) are left out of "X of Y saved".
            "toward_target": sum((r["goal"].allocated for r in goal_rows if r["goal"].has_target), ZERO),
            "left": sum((r["goal"].left for r in goal_rows), ZERO),
        }
    )
    goal_totals["pct"] = _pct(goal_totals["toward_target"], goal_totals["target"])

    # Envelopes as one figure: Σ max(0, available) over expense categories, split into
    # what rolled in from earlier months and this month's unspent budget (spending draws
    # on this month's budget first, so an envelope's rolled part is the smaller of
    # what rolled in and its balance). Overspent envelopes claim nothing -- that money already came out of
    # Unassigned -- and `overspent` is the negative balance they still carry.
    rollover = sum(
        (min(e["amount"], max(e["rollover"], ZERO)) for e in unassigned.detail["envelopes"] if e["amount"] > 0),
        ZERO,
    )
    envelopes = {
        "total": unassigned.envelopes,
        "rollover": rollover,
        "this_month": unassigned.envelopes - rollover,
        "overspent": unassigned.overspent,
    }
    return {
        "unassigned": unassigned,
        "bar": allocation_bar(unassigned),
        "waterfall": waterfall(unassigned),
        "goal_rows": goal_rows,
        "goal_totals": goal_totals,
        "envelopes": envelopes,
        "income_due": unassigned.income_due,
    }


def shift_month(month, delta):
    index = month.year * 12 + month.month - 1 + delta
    return date(index // 12, index % 12 + 1, 1)
