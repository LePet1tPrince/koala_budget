"""
Data for the three consolidated reports (docs/reports-consolidation.md):

- spending_report: Income & Spending -- money in/out over a range (Income Statement + Cash Flow)
- net_worth_report: Net Worth -- balances and their change over a range (Balance Sheet + Net Worth Trend)
- budget_goals_report: Budget & Goals -- one month's plan (Budget vs Actual + Goal Progress + Dollar Map)

Each builder returns a plain dict for its template; the views only parse params.
"""

from datetime import date, timedelta
from decimal import Decimal

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME

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
    return {"sections": sections, "stats": stats, "chart_data": chart_data}


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
    """One month of the plan: Unassigned, goals, spending envelopes and (optionally) income."""
    from apps.budget.services import GoalService
    from apps.budget.unassigned import allocation_bar, compute_unassigned, waterfall

    month = month.replace(day=1)
    unassigned = compute_unassigned(book, month, detail=True)
    goal_rows, goal_totals = GoalService(book).month_rows(month)
    goal_totals.update(
        {
            "allocated": sum((r["goal"].allocated for r in goal_rows), ZERO),
            "target": sum((r["goal"].target_amount for r in goal_rows), ZERO),
            "left": sum((r["goal"].left for r in goal_rows), ZERO),
        }
    )
    goal_totals["pct"] = _pct(goal_totals["allocated"], goal_totals["target"])

    spending, income = _category_sections(book, month)
    return {
        "unassigned": unassigned,
        "bar": allocation_bar(unassigned),
        "steps": waterfall(unassigned),
        "goal_rows": goal_rows,
        "goal_totals": goal_totals,
        "spending": spending,
        "income": income,
    }


def _category_sections(book, month):
    """
    Envelope rows for every budgeted or active category this month.

    Spending rows are read as envelopes: what there was to spend is this month's
    assignment plus what rolled in, `available` is what is left of it (the budget
    page's figure), and the meter is spent against the former -- so a full meter
    and a zero Available are the same thing. Income rows (books that budget income
    before it lands) compare received against expected.
    """
    from apps.accounts.models import Account
    from apps.budget.models import Budget
    from apps.budget.services import BudgetService, budgeted_account_types

    types = budgeted_account_types(book)
    categories = list(
        Account.objects.filter(book=book, account_group__account_type__in=types)
        .select_related("account_group")
        .order_by("account_group__sort_order", "account_group__name", "sort_order", "name")
    )
    service = BudgetService(book)
    actuals = service.get_actuals_by_category(month)
    available, previous = service.get_available_with_previous(month, categories)
    budgets = dict(Budget.objects.filter(book=book, month=month).values_list("category_id", "budget_amount"))

    spending = _empty_section()
    income = _empty_section() if ACCOUNT_TYPE_INCOME in types else None
    for account in categories:
        assigned = budgets.get(account.pk, ZERO)
        actual = actuals.get(account.pk, ZERO)
        if account.account_group.account_type == ACCOUNT_TYPE_EXPENSE:
            rolled_in = previous.get(account.pk, ZERO)
            left = available.get(account.pk, ZERO)
            if not (assigned or actual or left):
                continue
            to_spend = assigned + max(rolled_in, ZERO)
            pct = _pct(actual, to_spend)
            row = {
                "account": account,
                "assigned": assigned,
                "rolled_in": rolled_in,
                "spent": actual,
                "available": left,
                "pct": pct,
                "pct_capped": max(min(pct, 100), 0) if pct is not None else (100 if actual > 0 else 0),
                "overspent": left < 0,
                "unbudgeted": not to_spend and actual > 0,
            }
            _add_row(spending, row, {"assigned": assigned, "spent": actual, "available": left})
            spending["overspent_count"] += 1 if row["overspent"] else 0
        elif income is not None:
            if not (assigned or actual):
                continue
            pct = _pct(actual, assigned)
            to_go = max(assigned - actual, ZERO)  # income beyond what was expected isn't "to go"
            row = {
                "account": account,
                "expected": assigned,
                "received": actual,
                "to_go": to_go,
                "pct": pct,
                "pct_capped": max(min(pct, 100), 0) if pct is not None else (100 if actual > 0 else 0),
            }
            _add_row(income, row, {"expected": assigned, "received": actual, "to_go": to_go})
    if income is not None and not income["groups"]:
        income = None
    return spending, income


def _empty_section():
    return {"groups": [], "totals": {}, "overspent_count": 0}


def _add_row(section, row, amounts):
    group = row["account"].account_group
    if not section["groups"] or section["groups"][-1]["group"].pk != group.pk:
        section["groups"].append({"group": group, "rows": [], "totals": {}})
    group_data = section["groups"][-1]
    group_data["rows"].append(row)
    for key, value in amounts.items():
        group_data["totals"][key] = group_data["totals"].get(key, ZERO) + value
        section["totals"][key] = section["totals"].get(key, ZERO) + value


def month_bounds(month):
    start = month.replace(day=1)
    return start, (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def shift_month(month, delta):
    index = month.year * 12 + month.month - 1 + delta
    return date(index // 12, index % 12 + 1, 1)
