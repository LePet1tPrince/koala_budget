"""
Linked accounts: what an account linked to a goal does to that goal
(docs/goal-linked-accounts-plan.md §3, §5).

Nothing here is stored. Every figure is derived from counted journal lines, so
editing, re-dating, re-categorizing, splitting, voiding, archiving, deleting or
bulk-importing a transaction moves the goal with no hook to keep in step.

For a counted line `l` on an account linked to goal `G` (dated inside the link's
range), the *other side* of `l`'s entry decides. Each other line falls in one class:

    free    asset/liability linked to no goal on that date (checking, a card, a loan)
    other   asset/liability linked to another goal on that date
    income  an income account
    adjust  equity that isn't a goal (opening balances, reconciliation adjustments)
    (none)  an expense, a goal's own account, or an account linked to G itself

and each class's *share* is its amount on the side opposite `l` over the entry's
total. Money arriving (`l.dr`) counts for every class; money leaving (`l.cr`) always
comes out of the goal for `other`/`income`/`adjust`, and for `free` does what the
goal's `outflow` says:

    alloc_delta = (dr × (free + other + income + adjust)
                   − cr × (other + income + adjust)
                   − cr × free  [outflow = withdraw]) / total
    spent_delta =  cr × free  [outflow = spend]   / total

A two-line entry is all one class, so the share is 0 or 1 and the result exact; a
split's bank line takes just the legs that count, and a leg takes its own amount.
Only an entry with several lines on both sides divides pro rata, hence the rounding.

Expense lines never count: an expense has already lowered its envelope's claim, and
lowering the goal's too would make Unassigned rise by money that no longer exists.
A goal account's lines are goal spending, which `spent` already counts.

Starting balances: a link with `include_starting_balance` gives the goal the
account's balance on the day before `start_date`, in `start_date`'s month.
"""

from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, NullIf, Round, TruncMonth

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_EQUITY, ACCOUNT_TYPE_INCOME, ACCOUNT_TYPE_LIABILITY

ZERO = Decimal("0")
MONEY = DecimalField(max_digits=15, decimal_places=2)
# Room for the intermediate products before rounding back to cents.
WIDE = DecimalField(max_digits=30, decimal_places=10)


def _money(value):
    return Value(value, output_field=MONEY)


def _links_covering(entry_date_ref):
    """`GoalAccountLink`s on `OuterRef("account")` whose range includes `entry_date_ref`."""
    from apps.budget.models import GoalAccountLink

    return GoalAccountLink.objects.filter(account=OuterRef("account"), start_date__lte=entry_date_ref).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=entry_date_ref)
    )


def _other_side_sum(column, classes):
    """
    Σ `column` over the lines of `OuterRef`'s entry that fall in `classes`, a
    scalar subquery evaluated per linked line (see the module docstring).
    """
    from apps.journal.models import JournalLine

    entry_date = OuterRef("journal_entry__entry_date")
    lines = JournalLine.objects.filter(journal_entry=OuterRef("journal_entry")).alias(
        linked_any=Exists(_links_covering(entry_date)),
        linked_same=Exists(_links_covering(entry_date).filter(goal=OuterRef(OuterRef("link_goal")))),
    )
    balance_sheet = Q(account__account_group__account_type__in=(ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY))
    conditions = {
        "free": balance_sheet & Q(linked_any=False),
        "other": balance_sheet & Q(linked_any=True, linked_same=False),
        "income": Q(account__account_group__account_type=ACCOUNT_TYPE_INCOME),
        "adjust": Q(account__account_group__account_type=ACCOUNT_TYPE_EQUITY, account__goal__isnull=True),
    }
    condition = Q()
    for name in classes:
        condition |= conditions[name]
    total = lines.filter(condition).values("journal_entry").annotate(total=Sum(column)).values("total")
    return Coalesce(Subquery(total, output_field=MONEY), _money(ZERO))


def _entry_total():
    from apps.journal.models import JournalLine

    total = (
        JournalLine.objects.filter(journal_entry=OuterRef("journal_entry"))
        .values("journal_entry")
        .annotate(total=Sum("dr_amount"))
        .values("total")
    )
    return Subquery(total, output_field=MONEY)


