"""
Linking accounts to a goal (docs/goal-linked-accounts-plan.md §8).

`set_links` is the one writer: the goal form sends the accounts it wants and this
works out what to link, update, end or drop. Every refusal is a `LinkError` raised
before anything is written. `preview` runs the same writer inside a savepoint and
rolls it back, so what the form previews is exactly what saving would do.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import ACCOUNT_TYPE_ASSET, Account

from .models import Goal, GoalAccountLink

ZERO = Decimal("0")


class LinkError(ValueError):
    """A link the user asked for that can't be made. The message is shown as is."""


@dataclass(frozen=True)
class LinkRow:
    """One account the goal should be linked to."""

    account: Account
    start_date: date
    include_starting_balance: bool = True


@dataclass
class LinkChanges:
    linked: list
    updated: list
    unlinked: list

    @property
    def any(self):
        return bool(self.linked or self.updated or self.unlinked)


def eligible_accounts(book, goal=None):
    """
    Accounts that can be offered for linking: this book's non-system, open asset
    accounts, plus any archived account `goal` is still linked to (so it can be
    unlinked). Each carries `feeds_goal_id`/`feeds_goal_name`: the goal it is
    linked to now, if any.
    """
    open_links = GoalAccountLink.objects.open().filter(account=OuterRef("pk"))
    accounts = Account.objects.filter(
        book=book, is_system=False, account_group__account_type=ACCOUNT_TYPE_ASSET
    ).select_related("account_group", "institution")
    keep = Q(is_archived=False)
    if goal is not None and goal.pk:
        keep |= Exists(GoalAccountLink.objects.open().filter(account=OuterRef("pk"), goal=goal))
    accounts = accounts.filter(keep)
    return accounts.annotate(
        is_linked=Exists(open_links),
        feeds_goal_id=Subquery(open_links.values("goal_id")[:1]),
        feeds_goal_name=Subquery(open_links.values("goal__name")[:1]),
    ).order_by("account_group__sort_order", "account_group__name", "sort_order", "name")


def _check_row(goal, row, today, existing=None):
    account = row.account
    if account.book_id != goal.book_id:
        raise LinkError(_("That account isn't in this set of books."))
    if account.is_system:
        raise LinkError(_("%(account)s is a bookkeeping account and can't hold a goal's money.") % {"account": account})
    if account.account_group.account_type != ACCOUNT_TYPE_ASSET:
        raise LinkError(_("Only asset accounts can be linked to a goal; %(account)s isn't one.") % {"account": account})
    if account.is_archived and existing is None:
        raise LinkError(_("%(account)s is archived.") % {"account": account})
    if row.start_date > today:
        raise LinkError(_("The start date for %(account)s can't be in the future.") % {"account": account})

    other_open = GoalAccountLink.objects.open().filter(account=account).exclude(goal=goal)
    taken = other_open.select_related("goal").first()
    if taken is not None:
        raise LinkError(
            _("%(account)s already feeds %(goal)s. Unlink it there first.")
            % {"account": account, "goal": taken.goal.name}
        )

    # An account's links never overlap: a new range starts after the last one ended.
    previous = GoalAccountLink.objects.filter(account=account, end_date__isnull=False)
    if existing is not None:
        previous = previous.exclude(pk=existing.pk)
    last_end = previous.order_by("-end_date").values_list("end_date", flat=True).first()
    if last_end is not None and row.start_date <= last_end:
        raise LinkError(
            _("%(account)s counted towards a goal until %(date)s. Start this link after that date.")
            % {"account": account, "date": last_end.strftime("%b %-d, %Y")}
        )


def _end(link, today):
    """End a link today; one made today is simply dropped (a mistake fixed the same day)."""
    if timezone.localtime(link.created_at).date() >= today:
        link.delete()
    else:
        link.end_date = max(today, link.start_date)
        link.save(update_fields=["end_date", "updated_at"])


@transaction.atomic
def set_links(goal, rows, today=None):
    """
    Make the goal's open links exactly `rows` (a list of `LinkRow`).

    An account no longer listed is unlinked today (its past months keep what it
    brought in); a listed account already linked has its start date and
    starting-balance choice updated; a new one is linked. Returns `LinkChanges`.
    """
    today = today or timezone.localdate()
    if rows and (goal.closed_at is not None or goal.is_archived):
        raise LinkError(_("A closed goal can't be linked to an account."))
    seen = set()
    for row in rows:
        if row.account.pk in seen:
            raise LinkError(_("%(account)s is listed twice.") % {"account": row.account})
        seen.add(row.account.pk)

    current = {link.account_id: link for link in GoalAccountLink.objects.open().filter(goal=goal).select_for_update()}
    changes = LinkChanges(linked=[], updated=[], unlinked=[])

    for account_id, link in current.items():
        if account_id not in seen:
            changes.unlinked.append(link)
            _end(link, today)

    for row in rows:
        existing = current.get(row.account.pk)
        _check_row(goal, row, today, existing)
        if existing is None:
            changes.linked.append(
                GoalAccountLink.objects.create(
                    book=goal.book,
                    goal=goal,
                    account=row.account,
                    start_date=row.start_date,
                    include_starting_balance=row.include_starting_balance,
                )
            )
        elif (existing.start_date, existing.include_starting_balance) != (
            row.start_date,
            row.include_starting_balance,
        ):
            existing.start_date = row.start_date
            existing.include_starting_balance = row.include_starting_balance
            existing.save(update_fields=["start_date", "include_starting_balance", "updated_at"])
            changes.updated.append(existing)
    return changes


@transaction.atomic
def unlink(link, today=None):
    today = today or timezone.localdate()
    if link.end_date is not None:
        raise LinkError(_("That account is already unlinked."))
    _end(link, today)


def end_all(goal, end_date):
    """End every open link of `goal` on `end_date` (closing or archiving the goal)."""
    for link in GoalAccountLink.objects.open().filter(goal=goal):
        link.end_date = max(end_date, link.start_date)
        link.save(update_fields=["end_date", "updated_at"])


class _Rollback(Exception):
    pass


def preview(book, goal, rows, outflow, month=None, today=None):
    """
    What saving `rows` and `outflow` on `goal` (None for a goal not yet created)
    would do, without writing anything: {"left_before", "left_after", "adds",
    "unassigned_before", "unassigned_after"} for `month` (default: this month).
    Raises `LinkError` exactly as saving would.
    """
    from .unassigned import compute_unassigned

    today = today or timezone.localdate()
    month = (month or today).replace(day=1)

    def left_of(goal_pk):
        if goal_pk is None:
            return ZERO
        return Goal.objects.filter(pk=goal_pk).with_progress(month).values_list("left", flat=True).get()

    goal_pk = goal.pk if goal is not None else None
    left_before = left_of(goal_pk)
    unassigned_before = compute_unassigned(book, month).amount
    result = {}
    try:
        with transaction.atomic():
            target = goal
            if target is None:
                target = Goal(book=book, name="__preview__", target_amount=ZERO)
            target.outflow = outflow
            target.save()
            set_links(target, rows, today=today)
            result["left_after"] = left_of(target.pk)
            result["unassigned_after"] = compute_unassigned(book, month).amount
            raise _Rollback
    except _Rollback:
        pass
    finally:
        if goal is not None:
            goal.refresh_from_db()
    result.update(
        left_before=left_before,
        adds=result["left_after"] - left_before,
        unassigned_before=unassigned_before,
    )
    return result
