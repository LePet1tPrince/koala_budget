"""
Every figure the single-month budget page shows, computed in one place.

`budget_figures(book, month)` is what the page renders -- sections, groups and
rows with their Budgeted / Actual / Available and progress meter, section totals,
the per-tab sidebar summary and the net-worth card. `budget_cells` flattens the
same figures into `{cell key: {value, tone}}` for the endpoints that repaint the
page in place (auto-save, cover, the figures read after a recategorization), so
the page and those endpoints can never disagree about a number.
"""

from decimal import Decimal

from django.db.models import Case, IntegerField, Value, When
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account
from apps.web.templatetags.currency_tags import currency

from . import ledger as budget_ledger
from .forms import BudgetAmountForm
from .services import BudgetService, NetWorthService, budgeted_account_types


def _zero_totals():
    return {"budgeted": Decimal("0"), "actual": Decimal("0"), "available": Decimal("0")}


def budget_figures(book, month):
    """Every number the budget page shows for `month`, computed in one place.

    The month view renders these; the auto-save endpoint recomputes them and
    returns just the values (see `budget_cells`), so saving an amount updates
    the page in place instead of reloading it.
    """
    service = BudgetService(book)
    categories = list(budget_categories(book))

    budgeted_map = budget_ledger.budgeted_in_month(book, month)
    actuals_map = service.get_actuals_by_category(month)
    # This month's balances and last month's (what rolled in) from one walk of
    # the budget history.
    available_map, prev_available_map = service.get_available_with_previous(month, categories)

    # Income section first, then expenses; groups within a section keep the
    # category ordering (board sort order, then group/account name).
    sections = {
        "income": {"key": "income", "label": _("Income"), "groups": [], "totals": _zero_totals()},
        "expense": {"key": "expense", "label": _("Expenses"), "groups": [], "totals": _zero_totals()},
    }

    # A hidden category is a display choice, not an accounting one: it leaves its
    # account group for a collapsed "Hidden" group at the end of its section, and
    # its figures keep counting in the section totals, the sidebar and Unassigned.
    hidden_groups = {}

    for category in categories:
        budgeted = budgeted_map.get(category.pk, Decimal("0"))
        actual = actuals_map.get(category.pk, Decimal("0"))
        available = available_map.get(category.pk, Decimal("0"))

        section_key = "income" if category.account_group.account_type == "income" else "expense"
        section = sections[section_key]
        if category.hidden_from_budget:
            group = hidden_groups.setdefault(section_key, _hidden_group())
        else:
            group_name = category.account_group.name
            if not section["groups"] or section["groups"][-1]["name"] != group_name:
                section["groups"].append({"name": group_name, "rows": [], "subtotals": _zero_totals()})
            group = section["groups"][-1]

        # The input has no visible label — the category is its row header.
        form = BudgetAmountForm(initial={"budget_amount": budgeted} if budgeted else None)
        form.fields["budget_amount"].widget.attrs["aria-label"] = _("%(category)s budget") % {"category": category.name}

        group["rows"].append(
            {
                "category": category,
                "form": form,
                "budgeted": budgeted,
                "actual": actual,
                "available": available,
                "meter": meter(category.account_group.account_type, budgeted, actual, available),
            }
        )

        for field, amount in (("budgeted", budgeted), ("actual", actual), ("available", available)):
            group["subtotals"][field] += amount
            section["totals"][field] += amount

    for section_key, group in hidden_groups.items():
        group["overspent"] = sum(1 for row in group["rows"] if row["available"] < 0)
        sections[section_key]["groups"].append(group)
        sections[section_key]["hidden_count"] = len(group["rows"])

    # One tab per section the book budgets (no Income tab with future income off).
    section_list = [sections[key] for key in budget_tab_keys(book)]

    # Grand totals across both sections
    grand_totals = {
        field: sum((section["totals"][field] for section in section_list), Decimal("0"))
        for field in ("budgeted", "actual", "available")
    }

    # The sidebar summarises the tab on screen, so each section carries its own. A
    # section's key is its categories' account type.
    type_of = {category.pk: category.account_group.account_type for category in categories}
    sidebar_summary = {}
    for section in section_list:
        key = section["key"]
        rows = [row for group in section["groups"] for row in group["rows"]]
        section["overspent"] = sum(1 for row in rows if row["available"] < 0) if key == ACCOUNT_TYPE_EXPENSE else 0
        section["autofill"] = _autofill_actions(key)
        section["summary"] = sidebar_summary[key] = {
            "leftover_last_month": sum(
                (amount for pk, amount in prev_available_map.items() if type_of.get(pk) == key), Decimal("0")
            ),
            "assigned_this_month": section["totals"]["budgeted"],
            "activity_this_month": section["totals"]["actual"],
            "available": section["totals"]["available"],
        }

    return {
        "categories": categories,
        "sections": section_list,
        "has_categories": bool(categories),
        "grand_totals": grand_totals,
        "sidebar_summary": sidebar_summary,
        "net_worth_card": NetWorthService(book).get_net_worth_card_data(month, categories),
    }


