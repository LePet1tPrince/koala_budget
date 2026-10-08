"""
Goal plans: what a goal plans to receive each month (docs/goal-plans-plan.md).

For goal G and month m (first of month):

    planned(m)  the `GoalPlan` row for m, or else the default -- G's
                `monthly_contribution` while the default is active and m ≥ G.plan_from
    linked(m)   one of G's `GoalAccountLink`s covers some day of m (derived from
                link history, never stored); otherwise m is a *direct* month
    put_in(m)   manual allocations + flows from linked accounts in m (starting
                balances are a one-off and never count towards a plan)

A direct month has nothing to wait for, so its plan *is* the money given to the
goal: `allocated` counts it, capped so plans never take a goal past its target
(the cap is cumulative: what plans have put in through any date is at most what
the target still needed after everything else dated before it). A linked month's
plan never changes `allocated` -- the money counts when it lands in the account --
but until it does, the shortfall is *held* back from Unassigned:

    release   held(M) = max(0, planned(M) − put_in(M))
    carry     held(M) = max(0, Σ planned(m) − put_in(m) over linked months from the
              first planned one through M)

capped at what the target still needs, and nothing once the goal is closed.

History. A month with no row plans the goal's *current* default, so changing the
default would silently rewrite every such month. Every write that changes what the
default depends on (the contribution, the target, Funded, closing, archiving, the
goal's links) calls `freeze` first: it writes a row for each month from `plan_from`
up to the current one that the default covered, recording what that month counted,
then moves `plan_from` up. Months from `plan_from` on therefore all share the
goal's current settings. `freeze` never changes any figure; it only makes the
past independent of the change that follows.

The direct plans reach `allocated` through `direct_planned_subquery` (SQL, so every
`with_progress` caller is unchanged); the per-month figures and `held` are computed
here in Python (`plan_months`, `apply_plans`, `held_by_goal`). `PlanTwinTest` keeps
the two in step.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import (
    Case,
    Count,
    DateField,
    DecimalField,
    Exists,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear, Greatest, Least, TruncMonth
from django.utils import timezone
from django.utils.translation import gettext as _

ZERO = Decimal("0")
MONEY = DecimalField(max_digits=15, decimal_places=2)


class PlanError(ValueError):
    """A plan write refused with a message for the user."""


# --- Months ----------------------------------------------------------------------


def first_of_month(day: date) -> date:
    return day.replace(day=1)


def next_month(month: date) -> date:
    month = month.replace(day=1)
    return month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)


def months_between(start: date, end: date):
    """First-of-month dates from `start`'s month (inclusive) to `end` (exclusive)."""
    month = first_of_month(start)
    while month < end:
        yield month
        month = next_month(month)


def current_month(today=None) -> date:
    return first_of_month(today or timezone.localdate())


# --- The default -------------------------------------------------------------------


def default_active(goal) -> bool:
    """Whether months without a row (from `plan_from` on) plan the contribution."""
    return bool(
        goal.plan_from is not None
        and goal.monthly_contribution
        and goal.monthly_contribution > 0
        and goal.closed_at is None
        and not goal.is_archived
        and not goal.is_complete
    )


def default_amount(goal) -> Decimal:
    return goal.monthly_contribution if default_active(goal) else ZERO


def _default_active_q():
    return Q(
        plan_from__isnull=False,
        monthly_contribution__gt=0,
        closed_at__isnull=True,
        is_archived=False,
        is_complete=False,
    )


def covers_month(links, month: date) -> bool:
    """Whether any of `links` ((start_date, end_date) pairs) covers some day of `month`."""
    end = next_month(month)
    return any(start < end and (stop is None or stop >= month) for start, stop in links)


# --- Writers ----------------------------------------------------------------------


