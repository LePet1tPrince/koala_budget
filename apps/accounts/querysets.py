from decimal import Decimal

from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce


def _counted():
    """Lines of entries that count (not void, not behind an archived bank transaction)."""
    from apps.journal.models import counted_entries

    return counted_entries("journal_lines__journal_entry__")


def _through(as_of):
    """Lines of entries dated on or before `as_of`; every line when it is None."""
    return Q(journal_lines__journal_entry__entry_date__lte=as_of) if as_of else Q()


class AccountQuerySet(models.QuerySet):
    """Custom QuerySet for Account model with optimized balance calculation."""

    def with_balance(self, as_of=None):
        """Annotate accounts with their calculated balance in a single query (optionally as of a date)."""
        counted = _counted() & _through(as_of)
        return self.annotate(
            _balance=Coalesce(Sum("journal_lines__dr_amount", filter=counted), Decimal("0"))
            - Coalesce(Sum("journal_lines__cr_amount", filter=counted), Decimal("0"))
        )

    def with_reconciled_balance(self, as_of=None):
        """Annotate accounts with their reconciled balance (only reconciled journal lines, optionally as of a date)."""
        reconciled = Q(journal_lines__is_reconciled=True) & _counted() & _through(as_of)
        return self.annotate(
            _reconciled_balance=Coalesce(Sum("journal_lines__dr_amount", filter=reconciled), Decimal("0"))
            - Coalesce(Sum("journal_lines__cr_amount", filter=reconciled), Decimal("0"))
        )
