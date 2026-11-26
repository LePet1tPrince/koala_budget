"""
Categorize Mode's queue: the uncategorized rows in scope, grouped by merchant.

The same merchant turns up over and over, so the queue is a list of groups, not
of rows: one pick files every row in a group. A group is the rows of one feed
account, one direction (money out or in) and one merchant signature
(`apps.rules.services.signatures.signature_for` -- the key rule drafts and
learned rules use, so a group and the rule offered after filing it agree on what
"this merchant" is). Rows a rule suggests for are grouped by the rule's category
as well, so one group never mixes two rules' answers.

Each group carries the categories similar transactions were filed under
(`similar_transactions`, history indexed once for the whole queue) or the
rule's suggestion, and `confident`: whether that guess is safe to offer as a
one-click "file all" -- a rule's suggestion, or a payee/description match seen
at least `CONFIDENT_MIN_COUNT` times that accounts for at least
`CONFIDENT_SHARE` of the matched history.

Order: confident groups first (quick wins), then the biggest groups, then the
most recent. Nothing here writes.
"""

from dataclasses import dataclass, field

from apps.rules.services.signatures import signature_for

from .similar_transactions import (
    MATCH_DESCRIPTION,
    MATCH_PAYEE,
    build_history_index,
    normalize,
    suggest_categories_for,
)

MATCH_RULE = "rule"

#: How many suggestions each group carries.
SUGGESTION_LIMIT = 3

#: A history guess is confident when its category was used this many times ...
CONFIDENT_MIN_COUNT = 2
#: ... and makes up at least this share of every matched categorization.
CONFIDENT_SHARE = 0.8

#: Words that say how money moved, not who it went to. A signature made only of
#: these ("CHECK 1042", "ATM WITHDRAWAL", "DEPOSIT") would pull unrelated rows
#: into one group -- every cheque, whoever it paid -- so such rows stay single.
GENERIC_TOKENS = frozenset(
    {
        "atm",
        "bill",
        "cash",
        "check",
        "cheque",
        "deposit",
        "etransfer",
        "fee",
        "interac",
        "mobile",
        "online",
        "transfer",
        "venmo",
        "wire",
        "withdrawal",
        "zelle",
    }
)


@dataclass
class QueueGroup:
    key: str
    rows: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    confident: bool = False

    def as_dict(self):
        return {
            "key": self.key,
            "ids": [tx.pk for tx in self.rows],
            "suggestions": self.suggestions,
            "confident": self.confident,
        }


def _open_rule_suggestion(tx):
    """The row's open rule suggestion with a single category, or None."""
    match = getattr(tx, "rule_match", None)
    if match is None or match.status != "suggested" or not match.category_id or match.splits:
        return None
    return match


def merchant_key(tx):
    """The row's merchant signature, or None when it names no one in particular."""
    found = signature_for(tx)
    if found is None:
        return None
    key, _field, value = found
    words = set(normalize(value).split())
    if words and words <= GENERIC_TOKENS:
        return None
    return key


def group_key(tx):
    """Which group `tx` belongs to. A row with no merchant signature is a group of its own."""
    merchant = merchant_key(tx)
    if merchant is None:
        return f"row:{tx.pk}"
    direction = "out" if tx.amount > 0 else "in"
    match = _open_rule_suggestion(tx)
    rule_part = f"rule:{match.category_id}" if match else ""
    return f"{tx.account_id}|{direction}|{rule_part}|{merchant}"


def _rule_suggestions(match):
    return [
        {
            "category_id": match.category_id,
            "category_name": match.category.name,
            "count": None,
            "match_type": MATCH_RULE,
            "payee": "",
            "rule_name": match.rule_name,
        }
    ]


def _history_suggestions(tx, index):
    """`(suggestions, confident)` from how similar transactions were filed."""
    if index is None:
        return [], False
    # Every matched category, not just the top few: confidence is the top one's
    # share of all of them.
    ranked = [s for s in suggest_categories_for(tx, index, limit=None) if s["category_id"] != tx.account_id]
    if not ranked:
        return [], False
    top = ranked[0]
    total = sum(s["count"] for s in ranked)
    confident = (
        top["match_type"] in (MATCH_PAYEE, MATCH_DESCRIPTION)
        and top["count"] >= CONFIDENT_MIN_COUNT
        and top["count"] >= CONFIDENT_SHARE * total
    )
    return [{**s, "rule_name": ""} for s in ranked[:SUGGESTION_LIMIT]], confident


def build_queue(book, rows):
    """
    `rows` (uncategorized BankTransactions, newest first) as ordered groups:
    `[{key, ids, suggestions, confident}]`, each group's ids newest first.
    """
    groups = {}
    for tx in rows:
        key = group_key(tx)
        groups.setdefault(key, QueueGroup(key=key)).rows.append(tx)

    index = None
    if any(_open_rule_suggestion(g.rows[0]) is None for g in groups.values()):
        index = build_history_index(book)
        if not len(index):
            index = None

    for group in groups.values():
        lead = group.rows[0]
        match = _open_rule_suggestion(lead)
        if match is not None:
            group.suggestions, group.confident = _rule_suggestions(match), True
        else:
            group.suggestions, group.confident = _history_suggestions(lead, index)

    ordered = sorted(
        groups.values(),
        key=lambda g: (not g.confident, -len(g.rows), -g.rows[0].posted_date.toordinal(), -g.rows[0].pk),
    )
    return [g.as_dict() for g in ordered]