@transaction.atomic
def freeze(goal, today=None, through_current=False):
    """
    Record what the default planned for every month from `plan_from` up to the
    current month (included with `through_current`), then move `plan_from` past
    them. Call it inside the writer's transaction, *before* changing anything the
    default depends on: it reads the goal's stored settings, not `goal`'s
    attributes, which a bound form may already have changed.

    Contribution, target and link changes freeze up to (not including) the
    current month, so the current month follows the new settings. Funded, closing
    and archiving freeze through it, so what this month already counted stays.

    The rows record what the months *counted*: where the target cap stopped
    direct plans, the latest default rows are trimmed to what was counted, so
    raising the target later doesn't release months the cap had stopped.
    """
    from .models import Goal, GoalPlan

    stored = Goal.objects.select_for_update().get(pk=goal.pk)
    this_month = current_month(today)
    until = next_month(this_month) if through_current else this_month
    if stored.plan_from is not None and stored.plan_from < until and default_active(stored):
        months = list(months_between(stored.plan_from, until))
        existing = set(GoalPlan.objects.filter(goal=stored, month__in=months).values_list("month", flat=True))
        missing = [m for m in months if m not in existing]
        if missing:
            counted = None
            if stored.target_amount and stored.target_amount > 0:
                from .services import goal_monthly

                cells = goal_monthly(stored.book, [stored], end=until).get(stored.pk, {})
                counted = sum((c["plan_in"] for m, c in cells.items() if m < until), ZERO)
            GoalPlan.objects.bulk_create(
                [
                    GoalPlan(
                        book_id=stored.book_id,
                        goal=stored,
                        month=month,
                        amount=stored.monthly_contribution,
                        source=GoalPlan.SOURCE_DEFAULT,
                    )
                    for month in missing
                ]
            )
            if counted is not None:
                _trim_to_counted(stored, until, counted)
    if stored.plan_from is None or stored.plan_from < until:
        Goal.objects.filter(pk=stored.pk).update(plan_from=until)
        stored.plan_from = until
    goal.plan_from = stored.plan_from
    return stored


def _trim_to_counted(goal, until, counted):
    """Lower the latest direct default rows before `until` until the direct rows sum to `counted`."""
    from .models import GoalAccountLink, GoalPlan

    links = list(GoalAccountLink.objects.filter(goal=goal).values_list("start_date", "end_date"))
    direct = [
        plan
        for plan in GoalPlan.objects.filter(goal=goal, month__lt=until).order_by("-month")
        if not covers_month(links, plan.month)
    ]
    excess = sum((plan.amount for plan in direct), ZERO) - counted
    for plan in direct:
        if excess <= 0:
            break
        if plan.source != GoalPlan.SOURCE_DEFAULT:
            continue
        cut = min(plan.amount, excess)
        excess -= cut
        if cut == plan.amount:
            plan.delete()
        else:
            plan.amount -= cut
            plan.save(update_fields=["amount", "updated_at"])


@transaction.atomic
def set_plan(goal, month: date, amount: Decimal):
    """The user's plan for one month: a typed row, kept until reset."""
    from .models import Goal, GoalPlan

    if amount < 0:
        raise PlanError(_("A plan can't be negative. To take money out, withdraw it on the Goals page."))
    goal = Goal.objects.select_for_update().get(pk=goal.pk)
    if goal.is_archived or goal.is_closed:
        raise PlanError(_("This goal is closed. Its plan can't be changed."))
    month = first_of_month(month)
    plan, _created = GoalPlan.objects.update_or_create(
        book_id=goal.book_id,
        goal=goal,
        month=month,
        defaults={"amount": amount, "source": GoalPlan.SOURCE_TYPED},
    )
    return plan


def can_reset(goal, month: date) -> bool:
    """A typed month goes back to the default only where the default still applies."""
    return goal.plan_from is not None and first_of_month(month) >= goal.plan_from


@transaction.atomic
def reset_plan(goal, month: date):
    """Drop the month's typed plan, so it plans the monthly contribution again."""
    from .models import Goal, GoalPlan

    goal = Goal.objects.select_for_update().get(pk=goal.pk)
    month = first_of_month(month)
    if not can_reset(goal, month):
        raise PlanError(_("This month's plan was set before the monthly contribution last changed. Type a new amount."))
    GoalPlan.objects.filter(goal=goal, month=month, source=GoalPlan.SOURCE_TYPED).delete()


def adopt_goals(goals, month: date, Goal, GoalPlan, GoalAllocation, GoalAccountLink):
    """
    Bring goals that predate plans into them from `month` on, changing no earlier
    month (the budget migration and importing an older export both use it; the
    model classes are passed so a migration can hand in its historical ones).

    `plan_from` becomes `month`. A direct goal with a contribution that already has
    a positive manual allocation in `month` gets a typed plan of 0 for it: the
    contribution was assigned by hand already, and the new default must not add it
    a second time.
    """
    month = first_of_month(month)
    for goal in goals:
        Goal.objects.filter(pk=goal.pk).update(plan_from=month)
        if goal.closed_at is not None or goal.is_archived or goal.is_complete:
            continue
        if not goal.monthly_contribution or goal.monthly_contribution <= 0:
            continue
        links = list(GoalAccountLink.objects.filter(goal_id=goal.pk).values_list("start_date", "end_date"))
        if covers_month(links, month):
            continue
        assigned = GoalAllocation.objects.filter(goal_id=goal.pk, month=month).aggregate(total=Sum("amount"))["total"]
        if assigned and assigned > 0:
            GoalPlan.objects.update_or_create(
                book_id=goal.book_id,
                goal_id=goal.pk,
                month=month,
                defaults={"amount": ZERO, "source": "typed"},
            )