def linked_lines(start=None, end=None):
    """
    Counted journal lines on linked accounts, each inside its link's range, with:

    - `link_goal`, `link_account`, `link_outflow`: the link's goal, the account, and
      the goal's outflow setting
    - `month`: first of the entry's month
    - `alloc_delta`, `spent_delta`: what the line does to the goal

    Dated from `start` (inclusive) to `end` (exclusive). An account's links never
    overlap, so a line appears at most once.
    """
    from apps.budget.models import Goal
    from apps.journal.models import JournalLine, counted_entries

    entry_date = F("journal_entry__entry_date")
    # One filter() call, so the range conditions apply to the same link row.
    lines = JournalLine.objects.filter(
        counted_entries("journal_entry__"),
        Q(account__goal_links__start_date__lte=entry_date)
        & (Q(account__goal_links__end_date__isnull=True) | Q(account__goal_links__end_date__gte=entry_date)),
    )
    if start is not None:
        lines = lines.filter(journal_entry__entry_date__gte=start)
    if end is not None:
        lines = lines.filter(journal_entry__entry_date__lt=end)

    total = NullIf(_entry_total(), _money(ZERO))
    lines = lines.annotate(
        link_goal=F("account__goal_links__goal"),
        link_account=F("account"),
        link_outflow=F("account__goal_links__goal__outflow"),
        month=TruncMonth("journal_entry__entry_date"),
        _in=_other_side_sum("cr_amount", ("free", "other", "income", "adjust")),
        _out_kept=_other_side_sum("dr_amount", ("other", "income", "adjust")),
        _out_free=_other_side_sum("dr_amount", ("free",)),
    )
    out_free = F("cr_amount") * F("_out_free")
    alloc = (
        F("dr_amount") * F("_in")
        - F("cr_amount") * F("_out_kept")
        - Case(When(link_outflow=Goal.OUTFLOW_WITHDRAW, then=out_free), default=_money(ZERO), output_field=WIDE)
    )
    spent = Case(When(link_outflow=Goal.OUTFLOW_SPEND, then=out_free), default=_money(ZERO), output_field=WIDE)
    return lines.annotate(
        alloc_delta=Coalesce(Round(alloc / total, 2, output_field=MONEY), _money(ZERO)),
        spent_delta=Coalesce(Round(spent / total, 2, output_field=MONEY), _money(ZERO)),
    )


def starting_balances(start=None, end=None):
    """
    Links that count the balance already in their account, annotated with `amount`
    (the account's counted balance before `start_date`) and `month` (the start
    date's month). Only links starting from `start` (inclusive) to `end` (exclusive).
    """
    from apps.budget.models import GoalAccountLink
    from apps.journal.models import JournalLine, counted_entries

    balance = (
        JournalLine.objects.filter(
            counted_entries("journal_entry__"),
            account=OuterRef("account"),
            journal_entry__entry_date__lt=OuterRef("start_date"),
        )
        .values("account")
        .annotate(total=Sum(F("dr_amount") - F("cr_amount")))
        .values("total")
    )
    links = GoalAccountLink.objects.filter(include_starting_balance=True)
    if start is not None:
        links = links.filter(start_date__gte=start)
    if end is not None:
        links = links.filter(start_date__lt=end)
    return links.annotate(
        amount=Coalesce(Subquery(balance, output_field=MONEY), _money(ZERO)),
        month=TruncMonth("start_date"),
    )


def _per_goal(queryset, goal_field, value_field):
    total = queryset.filter(**{goal_field: OuterRef("pk")}).values(goal_field).annotate(t=Sum(value_field)).values("t")
    return Coalesce(Subquery(total, output_field=MONEY), _money(ZERO))


def linked_allocated_subquery(start=None, end=None):
    """What linked accounts added to a goal (scalar subquery on `Goal`), from `start` to `end`."""
    return _per_goal(linked_lines(start, end), "link_goal", "alloc_delta") + _per_goal(
        starting_balances(start, end), "goal", "amount"
    )


def linked_spent_subquery(start=None, end=None):
    """What linked accounts spent from a goal (scalar subquery on `Goal`), from `start` to `end`."""
    return _per_goal(linked_lines(start, end), "link_goal", "spent_delta")


def monthly_linked(goal_ids, start=None, end=None):
    """
    {goal id: {month: {"linked", "starting", "spent"}}} from linked accounts.
    `linked` is everything they brought in, `starting` the part of it that was a
    starting balance (a one-off, which never counts towards a monthly plan).
    """
    result = {}

    def cell(goal_id, month):
        month = month.date() if hasattr(month, "date") else month
        return result.setdefault(goal_id, {}).setdefault(month, {"linked": ZERO, "starting": ZERO, "spent": ZERO})

    rows = (
        linked_lines(start, end)
        .filter(link_goal__in=goal_ids)
        .values("link_goal", "month")
        .annotate(linked=Sum("alloc_delta"), spent=Sum("spent_delta"))
    )
    for row in rows:
        target = cell(row["link_goal"], row["month"])
        target["linked"] += row["linked"]
        target["spent"] += row["spent"]
    for link in starting_balances(start, end).filter(goal_id__in=goal_ids):
        target = cell(link.goal_id, link.month)
        target["linked"] += link.amount
        target["starting"] += link.amount
    return result
