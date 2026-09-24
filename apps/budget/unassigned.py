"""
The Unassigned metric: money that has no job yet (see docs/unassigned-plan.md).

    unassigned = net worth
               + income budgeted this month and not yet received
               − every expense envelope's balance (unspent budget, rollover included)
               − every goal's left (allocated − spent from it)

`compute_unassigned()` is the one place this is calculated. The sidebar pill, the
dashboard, the budget/goals card (via `NetWorthService.get_net_worth_card_data`), the
goal quick-assign clamp and the Dollar Map report all read it, so no two screens can
disagree about the number.

Income is deliberately *not* summed through the budget page's per-category income
"available" (actual − budget + rollover). Carried forward, that figure turns every
past month's shortfall into income still "due" forever (budget $5,000, earn $4,800,
and $200 of phantom money joins Unassigned every month), and it holds back any
income earned over budget instead of letting it arrive as money with no job. What
counts is this month's budgeted income that has not landed yet, and only while the
month is still running: once a month is over, whatever didn't arrive never will.

A goal is an envelope that never resets (docs/goals-envelopes-plan.md): spending
from it is a real transaction categorized to its account, which lowers net worth
and the goal's claim by the same amount, so Unassigned doesn't move when you spend
money you saved for. Spending counts through the end of `month`, like net worth.

Overspending is carried, never forced: an overspent envelope keeps its negative
balance, which (being subtracted) leaves Unassigned where it was. The shortfall
stays visible on the envelope that caused it rather than being pulled out of
Unassigned, and covering it is the user's choice.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account

ZERO = Decimal("0")

# The metric's name is still being decided; every template and script reads these.
UNASSIGNED_LABEL = _("Unassigned")
OVER_ASSIGNED_LABEL = _("Over-assigned")

STATE_POSITIVE = "positive"
STATE_ZERO = "zero"
STATE_NEGATIVE = "negative"


@dataclass(frozen=True)
class Unassigned:
    """Every term of the Unassigned sum for one month, plus the result."""

    month: date
    net_worth: Decimal
    income_due: Decimal
    rollover: Decimal  # expense envelopes carried in from last month
    this_month: Decimal  # this month's expense budget, not yet spent
    goals_before: Decimal
    goals_this_month: Decimal
    goals_spent: Decimal = ZERO  # spent from goals through month end
    # Per-account detail, filled only when asked for (the Dollar Map report).
    detail: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def envelopes(self) -> Decimal:
        return self.rollover + self.this_month

    @property
    def goals(self) -> Decimal:
        """Σ left over goals: what they have been given, less what was spent from them."""
        return self.goals_before + self.goals_this_month - self.goals_spent

    @property
    def amount(self) -> Decimal:
        return self.net_worth + self.income_due - self.envelopes - self.goals

    @property
    def state(self) -> str:
        amount = self.amount
        if amount < 0:
            return STATE_NEGATIVE
        return STATE_POSITIVE if amount > 0 else STATE_ZERO

    @property
    def label(self):
        return OVER_ASSIGNED_LABEL if self.state == STATE_NEGATIVE else UNASSIGNED_LABEL


def budget_categories(team):
    """Income and expense accounts, with the group loaded for the type checks."""
    return list(
        Account.objects.filter(
            team=team, account_group__account_type__in=(ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME)
        ).select_related("account_group")
    )


def compute_unassigned(team, month: date, categories=None, today: date | None = None, detail=False) -> Unassigned:
    """
    Unassigned as of the end of `month`.

    `categories` may be passed by a caller that already loaded them (the budget
    page); anything that isn't an income or expense account is ignored. With
    `detail=True` the result also carries the per-goal, per-envelope and per-income
    figures the Dollar Map report breaks the total down into.
    """
    from apps.budget.models import Budget, Goal, GoalAllocation, month_after
    from apps.budget.services import BudgetService, NetWorthService
    from apps.journal.models import JournalLine, counted_entries

    month = month.replace(day=1)
    today = today or date.today()
    if categories is None:
        categories = budget_categories(team)
    expense = [c for c in categories if c.account_group.account_type == ACCOUNT_TYPE_EXPENSE]
    income = [c for c in categories if c.account_group.account_type == ACCOUNT_TYPE_INCOME]

    service = BudgetService(team)
    available, previous = service.get_available_with_previous(month, expense)

    # Income still to come: only this month's, and only while the month is running.
    income_due_by_account = {}
    if income and month >= today.replace(day=1):
        income_ids = {c.pk for c in income}
        budgets = {
            b.category_id: b.budget_amount
            for b in Budget.objects.filter(team=team, month=month, category_id__in=income_ids)
        }
        actuals = service.get_actuals_by_category(month)
        for account in income:
            due = budgets.get(account.pk, ZERO) - actuals.get(account.pk, ZERO)
            if due > 0:
                income_due_by_account[account.pk] = due

    goal_totals = GoalAllocation.objects.filter(team=team, goal__is_archived=False).aggregate(
        before=Sum("amount", filter=Q(month__lt=month), default=ZERO),
        this_month=Sum("amount", filter=Q(month__gte=month), default=ZERO),
    )
    spent = JournalLine.objects.filter(
        counted_entries("journal_entry__"),
        team=team,
        account__goal__isnull=False,
        account__goal__is_archived=False,
        journal_entry__entry_date__lt=month_after(month),
    ).aggregate(total=Sum(F("dr_amount") - F("cr_amount"), default=ZERO))["total"]

    rollover = sum(previous.values(), ZERO)
    result = Unassigned(
        month=month,
        net_worth=NetWorthService(team).get_net_worth(month),
        income_due=sum(income_due_by_account.values(), ZERO),
        rollover=rollover,
        this_month=sum(available.values(), ZERO) - rollover,
        goals_before=goal_totals["before"],
        goals_this_month=goal_totals["this_month"],
        goals_spent=spent,
    )
    if not detail:
        return result

    by_id = {c.pk: c for c in categories}
    goals = [
        g
        for g in Goal.objects.filter(team=team, is_archived=False)
        .with_progress(month)
        .order_by("order", "target_date", "name")
        if g.allocated or g.spent
    ]
    result.detail.update(
        {
            # `amount` is the goal's claim (left); allocated and spent explain it.
            "goals": [
                {"name": g.name, "amount": g.left, "allocated": g.allocated, "spent": g.spent, "goal": g} for g in goals
            ],
            "envelopes": [
                {
                    "name": by_id[pk].name,
                    "group": by_id[pk].account_group.name,
                    "amount": amount,
                    "rollover": previous.get(pk, ZERO),
                }
                for pk, amount in available.items()
                if amount != 0
            ],
            "income_due": [{"name": by_id[pk].name, "amount": due} for pk, due in income_due_by_account.items()],
        }
    )
    return result


def pill_context(unassigned: Unassigned) -> dict:
    """What the pill and the JSON endpoint need: the figure, its state and its words."""
    from apps.web.templatetags.currency_tags import currency

    amount = unassigned.amount
    return {
        "amount": float(amount),
        # A plain string for templates, which would otherwise localize a float.
        "raw": f"{amount:.2f}",
        "display": currency(amount),
        "state": unassigned.state,
        "label": str(unassigned.label),
        "month": unassigned.month.isoformat(),
    }


# --- Dollar Map report ----------------------------------------------------------


def _pct(value: Decimal, scale: Decimal) -> float:
    if scale <= 0:
        return 0.0
    return round(float(max(min(value / scale, Decimal("1")), ZERO) * 100), 3)


def allocation_bar(unassigned: Unassigned) -> dict:
    """
    Geometry for the allocation bar: every claim on your money side by side.

    Segments are goals, budget envelopes and (when positive) Unassigned. A marker
    sits at net worth, and a second at net worth + income still due when some is.
    The claims can reach past what you have for two reasons, which are the only
    ways the sum can overshoot (the identity is checked in the tests): the total
    is over-assigned, or envelopes/goals are overspent and carried negative. That
    overshoot is drawn hatched and explained rather than silently rescaled away.
    """
    detail = unassigned.detail
    goals_pos = sum((g["amount"] for g in detail["goals"] if g["amount"] > 0), ZERO)
    env_pos = sum((e["amount"] for e in detail["envelopes"] if e["amount"] > 0), ZERO)
    carried = -sum((e["amount"] for e in detail["envelopes"] if e["amount"] < 0), ZERO) - sum(
        (g["amount"] for g in detail["goals"] if g["amount"] < 0), ZERO
    )
    amount = unassigned.amount
    free = max(amount, ZERO)
    have = unassigned.net_worth + unassigned.income_due
    filled = goals_pos + env_pos + free
    scale = max(filled, have)

    segments = [
        {"key": "goals", "label": _("Goals"), "amount": goals_pos},
        {"key": "envelopes", "label": _("Budget envelopes"), "amount": env_pos},
        {"key": "unassigned", "label": unassigned.label, "amount": free},
    ]
    for segment in segments:
        segment["pct"] = _pct(segment["amount"], scale)

    overshoot = filled - max(have, ZERO)
    return {
        "segments": [s for s in segments if s["amount"] > 0],
        "empty": scale <= 0,
        "net_worth_pct": _pct(unassigned.net_worth, scale) if unassigned.net_worth > 0 else None,
        "with_due_pct": _pct(have, scale) if unassigned.income_due > 0 and have > 0 else None,
        "overshoot": {
            "start_pct": _pct(max(have, ZERO), scale),
            "width_pct": _pct(overshoot, scale),
            "over_assigned": max(-amount, ZERO),
            "carried": carried,
        }
        if overshoot > Decimal("0.005")
        else None,
    }


def waterfall(unassigned: Unassigned) -> list[dict]:
    """Net worth stepping down to Unassigned, one floating bar per term."""
    steps = [("net_worth", _("Net worth"), unassigned.net_worth, True)]
    if unassigned.income_due:
        steps.append(("income_due", _("Income still due"), unassigned.income_due, False))
    steps += [
        ("rollover", _("Envelopes rolled over"), -unassigned.rollover, False),
        ("this_month", _("This month's budget, unspent"), -unassigned.this_month, False),
        ("goals_before", _("Goals, earlier months"), -unassigned.goals_before, False),
        ("goals_this_month", _("Goals, this month"), -unassigned.goals_this_month, False),
    ]
    # Already out of net worth, so it adds back: spending from a goal moves nothing.
    if unassigned.goals_spent:
        steps.append(("goals_spent", _("Spent from goals"), unassigned.goals_spent, False))
    steps += [
        ("unassigned", unassigned.label, unassigned.amount, True),
    ]
    bars, running = [], ZERO
    for key, label, value, is_total in steps:
        if is_total:
            start, end = ZERO, value
            running = value
        else:
            start, end = running, running + value
            running = end
        bars.append(
            {
                "key": key,
                "label": str(label),
                "value": float(value),
                "start": float(start),
                "end": float(end),
                "total": is_total,
            }
        )
    return bars