# --- Reads (Python) ------------------------------------------------------------------


@dataclass
class MonthPlan:
    planned: Decimal
    linked: bool
    source: str | None  # "default" / "typed" for a row; None for the default itself


def plan_months(goals, end: date, links=None):
    """
    {goal id: {month: MonthPlan}} for every month before `end` that plans something
    or has a row. `links` ({goal id: [(start, end)]}) may be passed by a caller that
    already has them.
    """
    from .models import GoalAccountLink, GoalPlan

    goals = list(goals)
    ids = [g.pk for g in goals]
    if links is None:
        links = {pk: [] for pk in ids}
        for goal_id, start, stop in GoalAccountLink.objects.filter(goal_id__in=ids).values_list(
            "goal_id", "start_date", "end_date"
        ):
            links[goal_id].append((start, stop))
    rows = {pk: {} for pk in ids}
    for goal_id, month, amount, source in GoalPlan.objects.filter(goal_id__in=ids, month__lt=end).values_list(
        "goal_id", "month", "amount", "source"
    ):
        rows[goal_id][month] = (amount, source)

    result = {}
    for goal in goals:
        goal_links = links.get(goal.pk, [])
        months = {}
        for month, (amount, source) in rows[goal.pk].items():
            months[month] = MonthPlan(amount, covers_month(goal_links, month), source)
        if default_active(goal):
            for month in months_between(goal.plan_from, end):
                if month not in months:
                    months[month] = MonthPlan(goal.monthly_contribution, covers_month(goal_links, month), None)
        result[goal.pk] = dict(sorted(months.items()))
    return result


def planned_for(goals, month: date):
    """{goal id: MonthPlan or None} for one month."""
    month = first_of_month(month)
    by_goal = plan_months(goals, next_month(month))
    return {pk: months.get(month) for pk, months in by_goal.items()}


def apply_plans(goal, cells, plans, plan_end: date, cell_factory):
    """
    Fold `plans` (one goal's `plan_months`) into its per-month `cells` (from
    `goal_monthly`, covering all of history): every month gets `planned`,
    `plan_linked`, `plan_source` and `plan_in` (what direct plans counted, after
    the target cap), and `saved` includes `plan_in`.

    The cap is cumulative, as in `direct_planned_subquery`: through any date, the
    direct plans count at most what the target still needed after everything
    else given before that date. Months from `plan_end` on count no plan.
    """
    target = goal.target_amount or ZERO
    for month in plans:
        cell_factory(month)
    other = planned = counted = ZERO
    for month in sorted(cells):
        cell = cells[month]
        plan = plans.get(month)
        cell["planned"] = plan.planned if plan else ZERO
        cell["plan_linked"] = plan.linked if plan else False
        cell["plan_source"] = plan.source if plan else None
        cell["plan_in"] = ZERO
        other += cell["assigned"] + cell["linked"]
        if month >= plan_end:
            continue
        if plan and not plan.linked:
            planned += plan.planned
        now = planned if target <= 0 else min(planned, max(target - other, ZERO))
        cell["plan_in"] = now - counted
        counted = now
    for cell in cells.values():
        cell["saved"] = cell["assigned"] + cell["linked"] + cell["plan_in"]


def held_by_goal(goals, cells_by_goal, month: date):
    """
    {goal id: held} as of the end of `month`: planned money a linked goal is still
    waiting for. `cells_by_goal` is `goal_monthly` output covering every month up
    to `month` (from the start of history, for `carry`).
    """
    month = first_of_month(month)
    result = {}
    for goal in goals:
        result[goal.pk] = _held(goal, cells_by_goal.get(goal.pk, {}), month)
    return result


