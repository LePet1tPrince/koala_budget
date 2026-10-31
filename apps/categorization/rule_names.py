"""
Naming a rule, and drafting one from a transaction.

The editor opens on a draft built here -- from a categorize-mode card or the
feed's edit modal -- so "Always categorize transactions like this" starts from
the conditions most likely to be right rather than an empty form.
"""

from apps.bank_feed.services.similar_transactions import MIN_TOKEN_LENGTH, NOISE_TOKENS, normalize

from .models import (
    DIRECTION_INFLOW,
    DIRECTION_OUTFLOW,
    MATCH_ANY,
    MATCH_EQUALS,
    MATCH_WORDS,
    MODE_AUTO,
    CategorizationRule,
)

MAX_NAME = 200


def ordered_signature_words(text) -> list[str]:
    """`signature_tokens(text)`, in the order they appear -- for a readable "has the words" value."""
    words = []
    for token in normalize(text).split():
        if token.isdigit() or len(token) < MIN_TOKEN_LENGTH or token in NOISE_TOKENS or token in words:
            continue
        words.append(token)
    return words


def base_name(rule) -> str:
    """ "Blue Bottle → Coffee"-style name from what the rule matches and files to."""
    if rule.payee_match != MATCH_ANY and rule.payee_value:
        subject = rule.payee_value.strip()
    elif rule.description_match != MATCH_ANY and rule.description_value:
        subject = rule.description_value.strip()
    elif rule.amount_min is not None or rule.amount_max is not None:
        low, high = rule.amount_min, rule.amount_max
        subject = f"${low}" if low == high or high is None else (f"up to ${high}" if low is None else f"${low}–${high}")
    else:
        subject = "Rule"
    target = rule.category.name if getattr(rule, "category_id", None) and rule.category else ""
    name = f"{subject} → {target}" if target else subject
    return name[:MAX_NAME]


def unique_rule_name(book, rule, exclude_id=None) -> str:
    name = base_name(rule)
    taken = set(CategorizationRule.objects.filter(book=book).exclude(pk=exclude_id).values_list("name", flat=True))
    taken_lower = {n.lower() for n in taken}
    if name.lower() not in taken_lower:
        return name
    for n in range(2, 1000):
        candidate = f"{name[: MAX_NAME - 6]} ({n})"
        if candidate.lower() not in taken_lower:
            return candidate
    return name


def draft_from_row(row, category=None) -> dict:
    """
    An unsaved rule matching `row`, as the API payload the editor opens on.

    A payee is matched exactly (normalized); without one, the description's
    meaningful words are, which ignores the terminal and order numbers that
    change on every charge from the same merchant.
    """
    draft = {
        "name": "",
        "mode": MODE_AUTO,
        "is_enabled": True,
        "payee_match": MATCH_ANY,
        "payee_value": "",
        "description_match": MATCH_ANY,
        "description_value": "",
        "amount_min": None,
        "amount_max": None,
        "direction": DIRECTION_OUTFLOW if row.amount > 0 else DIRECTION_INFLOW,
        "account": None,
        "category": category.id if category else None,
        "set_payee": "",
        "set_description": "",
    }
    payee = (row.merchant_name or "").strip()
    if payee and normalize(payee):
        draft["payee_match"] = MATCH_EQUALS
        draft["payee_value"] = payee
    else:
        words = ordered_signature_words(row.description)
        if words:
            draft["description_match"] = MATCH_WORDS
            draft["description_value"] = " ".join(words)
        else:
            draft["description_match"] = MATCH_EQUALS
            draft["description_value"] = row.description or ""
    unsaved = CategorizationRule(
        book=row.book,
        payee_match=draft["payee_match"],
        payee_value=draft["payee_value"],
        description_match=draft["description_match"],
        description_value=draft["description_value"],
        category=category,
    )
    draft["name"] = unique_rule_name(row.book, unsaved)
    return draft
