"""
The history provider: how the book filed transactions that look like this one.

A thin wrapper over `apps/bank_feed/services/similar_transactions.py`, which
stays the single definition of "looks like" -- this module only turns its
suggestions into the provider contract.
"""

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.bank_feed.services.similar_transactions import (
    MATCH_DESCRIPTION,
    MATCH_PAYEE,
    build_history_index,
    suggest_categories_for,
)

from ..models import SOURCE_HISTORY
from .base import Suggestion

# How much a tier says on its own; more evidence raises it towards the tier's ceiling.
TIER_CONFIDENCE = {MATCH_PAYEE: 0.85, MATCH_DESCRIPTION: 0.75}
SIMILAR_CONFIDENCE = 0.55


def confidence_for(match_type, count) -> float:
    ceiling = TIER_CONFIDENCE.get(match_type, SIMILAR_CONFIDENCE)
    return round(ceiling * count / (count + 1), 3)


def reason_for(match_type, count) -> str:
    if match_type == MATCH_PAYEE:
        return ngettext(
            "%(count)d transaction with this payee was categorized as this",
            "%(count)d transactions with this payee were categorized as this",
            count,
        ) % {"count": count}
    if match_type == MATCH_DESCRIPTION:
        return ngettext(
            "%(count)d transaction with this description was categorized as this",
            "%(count)d transactions with this description were categorized as this",
            count,
        ) % {"count": count}
    return ngettext(
        "%(count)d transaction like this one was categorized as this",
        "%(count)d transactions like this one were categorized as this",
        count,
    ) % {"count": count}


class HistoryProvider:
    key = "history"
    source = SOURCE_HISTORY
    # Suggest-only. A future per-book setting may let it file rows (policy.py).
    can_auto_apply = True

    def suggest(self, context, rows):
        rows = list(rows)
        if not rows:
            return {}
        index = build_history_index(context.book)
        if not len(index):
            return {}
        results = {}
        for row in rows:
            found = suggest_categories_for(row, index)
            if not found:
                continue
            results[row.id] = [
                Suggestion(
                    category_id=s["category_id"],
                    source=SOURCE_HISTORY,
                    provider=self.key,
                    confidence=confidence_for(s["match_type"], s["count"]),
                    reason=reason_for(s["match_type"], s["count"]) or _("Used before"),
                    category_name=s["category_name"],
                    count=s["count"],
                    match_type=s["match_type"],
                    payee=s["payee"],
                )
                for s in found
            ]
        return results