def budget_tab_keys(book):
    """The budget page's tabs, in order: a section per category type the book budgets."""
    return ["income", "expense"] if ACCOUNT_TYPE_INCOME in budgeted_account_types(book) else ["expense"]


def _autofill_actions(section_key):
    """The sidebar's Auto-Assign buttons for a tab: `[{action, label, css}]`."""
    return [
        {"action": "assigned_last_month", "label": _("Assigned Last Month"), "css": "btn-soft btn-primary"},
        {
            "action": "spent_last_month",
            "label": _("Received Last Month") if section_key == "income" else _("Spent Last Month"),
            "css": "btn-soft btn-secondary",
        },
        {"action": "assign_zero", "label": _("Assign Zero"), "css": "btn-soft"},
        {"action": "reset_available_zero", "label": _("Reset Available to Zero"), "css": "btn-soft"},
    ]


def _hidden_group():
    return {"name": _("Hidden"), "hidden": True, "rows": [], "subtotals": _zero_totals()}


def meter(account_type, budgeted, actual, available):
    """The progress bar beside a budget row.

    Expense: spent against what there was to spend this month -- the budget plus
    whatever rolled in (the previous Available, which is `available − budgeted +
    actual`), so a full bar and a zero Available are the same thing. Red once
    Available is negative. Income: received against expected.
    """
    if account_type == "income":
        whole = budgeted
        over = False
    else:
        rolled_in = available - budgeted + actual
        whole = budgeted + max(rolled_in, Decimal("0"))
        over = available < 0
    pct = float(actual / whole * 100) if whole > 0 else None
    # No budget to measure against: a full bar if anything was spent, else empty.
    width = (100 if actual > 0 else 0) if pct is None else max(min(round(pct), 100), 0)
    return {
        "pct": pct,
        "width": width,
        "over": over,
        "income": account_type == "income",
        "label": f"{round(pct)}%" if pct is not None else "—",
    }


def _tone(amount):
    """Sign class hint for a money cell; mirrors the templates' text-error/text-success."""
    if amount < 0:
        return "neg"
    if amount > 0:
        return "pos"
    return ""


def budget_cells(figures):
    """Flatten `budget_figures` into `{cell key: {value, tone}}` for the auto-save
    response. Keys match the `data-budget-cell` attributes in the templates.

    Actuals are left out: a budget amount never moves them, and a recategorized
    transaction's actuals are updated by the Actual popover itself.
    """
    cells = {}

    def put(key, amount, toned=False):
        cells[key] = {"value": currency(amount), "tone": _tone(amount) if toned else ""}

    for section in figures["sections"]:
        for index, group in enumerate(section["groups"]):
            for row in group["rows"]:
                pk = row["category"].pk
                put(f"row:{pk}:available", row["available"], toned=True)
                meter = row["meter"]
                cells[f"row:{pk}:meter"] = {
                    "value": meter["label"],
                    "tone": "neg" if meter["over"] else "",
                    "width": meter["width"],
                }
                # Not rendered — the Auto-Assign confirm dialog reads it off the row checkbox.
                cells[f"row:{pk}:budgeted"] = {"value": f"{row['budgeted']:.2f}", "tone": ""}
            put(f"group:{section['key']}:{index}:budgeted", group["subtotals"]["budgeted"])
            put(f"group:{section['key']}:{index}:available", group["subtotals"]["available"], toned=True)
        put(f"section:{section['key']}:budgeted", section["totals"]["budgeted"])
        put(f"section:{section['key']}:available", section["totals"]["available"])

        put(f"tab:{section['key']}:budgeted", section["totals"]["budgeted"])
        if section["key"] == ACCOUNT_TYPE_EXPENSE:
            count = section["overspent"]
            cells["tab:expense:overspent"] = {
                "value": ngettext("%(count)s overspent", "%(count)s overspent", count) % {"count": count},
                "tone": "",
                "hidden": count == 0,
            }

    for key, summary in figures["sidebar_summary"].items():
        put(f"sidebar:{key}:assigned", summary["assigned_this_month"])
        put(f"sidebar:{key}:available", summary["available"], toned=True)

    card = figures["net_worth_card"]
    put("networth:net_worth", card["net_worth"])
    put("networth:income_due", card["income_due"])
    put("networth:spend", card["spend"])
    put("networth:save", card["save"])
    put("networth:available", card["available"], toned=True)
    # The line's own name flips to "Over-assigned" when the figure goes negative.
    cells["networth:label"] = {"value": str(card["label"]), "tone": ""}

    return cells


def budget_categories(book):
    """The categories a book budgets (see `budgeted_account_types`), in budget-table
    display order: income sections first, then expenses, each grouped alphabetically."""
    return (
        Account.objects.filter(book=book, account_group__account_type__in=budgeted_account_types(book))
        .select_related("account_group")
        .annotate(
            type_order=Case(
                When(account_group__account_type="income", then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("type_order", "account_group__sort_order", "account_group__name", "sort_order", "name")
    )
