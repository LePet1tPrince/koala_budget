"""
The Unassigned metric: money that has no job yet (see docs/unassigned-plan.md).

    unassigned = net worth
               + Σ max(0, −available) over income categories   (budgeted income not yet received)
               − Σ max(0,  available) over expense categories  (unspent budget: the envelopes)
               − Σ max(0,  left)      over goals               (allocated − spent from it)

Every "available" is the budget page's own running balance through `month`
(`BudgetService.get_available_with_previous`: expense budget − actual + rollover,
income actual − budget + rollover), and a goal's left counts allocations and
spending through `month` too, so nothing dated after the month moves it.

The rule behind every term: a claim is the larger of what was planned and what
actually happened.

- **Income.** Budgeted income that hasn't arrived counts as coming, and the
  difference rolls from month to month like an envelope's: a September paycheque
  that lands in October fills September's gap rather than arriving twice. Income
  beyond its budget isn't "due" — it is already in net worth, so it arrives
  unassigned. If the money isn't coming, lower the budget: the shortfall goes with it.
- **Overspending comes out of Unassigned.** An overspent envelope or goal claims
  nothing (its balance is floored at zero), so the money spent past it leaves net
  worth with nothing to offset it. Money spent without a budget was not free money;
  it's gone, and Unassigned says so as soon as the transaction is categorized. The
  negative balance itself is carried, never reset, so budgeting into the hole next
  month doesn't move Unassigned again: the first dollars of a budget fill the hole,
  and only what goes past it is a new claim.
- **Spending within a budget or a goal moves nothing**: net worth and the claim
  fall by the same amount.
- **Future months don't count.** Budgets, income and goal allocations dated after
  `month` claim nothing yet.
- **Everything else in net worth counts as it lands**: opening balances,
  reconciliation adjustments, any equity entry.

`compute_unassigned()` is the one place this is calculated. The sidebar pill, the
dashboard, the budget/goals card (via `NetWorthService.get_net_worth_card_data`), the
goal quick-assign clamp and the Dollar Map report all read it, so no two screens can
disagree about the number.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

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
    income_due: Decimal  # budgeted income not yet received, rolled over
    envelopes: Decimal  # Σ unspent expense budget (overspent envelopes count as 0)
    goals: Decimal  # Σ left in goals (overspent goals count as 0)
    # Not terms of the sum: overspending already left net worth, and these say how much
    # of it is still showing as a negative balance.
    overspent: Decimal = ZERO  # expense envelopes
    goals_overspent: Decimal = ZERO
    # Per-account detail, filled only when asked for (the Dollar Map report).
    detail: dict = field(default_factory=dict, compare=False, repr=False)

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


def budget_categories(book):
    """Income and expense accounts, with the group loaded for the type checks."""
    return list(
        Account.objects.filter(
            book=book, account_group__account_type__in=(ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME)
        ).select_related("account_group")
    )


def _positive(values) -> Decimal:
    return sum((v for v in values if v > 0), ZERO)


def compute_unassigned(
    book,
    month: date,
    categories=None,
    detail=False,
    future_income: bool | None = None,
) -> Unassigned:
    """
    Unassigned as of the end of `month`.

    `categories` may be passed by a caller that already loaded them (the budget
    page); anything that isn't an income or expense account is ignored. With
    `detail=True` the result also carries the per-goal, per-envelope and per-income
    figures the Dollar Map report breaks the total down into.

    `future_income` defaults to the book's own setting. With it off, income counts
    only once it has landed, so `income_due` is zero; the budgeting settings page
    passes the opposite of the setting to show what flipping it would do.
    """
    from apps.budget.models import Goal, goal_allocated_subquery, goal_spent_subquery, month_after
    from apps.budget.services import BudgetService, NetWorthService

    month = month.replace(day=1)
    if categories is None:
        categories = budget_categories(book)
    if future_income is None:
        future_income = book.budget_future_income
    expense = [c for c in categories if c.account_group.account_type == ACCOUNT_TYPE_EXPENSE]
    income = [c for c in categories if c.account_group.account_type == ACCOUNT_TYPE_INCOME] if future_income else []

    # One pass over the budget history gives both: expense available is
    # budget − actual + rollover, income available is actual − budget + rollover.
    available, previous = BudgetService(book).get_available_with_previous(month, expense + income)
    expense_available = {c.pk: available[c.pk] for c in expense}
    income_due_by_account = {c.pk: -available[c.pk] for c in income if available[c.pk] < 0}

    goals = list(
        Goal.objects.filter(book=book, is_archived=False)
        .annotate(
            allocated_to_date=goal_allocated_subquery(end=month_after(month)),
            spent_to_date=goal_spent_subquery(end=month_after(month)),
        )
        .order_by("order", "target_date", "name")
    )
    goal_left = {g.pk: g.allocated_to_date - g.spent_to_date for g in goals}

    result = Unassigned(
        month=month,
        net_worth=NetWorthService(book).get_net_worth(month),
        income_due=sum(income_due_by_account.values(), ZERO),
        envelopes=_positive(expense_available.values()),
        goals=_positive(goal_left.values()),
        overspent=-sum((v for v in expense_available.values() if v < 0), ZERO),
        goals_overspent=-sum((v for v in goal_left.values() if v < 0), ZERO),
    )
    if not detail:
        return result

    by_id = {c.pk: c for c in categories}
    result.detail.update(
        {
            # `amount` is the goal's left; allocated and spent explain it. A negative
            # left claims nothing (see the module docstring).
            "goals": [
                {
                    "name": g.name,
                    "amount": goal_left[g.pk],
                    "allocated": g.allocated_to_date,
                    "spent": g.spent_to_date,
                    "goal": g,
                }
                for g in goals
                if g.allocated_to_date or g.spent_to_date
            ],
            "envelopes": [
                {
                    "name": by_id[pk].name,
                    "group": by_id[pk].account_group.name,
                    "amount": amount,
                    "rollover": previous.get(pk, ZERO),
                }
                for pk, amount in expense_available.items()
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
    Goals + envelopes + Unassigned is exactly what you have (net worth + income
    due), so the claims only reach past it when Unassigned is negative: that
    over-assignment is drawn hatched rather than silently rescaled away.
    Overspending isn't a claim, so it never appears here: it has already left net worth.
    """
    amount = unassigned.amount
    free = max(amount, ZERO)
    have = unassigned.net_worth + unassigned.income_due
    filled = unassigned.goals + unassigned.envelopes + free
    scale = max(filled, have)

    segments = [
        {"key": "goals", "label": _("Goals"), "amount": unassigned.goals},
        {"key": "envelopes", "label": _("Budget envelopes"), "amount": unassigned.envelopes},
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
        ("envelopes", _("Budget envelopes, unspent"), -unassigned.envelopes, False),
        ("goals", _("Left in goals"), -unassigned.goals, False),
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
