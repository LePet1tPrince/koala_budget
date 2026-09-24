"""
The budget/actual merge shared by the Budget vs Actual report and the guided
monthly review's budget steps (§4.4/§4.6 of docs/monthly-review-plan.md).

`build_section` moved here verbatim from `apps.reports.views.budget_vs_actual`
(which now imports it) rather than being copied -- a second, divergent copy of
this merge would be a correctness bug waiting to happen.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE
from apps.budget.models import Budget
from apps.budget.services import BudgetService
from apps.budget.views import _budget_categories
from apps.journal.models import JournalLine, counted_entries


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
        group_data["rows"].sort(key=lambda r: (r["account"].sort_order, r["account"].name))
    section_groups = sorted(groups.values(), key=lambda g: (g["group"].sort_order, g["group"].name))
    totals["remaining"] = totals["budget"] - totals["actual"]
    return section_groups, totals


def _prev_month(month):
    if month.month == 1:
        return month.replace(year=month.year - 1, month=12)
    return month.replace(month=month.month - 1)


def _next_month(month):
    if month.month == 12:
        return month.replace(year=month.year + 1, month=1)
    return month.replace(month=month.month + 1)


def _month_bounds(month):
    start = month.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return start, end


def budget_breakdown(book, month) -> dict:
    """
    Every budgeted/spent category for `month`, grouped in budget-page order
    (income sections first), with the overspent-vs-over-assigned split.

    A category is *overspent* when its rollover `available` ends the month
    negative -- a real hole. It is merely *over-assigned* when spending beat
    the assignment but a carried-over cushion absorbed it (`available >= 0`).
    Only expense categories can be overspent; the rollover concept doesn't
    apply the same way to income falling short of its budget.

    Returns:
        {
          "groups": [{"name", "assigned", "spent", "prev", "available", "count",
                      "categories": [{"id", "name", "assigned", "spent", "prev",
                                      "available", "count", "unbudgeted"}, ...]}, ...],
          "totals": {"assigned", "spent", "available"},
          "overspent": [{"category", "group", "assigned", "spent", "available", "over"}, ...],
          "over_assigned": [ same shape, ...],
        }
    """
    categories = list(_budget_categories(book))
    category_ids = [c.pk for c in categories]
    month_start, month_end = _month_bounds(month)
    prev_month = _prev_month(month_start)

    service = BudgetService(book)
    this_actuals = service.get_actuals_by_category(month_start)
    prev_actuals = service.get_actuals_by_category(prev_month)
    available_map = service.get_available_by_category(month_start, categories)
    budgets = dict(
        Budget.objects.filter(book=book, month=month_start, category_id__in=category_ids).values_list(
            "category_id", "budget_amount"
        )
    )
    counts = dict(
        JournalLine.objects.filter(
            book=book,
            account_id__in=category_ids,
            journal_entry__entry_date__range=(month_start, month_end),
        )
        .filter(counted_entries("journal_entry__"))
        .values("account_id")
        .annotate(count=Count("id"))
        .values_list("account_id", "count")
    )

    groups = []
    current_group = None
    overspent = []
    over_assigned = []
    totals = {"assigned": Decimal("0"), "spent": Decimal("0"), "available": Decimal("0")}

    for category in categories:
        assigned = budgets.get(category.pk, Decimal("0"))
        spent = this_actuals.get(category.pk, Decimal("0"))
        if not assigned and not spent:
            continue
        prev = prev_actuals.get(category.pk, Decimal("0"))
        available = available_map.get(category.pk, Decimal("0"))
        count = counts.get(category.pk, 0)

        if current_group is None or current_group["_key"] != category.account_group.pk:
            current_group = {
                "_key": category.account_group.pk,
                "name": category.account_group.name,
                "assigned": Decimal("0"),
                "spent": Decimal("0"),
                "prev": Decimal("0"),
                "available": Decimal("0"),
                "count": 0,
                "categories": [],
            }
            groups.append(current_group)

        current_group["categories"].append(
            {
                "id": category.pk,
                "name": category.name,
                "assigned": assigned,
                "spent": spent,
                "prev": prev,
                "available": available,
                "count": count,
                "unbudgeted": not assigned and bool(spent),
            }
        )
        current_group["assigned"] += assigned
        current_group["spent"] += spent
        current_group["prev"] += prev
        current_group["available"] += available
        current_group["count"] += count

        totals["assigned"] += assigned
        totals["spent"] += spent
        totals["available"] += available

        if category.account_group.account_type == ACCOUNT_TYPE_EXPENSE and assigned and spent > assigned:
            row = {
                "category": category,
                "group": category.account_group,
                "assigned": assigned,
                "spent": spent,
                "available": available,
                "over": spent - assigned,
            }
            (overspent if available < 0 else over_assigned).append(row)

    for group in groups:
        del group["_key"]

    return {"groups": groups, "totals": totals, "overspent": overspent, "over_assigned": over_assigned}
