import logging
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce


def _counted():
    """Lines of entries that count (not void, not behind an archived bank transaction)."""
    from apps.journal.models import counted_entries

    return counted_entries("journal_lines__journal_entry__")


class AccountQuerySet(models.QuerySet):
    """Custom QuerySet for Account model with optimized balance calculation."""

    def with_balance(self):
        """Annotate accounts with their calculated balance in a single query."""
        counted = _counted()
        return self.annotate(
            _balance=Coalesce(Sum("journal_lines__dr_amount", filter=counted), Decimal("0"))
            - Coalesce(Sum("journal_lines__cr_amount", filter=counted), Decimal("0"))
        )

    def with_reconciled_balance(self):
        """Annotate accounts with their reconciled balance (only reconciled journal lines)."""
        reconciled = Q(journal_lines__is_reconciled=True) & _counted()
        return self.annotate(
            _reconciled_balance=Coalesce(Sum("journal_lines__dr_amount", filter=reconciled), Decimal("0"))
            - Coalesce(Sum("journal_lines__cr_amount", filter=reconciled), Decimal("0"))
        )


class AccountTeamScopedManager(models.Manager):
    """
    Team-scoped manager for Account model that uses AccountQuerySet.
    Combines TeamScopedManager filtering with AccountQuerySet methods.
    """

    def get_queryset(self):
        from apps.teams.context import EmptyTeamContextException, get_current_team

        queryset = AccountQuerySet(self.model, using=self._db)
        team = get_current_team()
        if team is None:
            if getattr(settings, "STRICT_TEAM_CONTEXT", False):
                raise EmptyTeamContextException("Team missing from context")
            else:
                logging.warning("Team not available in filtered context. Use `set_current_team()`.")
            return queryset.none()
        return queryset.filter(team=team)
