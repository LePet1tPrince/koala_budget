import contextlib
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from apps.teams.decorators import login_and_team_required

# Forms are no longer needed as we use React components with URL parameters
from .exports import (
    export_account_activity_csv,
    export_balance_sheet_csv,
    export_income_statement_csv,
    export_transactions_csv,
)
from .services import ReportService


@login_and_team_required
def reports_home(request, team_slug):
    """
    Reports home page with navigation to different reports.
    """
    return render(
        request,
        "reports/reports_home.html",
        {
            "active_tab": "reports",
            "page_title": _("Reports"),
        },
    )


CHART_SERIES_LIMIT = 8  # matches the categorical palette in chart-theme.js


def _fold_group_series(groups, num_periods, limit=CHART_SERIES_LIMIT):
    """
    Turn grouped per-period report data into chart series, folding the tail
    beyond `limit` into a single "Other" series (categorical palettes don't
    stretch past the validated hue count).

    Input: [{'group': AccountGroup, 'per_period': [Decimal, ...]}, ...]
    Output: [{'name': str, 'values': [float, ...]}, ...] sorted largest-first.
    """
    series = [
        {
            "name": group_data["group"].name,
            "total": group_data["subtotal"],
            "values": [float(a) for a in group_data["per_period"]],
        }
        for group_data in groups
    ]
    series.sort(key=lambda s: s["total"], reverse=True)
    if len(series) > limit:
        head, tail = series[: limit - 1], series[limit - 1 :]
        other_values = [0.0] * num_periods
        for tail_series in tail:
            for i, value in enumerate(tail_series["values"]):
                other_values[i] += value
        head.append({"name": "Other", "total": Decimal("0"), "values": other_values})
        series = head
    for entry in series:
        del entry["total"]
    return series


