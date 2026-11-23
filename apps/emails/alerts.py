"""
What each email says and who gets it. Everything here sends through `services.send`.

* Bank connection: every member of the book's team, when a Plaid item moves to a
  status the user has to act on. Once per item, status and day.
* Overspending: every member, from the daily task, when spending this month takes
  an expense category below zero. Once per category and month; one email lists
  every category overspent right now.
* Billing (trial ending, payment failed, renewal coming): the team's admins, from
  Stripe's webhooks. Once per Stripe object and date.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.web.meta import absolute_url

from . import kinds
from .services import send

logger = logging.getLogger(__name__)

#: PlaidItem statuses that get an email (all but healthy).
BANK_ALERT_STATUSES = ("login_required", "pending_expiration", "pending_disconnect", "revoked", "error")


def _members(team):
    return list(team.members.filter(is_active=True))


def _admins(team):
    from apps.teams.roles import ROLE_ADMIN

    # Through this team's memberships: `team.members.filter(membership__role=...)`
    # would also match someone who is an admin of a different team.
    memberships = team.membership_set.filter(role=ROLE_ADMIN, user__is_active=True).select_related("user")
    return [membership.user for membership in memberships]


# --- Bank connection ---------------------------------------------------------


def bank_connection(item_id, status) -> int:
    """Email the team that a bank connection needs them. Returns how many emails went out."""
    from apps.plaid.models import PlaidItem

    item = PlaidItem.objects.select_related("book__team").filter(pk=item_id).first()
    # Fixed (or changed again) before this ran: the newer status has its own email.
    if item is None or item.status != status or status not in BANK_ALERT_STATUSES or item.book.is_archived:
        return 0
    book = item.book
    context = {
        "item": item,
        "status": status,
        "book": book,
        "inbox_url": absolute_url(reverse("bank_feed:bank_feed_home", args=book.url_args)),
    }
    key = f"{item.pk}:{status}:{timezone.localdate().isoformat()}"
    return sum(send(user, kinds.BANK_CONNECTION, context, keys=[key], book=book) for user in _members(book.team))


# --- Overspending -------------------------------------------------------------


def overspent_categories(book, month):
    """
    Expense categories below zero at the end of `month` that had spending in it.

    The same Available the budget page shows (`BudgetService`), but a category
    that is negative only because last month's overspending rolled in, with
    nothing spent this month, is left out: it was already reported last month.
    """
    from apps.accounts.models import ACCOUNT_TYPE_EXPENSE
    from apps.budget import ledger
    from apps.budget.figures import budgeted_categories
    from apps.budget.services import BudgetService

    categories = [c for c in budgeted_categories(book) if c.account_group.account_type == ACCOUNT_TYPE_EXPENSE]
    if not categories:
        return []
    service = BudgetService(book)
    available, _previous = service.get_available_with_previous(month, categories)
    actual = service.get_actuals_by_category(month)
    budgeted = ledger.budgeted_in_month(book, month)
    zero = Decimal("0")
    return [
        {
            "category": category,
            "budgeted": budgeted.get(category.pk, zero),
            "spent": actual.get(category.pk, zero),
            "available": available[category.pk],
            "over_by": -available[category.pk],
        }
        for category in categories
        if available[category.pk] < 0 and actual.get(category.pk, zero) > 0
    ]


def budget_overspent(book, month=None) -> int:
    """Email the team about this month's overspent categories, when one is new. Returns emails sent."""
    from apps.budget import ledger

    if book.is_archived or not ledger.has_budget(book):
        return 0
    month = (month or timezone.localdate()).replace(day=1)
    rows = overspent_categories(book, month)
    if not rows:
        return 0
    context = {
        "book": book,
        "month": month,
        "rows": rows,
        "budget_url": absolute_url(reverse("budget:budget_home", args=book.url_args)),
    }
    keys = [f"{book.pk}:{month:%Y-%m}:{row['category'].pk}" for row in rows]
    return sum(send(user, kinds.BUDGET_OVERSPENT, context, keys=keys, book=book) for user in _members(book.team))


