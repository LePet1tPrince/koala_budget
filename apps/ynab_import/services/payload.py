"""
What the wizard sees.

One module, so the shape the client reads is defined in one place rather than
spread across the views. Everything here is derived from an `Analysis` or an
`ImportPlan` -- no queries, no decisions.
"""

from decimal import Decimal

from .analyse import ASSET, DEFAULT_ACCOUNT_GROUPS, INCOME, LIABILITY, OTHER_INCOME, Analysis
from .build import EQUITY_TYPE, ImportPlan, category_key

TYPE_LABELS = {
    ASSET: "Things you own",
    LIABILITY: "Things you owe",
    "income": "Money coming in",
    "expense": "Money going out",
    EQUITY_TYPE: "Bookkeeping",
}


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _account_groups(analysis: Analysis) -> list[dict]:
    """
    The groups the accounts screen offers, each with the type it holds.

    Typed because a group in the app is: an account can only be placed in a group
    of its own type, so the screen offers a debt only the debt groups.
    """
    groups = [{"name": name, "account_type": account_type} for name, account_type in DEFAULT_ACCOUNT_GROUPS]
    offered = {(group["name"], group["account_type"]) for group in groups}
    for facts in analysis.accounts:
        if (facts.group, facts.account_type) not in offered:
            offered.add((facts.group, facts.account_type))
            groups.append({"name": facts.group, "account_type": facts.account_type})
    return groups


def analysis_payload(analysis: Analysis) -> dict:
    """Everything the review screens ask the user about, with the evidence behind it."""
    return {
        "accounts": [
            {
                "name": facts.name,
                "account_type": facts.account_type,
                "group": facts.group,
                "on_budget": facts.on_budget,
                "rows": facts.rows,
                "reason": facts.reason,
                "closing_balance": _money(facts.closing_balance),
                "starting_balance": _money(facts.starting_balance) if facts.starting_balance is not None else None,
                "first_date": facts.first_date.isoformat(),
                "last_date": facts.last_date.isoformat(),
                "has_feed": facts.suggested_feed,
            }
            for facts in analysis.accounts
        ],
        "income": [
            {
                "payee": facts.payee,
                # A blank payee is a real row in the export, and "" reads as a bug on
                # screen. Naming it is the difference between a question the user can
                # answer and one they cannot.
                "label": facts.payee or "(no payee)",
                "count": facts.count,
                "total": _money(facts.total),
                "kind": facts.kind,
                "account": facts.account,
            }
            for facts in analysis.income_payees
        ],
        "categories": [
            {
                "key": category_key(facts.group, facts.name),
                "group": facts.group,
                "name": facts.name,
                "kind": facts.kind,
                "transfer_legs": facts.transfer_legs,
                "plain_rows": facts.plain_rows,
                "saved": _money(facts.saved),
            }
            # Only the categories the user has a decision to make about: a savings
            # category can be a goal or a spending category, and nothing else in the
            # export is ambiguous enough to be worth a screen.
            for facts in analysis.categories
            if facts.transfer_legs or facts.kind != "expense"
        ],
        "groups": _account_groups(analysis),
        "income_accounts": sorted({facts.account for facts in analysis.income_payees if facts.kind == INCOME}),
        # Where a payee switched from "not income" back to income lands until the
        # user picks otherwise -- the same fallback `parse_choices` applies.
        "other_income": OTHER_INCOME,
    }


def plan_payload(plan: ImportPlan) -> dict:
    """The preview: what will be created, and everything the import decided."""
    return {
        "summary": plan.stats,
        "notes": plan.notes,
        "chart": chart_sections(plan),
        "goals": [
            {"name": goal.name, "target": _money(goal.target_amount), "months": len(goal.allocations)}
            for goal in plan.goals
        ],
    }


def chart_sections(plan: ImportPlan) -> list[dict]:
    """
    The chart of accounts as it will be created: type, then group, then account.

    The same shape the accounts board shows, so the preview and the page the user
    lands on read as the same thing.
    """
    by_group = {}
    for account in plan.accounts:
        by_group.setdefault((account.account_type, account.group), []).append(account)

    groups = {group.name: group for group in plan.groups}
    sections = []
    for account_type in (ASSET, LIABILITY, "income", "expense", EQUITY_TYPE):
        rows = [(group, accounts) for (kind, group), accounts in by_group.items() if kind == account_type]
        if not rows:
            continue
        sections.append(
            {
                "type": account_type,
                "label": TYPE_LABELS[account_type],
                "groups": [
                    {
                        "name": group,
                        "accounts": [account.name for account in accounts],
                    }
                    for group, accounts in sorted(rows, key=lambda row: groups[row[0]].sort_order)
                ],
            }
        )
    return sections