@login_and_team_required
def income_statement(request, team_slug):
    """
    Income Statement (Profit & Loss) report view.
    """
    service = ReportService(request.team)

    report_data = None
    start_date = None
    end_date = None

    # Check for direct start_date and end_date parameters
    start_date_param = request.GET.get("start_date")
    end_date_param = request.GET.get("end_date")

    if start_date_param and end_date_param:
        # Parse dates directly from URL parameters
        try:
            start_date = datetime.strptime(start_date_param, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_param, "%Y-%m-%d").date()
        except ValueError:
            # Invalid date format, fall back to defaults
            today = date.today()
            start_date = today.replace(day=1)
            end_date = today
    else:
        # No parameters provided, set defaults for current month
        today = date.today()
        start_date = today.replace(day=1)
        end_date = today

    period_views = {"monthly": "month", "quarterly": "quarter", "yearly": "year"}
    period = period_views.get(request.GET.get("view"))
    report_data = service.get_income_statement_data(start_date, end_date, period=period)

    savings_rate = None
    if report_data and report_data["total_income"]:
        savings_rate = report_data["net_profit"] / report_data["total_income"] * 100

    # Querystrings for the Total / By Month|Quarter|Year display toggle (preserve other params)
    toggle_params = request.GET.copy()
    toggle_params.pop("view", None)
    total_view_qs = toggle_params.urlencode()
    period_view_qs = {}
    for view_name in period_views:
        toggle_params["view"] = view_name
        period_view_qs[view_name] = toggle_params.urlencode()

    sankey_data = None
    if report_data:
        sankey_data = {
            "income": [
                {
                    "name": item["account"].name,
                    "amount": float(item["amount"]),
                    "group": item["account"].account_group.name,
                }
                for item in report_data["income"]
            ],
            "expenses": [
                {
                    "name": item["account"].name,
                    "amount": float(item["amount"]),
                    "group": item["account"].account_group.name,
                }
                for item in report_data["expenses"]
            ],
            "income_groups": [
                {"name": group_data["group"].name, "amount": float(group_data["subtotal"])}
                for group_data in report_data["income_groups"]
            ],
            "expense_groups": [
                {"name": group_data["group"].name, "amount": float(group_data["subtotal"])}
                for group_data in report_data["expense_groups"]
            ],
            "net_profit": float(report_data["net_profit"]),
        }

    # Spending-by-group-over-time chart, only meaningful with a period breakdown
    trend_chart_data = None
    if period and report_data["periods"] and report_data["expense_groups"]:
        trend_chart_data = {
            "labels": report_data["period_labels"],
            "expense_groups": _fold_group_series(report_data["expense_groups"], len(report_data["periods"])),
        }

    return render(
        request,
        "reports/income_statement.html",
        {
            "active_tab": "reports",
            "page_title": _("Income Statement"),
            "report_data": report_data,
            "sankey_data": sankey_data,
            "trend_chart_data": trend_chart_data,
            "savings_rate": savings_rate,
            "period": period,
            "total_view_qs": total_view_qs,
            "period_view_qs": period_view_qs,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_and_team_required
def balance_sheet(request, team_slug):
    """
    Balance Sheet report view.
    """
    from urllib.parse import urlencode

    service = ReportService(request.team)

    # Check for direct as_of_date parameter
    as_of_date_param = request.GET.get("as_of_date")

    as_of_date = date.today()
    if as_of_date_param:
        # Parse date directly from URL parameter (invalid format falls back to today)
        with contextlib.suppress(ValueError):
            as_of_date = datetime.strptime(as_of_date_param, "%Y-%m-%d").date()

    report_data = service.get_balance_sheet_data(as_of_date)

    debt_ratio = None
    if report_data["total_assets"]:
        debt_ratio = report_data["total_liabilities"] / report_data["total_assets"] * 100

    # Account drill-down links: year-to-date activity up to the as-of date, with a
    # source marker so the activity page links back here.
    drill_qs = urlencode(
        {
            "source": "balance_sheet",
            "as_of_date": as_of_date.isoformat(),
            "start_date": date(as_of_date.year, 1, 1).isoformat(),
            "end_date": as_of_date.isoformat(),
        }
    )

    return render(
        request,
        "reports/balance_sheet.html",
        {
            "active_tab": "reports",
            "page_title": _("Balance Sheet"),
            "report_data": report_data,
            "as_of_date": as_of_date,
            "debt_ratio": debt_ratio,
            "drill_qs": drill_qs,
        },
    )


@login_and_team_required
def account_activity(request, team_slug, account_id):
    """
    Account activity drill-down view showing detailed transactions for a specific account.
    """
    from apps.accounts.models import Account

    service = ReportService(request.team)

    account = None
    report_data = None
    start_date = None
    end_date = None

    with contextlib.suppress(Account.DoesNotExist):
        account = Account.objects.get(team=request.team, pk=account_id)

    if account:
        # Check for direct start_date and end_date parameters
        start_date_param = request.GET.get("start_date")
        end_date_param = request.GET.get("end_date")

        if start_date_param and end_date_param:
            # Parse dates directly from URL parameters
            try:
                start_date = datetime.strptime(start_date_param, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_param, "%Y-%m-%d").date()
            except ValueError:
                # Invalid date format, fall back to defaults
                today = date.today()
                start_date = today.replace(day=1)
                end_date = today
        else:
            # No parameters provided, set defaults for current month
            today = date.today()
            start_date = today.replace(day=1)
            end_date = today

        report_data = service.get_account_activity(account, start_date, end_date)

    # Determine back navigation based on source parameter
    source = request.GET.get("source")
    if source == "budget":
        from django.urls import reverse

        back_url = reverse("budget:budget_home", args=[team_slug])
        if start_date:
            back_url += f"?month={start_date.isoformat()}"
        back_label = _("Back to Budget")
    elif source == "balance_sheet":
        from django.urls import reverse

        back_url = reverse("reports:balance_sheet", args=[team_slug])
        as_of_date_param = request.GET.get("as_of_date")
        if as_of_date_param:
            back_url += f"?as_of_date={as_of_date_param}"
        back_label = _("Back to Balance Sheet")
    else:
        from django.urls import reverse

        back_url = reverse("reports:income_statement", args=[team_slug])
        # Forward date params to income statement
        query_params = request.GET.copy()
        query_params.pop("source", None)
        if query_params:
            back_url += f"?{query_params.urlencode()}"
        back_label = _("Back to Summary")

    return render(
        request,
        "reports/account_activity.html",
        {
            "active_tab": "reports",
            "page_title": _("Account Activity"),
            "account": account,
            "report_data": report_data,
            "start_date": start_date,
            "end_date": end_date,
            "back_url": back_url,
            "back_label": back_label,
        },
    )


def _fold_float_series(series, limit=CHART_SERIES_LIMIT):
    """Fold chart series [{'name', 'values': [float, ...]}] beyond `limit` into an 'Other' series."""
    if len(series) <= limit:
        return series
    head, tail = series[: limit - 1], series[limit - 1 :]
    other_values = [0.0] * len(tail[0]["values"])
    for tail_series in tail:
        for i, value in enumerate(tail_series["values"]):
            other_values[i] += value
    head.append({"name": "Other", "values": other_values})
    return head


def _parse_month_range(request):
    """
    Parse start_month/end_month GET params (YYYY-MM) into a (start_date, end_date)
    range of whole months, defaulting to the last 12 months.
    """
    start_month_param = request.GET.get("start_month")
    end_month_param = request.GET.get("end_month")
    if start_month_param and end_month_param:
        try:
            start_year, start_month_num = map(int, start_month_param.split("-"))
            end_year, end_month_num = map(int, end_month_param.split("-"))
            start_date = date(start_year, start_month_num, 1)
            end_date = (date(end_year, end_month_num, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            return start_date, end_date
        except ValueError:
            pass
    today = date.today()
    return date(today.year - 1, today.month, 1), today


@login_and_team_required
def net_worth_trend(request, team_slug):
    """
    Net Worth Trend report view.
    """
    service = ReportService(request.team)

    report_data = None
    start_date = None
    end_date = None

    # Check for direct start_month and end_month parameters (YYYY-MM format)
    start_month_param = request.GET.get("start_month")
    end_month_param = request.GET.get("end_month")

    if start_month_param and end_month_param:
        try:
            # Parse YYYY-MM format
            start_year, start_month_num = map(int, start_month_param.split("-"))
            end_year, end_month_num = map(int, end_month_param.split("-"))

            # Create start_date as first day of start month
            start_date = date(start_year, start_month_num, 1)

            # Create end_date as last day of end month
            if end_month_num == 12:
                end_date = date(end_year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(end_year, end_month_num + 1, 1) - timedelta(days=1)

            report_data = service.get_net_worth_trend_data_by_date_range(start_date, end_date)
        except (ValueError, IndexError):
            # Invalid format, fall back to defaults
            today = date.today()
            start_date = date(today.year - 1, today.month, 1)
            end_date = today
            report_data = service.get_net_worth_trend_data_by_date_range(start_date, end_date)
    else:
        # No parameters provided, set defaults for last 12 months
        today = date.today()
        start_date = date(today.year - 1, today.month, 1)
        end_date = today
        report_data = service.get_net_worth_trend_data_by_date_range(start_date, end_date)

    # Month-over-month change for the table (first month has no prior point)
    previous_net_worth = None
    for item in report_data:
        item["change"] = item["net_worth"] - previous_net_worth if previous_net_worth is not None else None
        previous_net_worth = item["net_worth"]

    trend_stats = None
    chart_data = None
    if report_data:
        first, latest = report_data[0], report_data[-1]
        change = latest["net_worth"] - first["net_worth"]
        trend_stats = {
            "latest": latest,
            "change": change,
            "pct_change": change / abs(first["net_worth"]) * 100 if first["net_worth"] else None,
            "num_months": len(report_data),
        }
        chart_data = {
            "labels": [item["date"].isoformat() for item in report_data],
            "net_worth": [float(item["net_worth"]) for item in report_data],
            "assets": [float(item["assets"]) for item in report_data],
            "liabilities": [float(item["liabilities"]) for item in report_data],
        }

    # Composition tab: stacked-area balances per account group
    composition_chart_data = None
    if report_data:
        composition = service.get_balance_composition_data(start_date, end_date)
        if composition["asset_groups"] or composition["liability_groups"]:
            composition_chart_data = {
                "labels": composition["labels"],
                "asset_groups": _fold_float_series(composition["asset_groups"]),
                "liability_groups": _fold_float_series(composition["liability_groups"]),
            }

    return render(
        request,
        "reports/net_worth_trend.html",
        {
            "active_tab": "reports",
            "page_title": _("Net Worth Trend"),
            "report_data": report_data,
            "trend_stats": trend_stats,
            "chart_data": chart_data,
            "composition_chart_data": composition_chart_data,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_and_team_required
def cash_flow(request, team_slug):
    """
    Cash Flow report: money in vs money out per month with the net kept.
    """
    service = ReportService(request.team)
    start_date, end_date = _parse_month_range(request)
    data = service.get_income_statement_data(start_date, end_date, period="month")

    months = []
    for i, bucket in enumerate(data["periods"]):
        income = data["total_income_per_period"][i]
        expenses = data["total_expenses_per_period"][i]
        months.append(
            {
                "date": bucket,
                "label": data["period_labels"][i],
                "income": income,
                "expenses": expenses,
                "net": income - expenses,
            }
        )

    stats = {
        "total_income": data["total_income"],
        "total_expenses": data["total_expenses"],
        "net": data["net_profit"],
        "avg_net": data["net_profit"] / len(months) if months else Decimal("0"),
        "num_months": len(months),
    }
    chart_data = None
    if months:
        chart_data = {
            "labels": data["period_labels"],
            "income": [float(a) for a in data["total_income_per_period"]],
            "expenses": [float(a) for a in data["total_expenses_per_period"]],
            "net": [float(a) for a in data["net_profit_per_period"]],
        }

    return render(
        request,
        "reports/cash_flow.html",
        {
            "active_tab": "reports",
            "page_title": _("Cash Flow"),
            "months": months,
            "stats": stats,
            "chart_data": chart_data,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_and_team_required
def budget_vs_actual(request, team_slug):
    """
    Budget vs Actual report: per-category meters for a single month, grouped by account group.
    """
    from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME
    from apps.budget.models import Budget

    month = date.today().replace(day=1)
    month_param = request.GET.get("month")
    if month_param:
        with contextlib.suppress(ValueError):
            year, month_num = map(int, month_param.split("-"))
            month = date(year, month_num, 1)
    month_end = (month + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    service = ReportService(request.team)
    data = service.get_income_statement_data(month, month_end)
    budgets = Budget.objects.filter(team=request.team, month=month).select_related(
        "category", "category__account_group"
    )

    def build_section(items, budget_rows, spending=True):
        """Merge budgeted categories with actual activity into grouped meter rows."""
        actual_by_account = {item["account"].pk: item["amount"] for item in items}
        accounts = {item["account"].pk: item["account"] for item in items}
        budget_by_account = {}
        for budget in budget_rows:
            budget_by_account[budget.category_id] = budget.budget_amount
            accounts.setdefault(budget.category_id, budget.category)

        groups = {}
        totals = {"budget": Decimal("0"), "actual": Decimal("0"), "over_count": 0}
        for account_id, account in accounts.items():
            budget_amount = budget_by_account.get(account_id, Decimal("0"))
            actual = actual_by_account.get(account_id, Decimal("0"))
            if not budget_amount and not actual:
                continue
            over = spending and actual > budget_amount
            pct = float(actual / budget_amount * 100) if budget_amount else None
            row = {
                "account": account,
                "budget": budget_amount,
                "actual": actual,
                "remaining": budget_amount - actual,
                "pct": pct,
                "pct_capped": min(pct, 100) if pct is not None else (100 if actual else 0),
                "over": over,
                "unbudgeted": not budget_amount and bool(actual),
            }
            group = account.account_group
            group_data = groups.setdefault(
                group.pk, {"group": group, "rows": [], "budget": Decimal("0"), "actual": Decimal("0")}
            )
            group_data["rows"].append(row)
            group_data["budget"] += budget_amount
            group_data["actual"] += actual
            totals["budget"] += budget_amount
            totals["actual"] += actual
            totals["over_count"] += 1 if over else 0

        for group_data in groups.values():
            group_data["rows"].sort(key=lambda r: r["account"].name)
        section_groups = sorted(groups.values(), key=lambda g: g["group"].name)
        totals["remaining"] = totals["budget"] - totals["actual"]
        return section_groups, totals

    expense_budgets = [b for b in budgets if b.category.account_group.account_type == ACCOUNT_TYPE_EXPENSE]
    income_budgets = [b for b in budgets if b.category.account_group.account_type == ACCOUNT_TYPE_INCOME]
    expense_groups, expense_totals = build_section(data["expenses"], expense_budgets, spending=True)
    income_groups, income_totals = build_section(data["income"], income_budgets, spending=False)

    return render(
        request,
        "reports/budget_vs_actual.html",
        {
            "active_tab": "reports",
            "page_title": _("Budget vs Actual"),
            "month": month,
            "prev_month": (month - timedelta(days=1)).replace(day=1),
            "next_month": (month + timedelta(days=32)).replace(day=1),
            "expense_groups": expense_groups,
            "expense_totals": expense_totals,
            "income_groups": income_groups,
            "income_totals": income_totals,
        },
    )


@login_and_team_required
def goal_progress(request, team_slug):
    """
    Goal Progress report: cumulative savings per goal over time, with a projected
    path to each goal's target.
    """
    from django.db.models import Sum

    from apps.budget.models import Goal, GoalAllocation

    goals = list(Goal.objects.filter(team=request.team, is_archived=False).with_progress())

    allocation_rows = (
        GoalAllocation.objects.filter(team=request.team, goal__in=goals)
        .values("goal_id", "month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )
    allocations = {}  # goal id -> {month: Decimal}
    for row in allocation_rows:
        allocations.setdefault(row["goal_id"], {})[row["month"]] = row["total"]

    today_month = date.today().replace(day=1)

    # Month axis: earliest allocation through the latest of (today, last allocation, latest target date)
    all_months = [m for goal_months in allocations.values() for m in goal_months]
    axis_start = min(all_months, default=today_month)
    axis_end = max([today_month, *all_months, *[g.target_date.replace(day=1) for g in goals if g.target_date]])
    months = []
    current = axis_start
    while current <= axis_end:
        months.append(current)
        current = (current + timedelta(days=32)).replace(day=1)

    month_index = {month: i for i, month in enumerate(months)}
    chart_goals = []
    for goal in goals[:CHART_SERIES_LIMIT]:
        goal_allocations = allocations.get(goal.pk, {})
        actual = []
        running = Decimal("0")
        started = False
        for month in months:
            if month in goal_allocations:
                started = True
            running += goal_allocations.get(month, Decimal("0"))
            # Track record up to the current month; nothing to plot before the
            # first allocation or after today.
            actual.append(float(running) if started and month <= today_month else None)

        # Dashed projection from the current position to the target
        projection = [None] * len(months)
        if goal.target_date and goal.target_amount and not goal.is_complete:
            target_month = goal.target_date.replace(day=1)
            anchor_month = today_month if today_month in month_index else months[-1]
            if target_month in month_index and target_month > anchor_month:
                projection[month_index[anchor_month]] = float(running)
                projection[month_index[target_month]] = float(goal.target_amount)

        chart_goals.append({"name": goal.name, "actual": actual, "projection": projection})

    chart_data = None
    if goals and months:
        chart_data = {"labels": [m.isoformat() for m in months], "goals": chart_goals}

    # Table rows with the pace needed to hit each target on time
    goal_rows = []
    totals = {"saved": Decimal("0"), "target": Decimal("0")}
    for goal in goals:
        saved = goal.total_saved or Decimal("0")
        remaining = goal.target_amount - saved
        months_left = None
        needed_per_month = None
        if goal.target_date and goal.target_date >= date.today() and remaining > 0:
            target_month = goal.target_date.replace(day=1)
            months_left = max((target_month.year - today_month.year) * 12 + target_month.month - today_month.month, 1)
            needed_per_month = remaining / months_left
        goal_rows.append(
            {
                "goal": goal,
                "saved": saved,
                "remaining": remaining,
                "months_left": months_left,
                "needed_per_month": needed_per_month,
            }
        )
        totals["saved"] += saved
        totals["target"] += goal.target_amount

    totals["pct"] = totals["saved"] / totals["target"] * 100 if totals["target"] else None

    return render(
        request,
        "reports/goal_progress.html",
        {
            "active_tab": "reports",
            "page_title": _("Goal Progress"),
            "goal_rows": goal_rows,
            "totals": totals,
            "chart_data": chart_data,
            "num_charted": len(chart_goals),
            "num_goals": len(goals),
        },
    )


# --- Export Views ---


def _parse_date_range(request):
    """Parse start_date and end_date from GET params, with defaults to current month."""
    today = date.today()
    start_date_param = request.GET.get("start_date")
    end_date_param = request.GET.get("end_date")
    try:
        start_date = (
            datetime.strptime(start_date_param, "%Y-%m-%d").date() if start_date_param else today.replace(day=1)
        )  # noqa: E501
        end_date = datetime.strptime(end_date_param, "%Y-%m-%d").date() if end_date_param else today
    except ValueError:
        start_date = today.replace(day=1)
        end_date = today
    return start_date, end_date


@login_and_team_required
def export_income_statement(request, team_slug):
    """Export income statement as CSV."""
    start_date, end_date = _parse_date_range(request)
    return export_income_statement_csv(request.team, start_date, end_date)


@login_and_team_required
def export_balance_sheet(request, team_slug):
    """Export balance sheet as CSV."""
    as_of_date_param = request.GET.get("as_of_date")
    try:
        as_of_date = datetime.strptime(as_of_date_param, "%Y-%m-%d").date() if as_of_date_param else date.today()
    except ValueError:
        as_of_date = date.today()
    return export_balance_sheet_csv(request.team, as_of_date)


@login_and_team_required
def export_account_activity_view(request, team_slug, account_id):
    """Export account activity as CSV."""
    from apps.accounts.models import Account

    try:
        account = Account.objects.get(team=request.team, pk=account_id)
    except Account.DoesNotExist as err:
        from django.http import Http404

        raise Http404("Account not found") from err

    start_date, end_date = _parse_date_range(request)
    return export_account_activity_csv(request.team, account, start_date, end_date)


@login_and_team_required
def export_transactions(request, team_slug):
    """Export all transactions as CSV."""
    start_date, end_date = _parse_date_range(request)
    return export_transactions_csv(request.team, start_date, end_date)