# --- Billing --------------------------------------------------------------------


def _team(subscription_id=None, customer_id=None):
    from apps.teams.models import Team

    if subscription_id:
        team = Team.objects.filter(subscription__id=subscription_id).first()
        if team:
            return team
    if customer_id:
        return Team.objects.filter(customer__id=customer_id).first()
    return None


def _date(timestamp):
    return datetime.fromtimestamp(timestamp, tz=UTC).date() if timestamp else None


def _money(cents, currency):
    """`5900, "cad"` -> "$59.00 CAD" (Stripe amounts are in the currency's smallest unit)."""
    return f"${Decimal(cents or 0) / 100:,.2f} {(currency or '').upper()}".strip()


def _billing_context(team):
    return {
        "team": team,
        "subscription_url": absolute_url(reverse("subscriptions_team:subscription_details", args=[team.slug])),
    }


def _send_admins(team, kind, context, key) -> int:
    return sum(send(user, kind, context, keys=[key]) for user in _admins(team))


def _local_subscription(subscription_id):
    from djstripe.models import Subscription

    return Subscription.objects.filter(id=subscription_id).first() if subscription_id else None


def trial_ending(subscription) -> int:
    """`customer.subscription.trial_will_end` (three days out). `subscription` is Stripe's object."""
    if subscription.get("cancel_at_period_end"):
        return 0  # they cancelled: nothing will be charged
    team = _team(subscription.get("id"), subscription.get("customer"))
    if team is None:
        logger.warning("trial_will_end for unknown subscription %s", subscription.get("id"))
        return 0
    context = {**_billing_context(team), "trial_end": _date(subscription.get("trial_end"))}
    return _send_admins(team, kinds.TRIAL_ENDING, context, f"{subscription.get('id')}:{subscription.get('trial_end')}")


def payment_failed(invoice) -> int:
    """`invoice.payment_failed`. One email per attempt Stripe makes."""
    team = _team(invoice.get("subscription"), invoice.get("customer"))
    if team is None:
        logger.warning("invoice.payment_failed for unknown customer %s", invoice.get("customer"))
        return 0
    context = {
        **_billing_context(team),
        "amount": _money(invoice.get("amount_due"), invoice.get("currency")),
        "next_attempt": _date(invoice.get("next_payment_attempt")),
        "invoice_url": invoice.get("hosted_invoice_url") or "",
    }
    key = f"{invoice.get('id')}:{invoice.get('attempt_count')}"
    return _send_admins(team, kinds.PAYMENT_FAILED, context, key)


def _interval(invoice):
    lines = (invoice.get("lines") or {}).get("data") or []
    if not lines:
        return None
    line = lines[0]
    recurring = (line.get("price") or {}).get("recurring") or {}
    return recurring.get("interval") or (line.get("plan") or {}).get("interval")


def renewal_upcoming(invoice) -> int:
    """
    `invoice.upcoming` (Stripe's "upcoming renewal events" setting, days ahead).
    Annual plans only -- a monthly reminder is noise -- and not during a trial,
    which has its own email, nor when the subscription is set to cancel.
    """
    if _interval(invoice) != "year":
        return 0
    subscription_id = invoice.get("subscription")
    local = _local_subscription(subscription_id)
    if local is not None and (local.cancel_at_period_end or local.status == "trialing"):
        return 0
    team = _team(subscription_id, invoice.get("customer"))
    if team is None:
        logger.warning("invoice.upcoming for unknown customer %s", invoice.get("customer"))
        return 0
    renews = invoice.get("next_payment_attempt") or invoice.get("period_end")
    context = {
        **_billing_context(team),
        "amount": _money(invoice.get("amount_due"), invoice.get("currency")),
        "renews_on": _date(renews),
    }
    return _send_admins(team, kinds.RENEWAL_UPCOMING, context, f"{subscription_id}:{renews}")
