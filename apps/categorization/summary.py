"""
Reading a decision back, for the feed's "Rule" badge. Kept free of imports from
the bank feed so `bank_feed.serializers` can call it without a cycle.
"""

from django.core.exceptions import ObjectDoesNotExist


def decision_summary(tx, category_id):
    """
    `{source, label, rule_id, rule_name, reason, confidence}` while `tx` is still
    filed the way a provider filed it, else None. For the feed's badge.
    """
    if not tx.journal_entry_id or category_id is None:
        return None
    try:
        decision = tx.categorization_decision
    except ObjectDoesNotExist:
        return None
    if decision is None or not decision.stands_for(tx, category_id):
        return None
    rule = decision.rule
    return {
        "source": decision.source,
        "label": decision.label,
        "rule_id": decision.rule_id,
        "rule_name": rule.name if rule else "",
        "reason": decision.reason,
        "confidence": float(decision.confidence) if decision.confidence is not None else None,
    }
