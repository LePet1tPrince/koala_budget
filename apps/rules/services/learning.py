"""
Rules the book's history argues for (plan §9.6).

Nightly, per active book: group categorized single-category rows by merchant
signature (`signatures.signature_for`), and propose a rule for a merchant
categorized the same way at least `LEARN_MIN_COUNT` times with at least
`LEARN_MIN_CONSISTENCY` agreement, when no active rule already covers it. A
proposal the user dismissed (or accepted) is never touched again.
"""

from collections import Counter
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.bank_feed.models import BankTransaction

from .. import constants
from ..models import RuleProposal
from . import actions, engine
from .analysis import _single_categories, history_rows
from .apply import RuleSet, original_view
from .signatures import signature_for


def active_book_ids():
    """Books with a categorization in the last `LEARN_ACTIVE_DAYS` days."""
    since = timezone.now() - timedelta(days=constants.LEARN_ACTIVE_DAYS)
    return set(
        BankTransaction.objects.filter(journal_entry__isnull=False, updated_at__gte=since)
        .values_list("book_id", flat=True)
        .distinct()
    )


def _groups(book):
    """`{signature: {"field", "value", "rows": [(view, category id)]}}`, newest row first."""
    rows = list(history_rows(book))
    homes = {tx.journal_entry_id: tx.account_id for tx in rows}
    categories = _single_categories(list(homes), homes)
    groups = {}
    for tx in rows:
        cats = categories.get(tx.journal_entry_id, frozenset())
        if len(cats) != 1:
            continue
        view = original_view(tx)
        found = signature_for(view)
        if found is None:
            continue
        key, field, value = found
        group = groups.setdefault(key, {"field": field, "value": value, "rows": []})
        group["rows"].append((view, next(iter(cats))))
    return groups


@transaction.atomic
def propose(book):
    """Create, refresh or drop `book`'s open proposals. Returns the number open afterwards."""
    ruleset = RuleSet(book)
    accounts = actions.book_accounts(book)
    settled = set(
        RuleProposal.objects.filter(book=book)
        .exclude(status=RuleProposal.STATUS_OPEN)
        .values_list("signature", flat=True)
    )
    keep = set()
    for key, group in _groups(book).items():
        if key in settled:
            continue
        rows = group["rows"]
        if len(rows) < constants.LEARN_MIN_COUNT:
            continue
        ((category_id, top),) = Counter(cat for _view, cat in rows).most_common(1)
        consistency = (Decimal(top) / Decimal(len(rows))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if consistency < constants.LEARN_MIN_CONSISTENCY:
            continue
        category = accounts.get(category_id)
        if category is None or category.is_budget_bucket:
            continue
        if ruleset.first_match(rows[0][0]) is not None:
            continue
        signs = {view.amount > 0 for view, _cat in rows}
        direction = engine.DIRECTION_ANY
        if signs == {True}:
            direction = engine.DIRECTION_OUT
        elif signs == {False}:
            direction = engine.DIRECTION_IN
        RuleProposal.objects.update_or_create(
            book=book,
            signature=key,
            defaults={
                "field": group["field"],
                "value": group["value"][:255],
                "direction": direction,
                "category": category,
                "evidence_count": len(rows),
                "consistency": consistency,
                "status": RuleProposal.STATUS_OPEN,
            },
        )
        keep.add(key)
    RuleProposal.objects.filter(book=book, status=RuleProposal.STATUS_OPEN).exclude(signature__in=keep).delete()
    return len(keep)
