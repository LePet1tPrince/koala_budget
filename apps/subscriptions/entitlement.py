"""
Who may write to a team's books.

A team is *entitled* while any one of these holds:

* its Stripe subscription is active, trialing or past due (the statuses
  `helpers.subscription_is_active` counts);
* its free trial has not ended (`Team.trial_ends_at`, set when the team is
  created: `settings.TRIAL_DAYS`, no card);
* it is complimentary (`Team.is_complimentary`, set in the admin).

An unentitled team's books are read-only: `middleware.SubscriptionGateMiddleware`
refuses every unsafe request to a book URL, and the Plaid sync and the recurring
schedules skip its books (`entitled_teams_q`). Every page, and the data export,
stays readable.

Kept free of `helpers` (which imports `Team`) so `apps.teams.models` can import it.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone
from djstripe.enums import SubscriptionStatus

ACTIVE_STATUSES = (SubscriptionStatus.active, SubscriptionStatus.trialing, SubscriptionStatus.past_due)

SUBSCRIBED = "subscribed"
COMPLIMENTARY = "complimentary"
TRIAL = "trial"
READ_ONLY = "read_only"

# Banner during a trial's last days only: a 60-day banner would be noise.
TRIAL_WARNING_DAYS = 14

# Serializes founding-spot claims (pg_advisory_xact_lock key; any fixed bigint).
_FOUNDING_LOCK_KEY = 7_316_002_501


def default_trial_end() -> datetime:
    return timezone.now() + timedelta(days=settings.TRIAL_DAYS)


def entitled_teams_q(prefix: str = "") -> Q:
    """`Q` over `Team` (or a model reaching it through `prefix`, e.g. "book__team__") for entitled teams."""
    return (
        Q(**{f"{prefix}is_complimentary": True})
        | Q(**{f"{prefix}trial_ends_at__gt": timezone.now()})
        | Q(**{f"{prefix}subscription__status__in": ACTIVE_STATUSES})
    )


@dataclasses.dataclass(frozen=True)
class Access:
    status: str
    trial_ends_at: datetime | None

    @property
    def can_write(self) -> bool:
        return self.status != READ_ONLY

    @property
    def trial_days_left(self) -> int | None:
        if self.status != TRIAL:
            return None
        # Rounded up: 4 days 23 hours left reads "5 days", the last hours "1 day".
        return max(0, math.ceil((self.trial_ends_at - timezone.now()).total_seconds() / 86400))

    @property
    def show_banner(self) -> bool:
        return self.status == READ_ONLY or (self.status == TRIAL and self.trial_days_left <= TRIAL_WARNING_DAYS)


def team_access(team) -> Access:
    if team.has_active_subscription():
        return Access(SUBSCRIBED, team.trial_ends_at)
    if team.is_complimentary:
        return Access(COMPLIMENTARY, team.trial_ends_at)
    if team.trial_ends_at and team.trial_ends_at > timezone.now():
        return Access(TRIAL, team.trial_ends_at)
    return Access(READ_ONLY, team.trial_ends_at)


def is_entitled(team) -> bool:
    return team_access(team).can_write


def claim_founding_spot(team_model) -> bool:
    """
    Whether a team being created now gets a founding spot: true while fewer than
    `settings.FOUNDING_MEMBER_LIMIT` teams hold one. Call inside the creating
    transaction; the advisory lock is held until it commits, so two signups at
    spot 499 can't both take it.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_FOUNDING_LOCK_KEY])
    return team_model.objects.filter(is_founding_member=True).count() < settings.FOUNDING_MEMBER_LIMIT