def _held(goal, cells, month):
    from .models import Goal

    if goal.is_archived:
        return ZERO
    if goal.closed_at is not None and first_of_month(timezone.localtime(goal.closed_at).date()) <= month:
        return ZERO
    cell = cells.get(month)
    if cell is None or not cell.get("plan_linked"):
        return ZERO

    def shortfall(c):
        return c["planned"] - (c["assigned"] + c["flows"])

    if goal.unmet_plan == Goal.UNMET_CARRY:
        total = ZERO
        started = False
        for m in sorted(cells):
            if m > month:
                break
            c = cells[m]
            if not c.get("plan_linked"):
                continue
            if not started and c["planned"] <= 0:
                continue
            started = True
            total += shortfall(c)
        held = max(total, ZERO)
    else:
        held = max(shortfall(cell), ZERO)

    target = goal.target_amount or ZERO
    if target > 0 and held > 0:
        allocated = sum((c["saved"] for m, c in cells.items() if m <= month), ZERO)
        held = min(held, max(target - allocated, ZERO))
    return held


# --- Reads (SQL) ----------------------------------------------------------------------


def _money(value):
    return Value(value, output_field=MONEY)


def _links_covering(month_ref, goal_ref):
    """`GoalAccountLink`s of `goal_ref` covering some day of the month `month_ref`."""
    from .models import GoalAccountLink

    return (
        GoalAccountLink.objects.annotate(_start_month=TruncMonth("start_date", output_field=DateField()))
        .filter(goal=goal_ref, _start_month__lte=month_ref)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=month_ref))
    )


def _direct_rows(end):
    """A goal's rows (`OuterRef("pk")`) before `end` in months no link covers."""
    from .models import GoalPlan

    return (
        GoalPlan.objects.filter(goal=OuterRef("pk"), month__lt=end)
        .alias(_linked=Exists(_links_covering(OuterRef("month"), OuterRef("goal"))))
        .filter(_linked=False)
    )


def _month_index(expr):
    return ExtractYear(expr) * 12 + ExtractMonth(expr)


def direct_planned_subquery(end: date, other=None):
    """
    What direct plans counted before `end`, as a scalar expression on `Goal`:
    Σ direct planned(m) for months before `end`, capped for a goal with a target
    at what the target still needed after `other` -- everything else given before
    `end` (manual + linked; by default the same subqueries
    `goal_allocated_subquery` uses).

    The default's months are [plan_from, end). Because every change to the goal's
    links freezes first, those months share one link state except possibly the
    first (a link that ended, or started, in the month of the change): the first
    month is linked if a link covers it, the rest if the goal has an open link.
    """
    from .linked import linked_allocated_subquery
    from .models import GoalAccountLink, goal_assigned_subquery

    end = first_of_month(end)
    if other is None:
        other = goal_assigned_subquery(end=end) + linked_allocated_subquery(end=end)

    rows = _direct_rows(end).values("goal").annotate(t=Sum("amount")).values("t")
    rows_total = Coalesce(Subquery(rows, output_field=MONEY), _money(ZERO))

    in_range = _direct_rows(end).filter(month__gte=OuterRef("plan_from")).values("goal").annotate(n=Count("pk"))
    rows_in_range = Coalesce(Subquery(in_range.values("n"), output_field=IntegerField()), Value(0))

    span = Greatest(Value(end.year * 12 + end.month) - _month_index("plan_from"), Value(0))
    first_linked = Exists(_links_covering(OuterRef("plan_from"), OuterRef("pk")))
    rest_linked = Exists(GoalAccountLink.objects.filter(goal=OuterRef("pk"), end_date__isnull=True))
    direct_months = (
        Case(When(first_linked, then=Value(0)), default=Least(span, Value(1)), output_field=IntegerField())
        + Case(
            When(rest_linked, then=Value(0)), default=Greatest(span - Value(1), Value(0)), output_field=IntegerField()
        )
        - rows_in_range
    )
    dynamic = Case(
        When(
            _default_active_q(),
            then=ExpressionWrapper(F("monthly_contribution") * Greatest(direct_months, Value(0)), output_field=MONEY),
        ),
        default=_money(ZERO),
        output_field=MONEY,
    )
    planned = ExpressionWrapper(rows_total + dynamic, output_field=MONEY)
    room = Greatest(ExpressionWrapper(F("target_amount") - other, output_field=MONEY), _money(ZERO), output_field=MONEY)
    # Only a goal that plans something needs the cap, and the cap is the costly part
    # (`other` reads every linked line): a CASE branch is evaluated only when taken.
    plans_something = Q(_default_active_q()) | Exists(_direct_rows(end))
    return Case(
        When(Q(target_amount__gt=0) & plans_something, then=Least(planned, room, output_field=MONEY)),
        default=planned,
        output_field=MONEY,
    )
