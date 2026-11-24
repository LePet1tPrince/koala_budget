"""
The Unassigned metric: money that has no job yet (see docs/unassigned-plan.md).

    unassigned = net worth
               − Σ max(0,  available) over expense categories  (unspent budget: the envelopes)
               − Σ max(0,  left)      over goals               (allocated − spent from it)

    expected income = Σ max(0, −available) over income categories  (budgeted, not yet received)

Expected income is a separate figure shown beside Unassigned, never a term of it:
money is unassigned only once it is in net worth.

Every "available" is the budget page's own running balance through `month`
(`BudgetService.get_available_with_previous`: expense budget − actual + rollover,
income actual − budget + rollover), and a goal's left counts allocations and
spending through `month` too, so nothing dated after the month moves it.

The rule behind every term: a claim is the larger of what was planned and what
actually happened.

- **Income** counts toward Unassigned only as it lands in net worth. Budgeted
  income that hasn't arrived is Expected income, and the difference rolls from month
  to month like an envelope's: a September paycheque that lands in October fills
  September's gap rather than being expected twice. If the money isn't coming, lower
  the budget: the expectation goes with it. Budgeting envelopes against expected
  income makes Unassigned negative until the income lands; Expected income says how
  much of that is covered.
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

`compute_unassigned()` is the one place both are calculated. The sidebar pill, the
budget page and goals page (via `NetWorthService.get_net_worth_card_data`), the
goal quick-assign clamp and the Dollar Map report all read it, so no two screens can
disagree about the number.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from apps.accounts.models import ACCOUNT_TYPE_EXPENSE, ACCOUNT_TYPE_INCOME, Account
from apps.utils.months import add_months

ZERO = Decimal("0")

# The metric's name is still being decided; every template and script reads these.
UNASSIGNED_LABEL = _("Unassigned")
OVER_ASSIGNED_LABEL = _("Over-assigned")
# Budgeted income not yet received: shown beside Unassigned, not part of it.
EXPECTED_INCOME_LABEL = _("Expected income")

STATE_POSITIVE = "positive"
STATE_ZERO = "zero"
STATE_NEGATIVE = "negative"


@dataclass(frozen=True)
class Unassigned:
    """Every term of the Unassigned sum for one month, the result, and Expected income."""

    month: date
    net_worth: Decimal
    # Expected income: budgeted income not yet received, rolled over. Not a term of
    # the sum; shown beside it.
    income_due: Decimal
    envelopes: Decimal  # Σ unspent expense budget (overspent envelopes count as 0)
    goals: Decimal  # Σ left in goals (overspent goals count as 0)
    # Whether the book budgets income before it arrives: only then is Expected income shown.
    expects_income: bool = False
    # Not terms of the sum: overspending already left net worth, and these say how much
    # of it is still showing as a negative balance.
    overspent: Decimal = ZERO  # expense envelopes
    goals_overspent: Decimal = ZERO
    # Per-account detail, filled only when asked for (the Dollar Map report).
    detail: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def amount(self) -> Decimal:
        return self.net_worth - self.envelopes - self.goals

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

    `future_income` defaults to the book's own setting. With it off, income
    categories aren't budgeted, so `income_due` (Expected income) is zero; the
    budgeting settings page passes the opposite of the setting to show what flipping
    it would do. Unassigned itself is the same either way.
    """
    from apps.budget.models import Goal, goal_allocated_subquery, goal_spent_subquery
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
            allocated_to_date=goal_allocated_subquery(end=add_months(month, 1)),
            spent_to_date=goal_spent_subquery(end=add_months(month, 1)),
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
        expects_income=future_income,
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


def current_unassigned(book) -> Unassigned:
    """
    Unassigned for this month: the figure the sidebar pill shows. Always the current
    month, whatever month a page is on -- the pill answers "how much has no job right
    now". Read by the pill's context processor and the nav-state API.
    """
    return compute_unassigned(book, date.today())


def pill_context(unassigned: Unassigned) -> dict:
    """What the pill and the JSON endpoint need: the figure, its state, its words, and
    Expected income (`expected` is None when the book doesn't budget income ahead)."""
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
        "expected": {
            "label": str(EXPECTED_INCOME_LABEL),
            "raw": f"{unassigned.income_due:.2f}",
            "display": currency(unassigned.income_due),
        }
        if unassigned.expects_income
        else None,
    }
