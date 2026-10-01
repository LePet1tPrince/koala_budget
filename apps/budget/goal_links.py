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


# --- The goal form ---------------------------------------------------------------
#
# Field names (the form posts them; the preview endpoint reads the same ones):
#   link_account          one per ticked account (its id)
#   link_start_<id>       the account's "count from" date
#   link_include_<id>     present when its existing balance counts


def parse_link_rows(book, data, today=None):
    """`LinkRow`s from the goal form's fields. Raises `LinkError` on a bad id or date."""
    from django.utils.dateparse import parse_date

    today = today or timezone.localdate()
    ids = []
    for raw in data.getlist("link_account"):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            raise LinkError(_("That account isn't in this set of books.")) from None
    accounts = {a.pk: a for a in Account.objects.filter(book=book, pk__in=ids).select_related("account_group")}
    rows = []
    for pk in ids:
        account = accounts.get(pk)
        if account is None:
            raise LinkError(_("That account isn't in this set of books."))
        raw_start = (data.get(f"link_start_{pk}") or "").strip()
        start = parse_date(raw_start) if raw_start else today
        if start is None:
            raise LinkError(_("Enter a valid start date for %(account)s.") % {"account": account})
        rows.append(
            LinkRow(account=account, start_date=start, include_starting_balance=bool(data.get(f"link_include_{pk}")))
        )
    return rows


def link_options(book, goal=None, data=None, today=None):
    """
    The accounts the goal form offers, each a dict: account, balance, checked,
    start (ISO date), include, feeds (the other goal it feeds, if any) and
    disabled. With `data` (a re-rendered post) the user's choices win.
    """
    today = today or timezone.localdate()
    current = {}
    if goal is not None and goal.pk:
        current = {link.account_id: link for link in GoalAccountLink.objects.open().filter(goal=goal)}
    ticked = set(data.getlist("link_account")) if data is not None else None
    options = []
    for account in eligible_accounts(book, goal).with_balance():
        link = current.get(account.pk)
        feeds = account.feeds_goal_name if account.is_linked and link is None else None
        if ticked is not None:
            checked = str(account.pk) in ticked
            start = data.get(f"link_start_{account.pk}") or today.isoformat()
            include = bool(data.get(f"link_include_{account.pk}")) if checked else True
        else:
            checked = link is not None
            start = (link.start_date if link else today).isoformat()
            include = link.include_starting_balance if link else True
        options.append(
            {
                "account": account,
                "balance": account.balance,
                "checked": checked,
                "start": start,
                "include": include,
                "feeds": feeds,
                "disabled": bool(feeds),
            }
        )
    return options


# --- The goal page ---------------------------------------------------------------

ACTIVITY_ASSIGNED = "assigned"
ACTIVITY_WITHDRAWN = "withdrawn"
ACTIVITY_STARTING = "starting"
ACTIVITY_IN = "in"
ACTIVITY_OUT = "out"
ACTIVITY_SPENT = "spent"


def goal_activity(goal, limit=100):
    """
    Everything that moved the goal, newest first: manual allocations (by month),
    starting balances, each linked line that counted, and spending from the goal's
    own account. Each event: date, kind, account (for linked events), payee, memo
    and amount -- its effect on what's left in the goal (spending negative).
    """
    from apps.journal.models import JournalLine, counted_entries

    from .linked import linked_lines, starting_balances

    events = []
    for allocation in goal.allocations.exclude(amount=0):
        events.append(
            {
                "date": allocation.month,
                "kind": ACTIVITY_ASSIGNED if allocation.amount > 0 else ACTIVITY_WITHDRAWN,
                "account": None,
                "payee": "",
                "memo": allocation.notes,
                "amount": allocation.amount,
                "month_only": True,
            }
        )
    for link in starting_balances().filter(goal=goal).select_related("account").exclude(amount=0):
        events.append(
            {
                "date": link.start_date,
                "kind": ACTIVITY_STARTING,
                "account": link.account,
                "payee": "",
                "memo": "",
                "amount": link.amount,
                "month_only": False,
            }
        )
    lines = (
        linked_lines()
        .filter(link_goal=goal.pk)
        .filter(Q(alloc_delta__lt=0) | Q(alloc_delta__gt=0) | Q(spent_delta__gt=0) | Q(spent_delta__lt=0))
        .select_related("journal_entry", "journal_entry__payee", "account")
    )
    for line in lines:
        entry = line.journal_entry
        common = {
            "date": entry.entry_date,
            "account": line.account,
            "payee": entry.payee.name if entry.payee else "",
            "memo": entry.description,
            "month_only": False,
        }
        if line.alloc_delta:
            kind = ACTIVITY_IN if line.alloc_delta > 0 else ACTIVITY_OUT
            events.append({**common, "kind": kind, "amount": line.alloc_delta})
        if line.spent_delta:
            events.append({**common, "kind": ACTIVITY_SPENT, "amount": -line.spent_delta})
    if goal.account_id:
        own = (
            JournalLine.objects.filter(counted_entries("journal_entry__"), account_id=goal.account_id)
            .select_related("journal_entry", "journal_entry__payee")
            .order_by("-journal_entry__entry_date")[:limit]
        )
        for line in own:
            entry = line.journal_entry
            events.append(
                {
                    "date": entry.entry_date,
                    "kind": ACTIVITY_SPENT,
                    "account": None,
                    "payee": entry.payee.name if entry.payee else "",
                    "memo": entry.description,
                    "amount": line.cr_amount - line.dr_amount,
                    "month_only": False,
                }
            )
    events.sort(key=lambda e: e["date"], reverse=True)
    return events[:limit]


def link_drift(goal, left):
    """
    How far the goal's `left` is from the balance of the accounts it is linked to
    now, with the reasons that apply. None when the goal has no open link or the
    two agree.
    """
    from apps.bank_feed.models import BankTransaction

    from .linked import starting_balances

    links = list(GoalAccountLink.objects.open().filter(goal=goal).select_related("account"))
    if not links:
        return None
    accounts = Account.objects.filter(pk__in=[link.account_id for link in links]).with_balance()
    held = sum((a.balance for a in accounts), ZERO)
    gap = held - left
    if not gap:
        return None

    reasons = []
    assigned = sum((a.amount for a in goal.allocations.all()), ZERO)
    if assigned:
        reasons.append(_("You assigned or withdrew %(amount)s by hand.") % {"amount": _money(assigned)})
    counted_start = {link.pk for link in starting_balances().filter(goal=goal)}
    for link in links:
        if link.pk not in counted_start:
            reasons.append(
                _("What %(account)s held before %(date)s isn't counted.")
                % {"account": link.account, "date": link.start_date.strftime("%b %-d, %Y")}
            )
    for link in links:
        waiting = BankTransaction.objects.filter(
            account=link.account, journal_entry__isnull=True, is_archived=False
        ).count()
        if waiting:
            reasons.append(
                _("%(count)s transactions in %(account)s aren't categorized yet.")
                % {"count": waiting, "account": link.account}
            )
    reasons.append(
        _(
            "Purchases and refunds in these accounts belong to their budget categories, and spending "
            "from the goal through other accounts comes out of the goal but not these accounts."
        )
    )
    return {"held": held, "left": left, "gap": gap, "reasons": reasons}


def _money(amount):
    from apps.web.templatetags.currency_tags import currency

    return currency(amount)
