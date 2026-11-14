"""
Does a rule match a feed transaction? Pure functions over in-memory objects: no queries.

The same code answers ingestion (`apply.run`), the builder's Test panel, the
backtest, conflict detection and "why didn't it match?" (`analysis`), so what
the user is shown is exactly what will happen.

Semantics (docs/transaction-rules-plan.md §5):

* `payee` reads `BankTransaction.merchant_name` (null = ""), `description` the
  description; both sides are `normalize`d (lowercase, punctuation to spaces)
  before comparing, and `contains` is a substring test on the normalized text.
* `amount` compares the absolute amount; the sign is the rule's `direction`.
* Direction and accounts always AND; `match` says how the conditions combine.
* Rules are tried in `(priority, id)` order; the first that matches wins.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from apps.bank_feed.services.similar_transactions import normalize

FIELD_PAYEE = "payee"
FIELD_DESCRIPTION = "description"
FIELD_AMOUNT = "amount"
TEXT_FIELDS = (FIELD_PAYEE, FIELD_DESCRIPTION)
FIELDS = (*TEXT_FIELDS, FIELD_AMOUNT)

OP_CONTAINS = "contains"
OP_NOT_CONTAINS = "not_contains"
OP_EQUALS = "equals"
OP_GT = "gt"
OP_LT = "lt"
OP_BETWEEN = "between"
TEXT_OPS = (OP_CONTAINS, OP_NOT_CONTAINS, OP_EQUALS)
AMOUNT_OPS = (OP_EQUALS, OP_GT, OP_LT, OP_BETWEEN)

DIRECTION_ANY = "any"
DIRECTION_IN = "in"
DIRECTION_OUT = "out"

MATCH_ALL = "all"
MATCH_ANY = "any"

# An unsaved draft sorts after saved rules of the same priority, as a new rule would.
_UNSAVED_ID = float("inf")


class ConditionError(ValueError):
    """A condition that cannot be evaluated: unknown field or op, or a bad value."""


@dataclass(frozen=True)
class Condition:
    field: str
    op: str
    value: object  # normalized str for text; Decimal, or (low, high), for amount
    raw: object  # what the user typed, for display


@dataclass(frozen=True)
class CompiledRule:
    id: object
    priority: int
    direction: str
    account_ids: frozenset
    match: str
    conditions: tuple
    rule: object = field(default=None, compare=False)

    @property
    def sort_key(self):
        return (self.priority, self.id if self.id is not None else _UNSAVED_ID)


def _decimal(value):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ConditionError(f"'{value}' is not an amount.") from None


def compile_condition(raw):
    """Check one `{field, op, value}` and prepare it for matching. Raises ConditionError."""
    if not isinstance(raw, dict):
        raise ConditionError("A condition must be an object.")
    name, op, value = raw.get("field"), raw.get("op"), raw.get("value")
    if name in TEXT_FIELDS:
        if op not in TEXT_OPS:
            raise ConditionError(f"'{op}' is not a text comparison.")
        text = normalize(value if isinstance(value, str) else "")
        if not text:
            raise ConditionError("Text to match must have at least one letter or digit.")
        return Condition(name, op, text, value)
    if name == FIELD_AMOUNT:
        if op not in AMOUNT_OPS:
            raise ConditionError(f"'{op}' is not an amount comparison.")
        if op == OP_BETWEEN:
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ConditionError("'between' needs a low and a high amount.")
            low, high = abs(_decimal(value[0])), abs(_decimal(value[1]))
            if low > high:
                low, high = high, low
            return Condition(name, op, (low, high), list(value))
        return Condition(name, op, abs(_decimal(value)), value)
    raise ConditionError(f"'{name}' is not a field a rule can match on.")


def compile_rule(rule, *, account_ids=None):
    """
    A `Rule` (or anything with its attributes) ready for matching.

    `account_ids` overrides reading `rule.accounts` -- for an unsaved draft, or
    when the caller has already loaded them. Raises ConditionError.
    """
    if account_ids is None:
        account_ids = [a.pk for a in rule.accounts.all()]
    return CompiledRule(
        id=rule.pk,
        priority=rule.priority,
        direction=rule.direction,
        account_ids=frozenset(account_ids),
        match=rule.match,
        conditions=tuple(compile_condition(c) for c in (rule.conditions or ())),
        rule=rule,
    )


def ordered(compiled):
    return sorted(compiled, key=lambda c: c.sort_key)


def _text(tx, name):
    return normalize((tx.merchant_name if name == FIELD_PAYEE else tx.description) or "")


def condition_holds(tx, condition):
    if condition.field == FIELD_AMOUNT:
        amount = abs(tx.amount)
        if condition.op == OP_EQUALS:
            return amount == condition.value
        if condition.op == OP_GT:
            return amount > condition.value
        if condition.op == OP_LT:
            return amount < condition.value
        low, high = condition.value
        return low <= amount <= high
    text = _text(tx, condition.field)
    if condition.op == OP_CONTAINS:
        return condition.value in text
    if condition.op == OP_NOT_CONTAINS:
        return condition.value not in text
    return text == condition.value


def direction_holds(tx, direction):
    if direction == DIRECTION_OUT:
        return tx.amount > 0
    if direction == DIRECTION_IN:
        return tx.amount < 0
    return True


def account_holds(tx, account_ids):
    return not account_ids or tx.account_id in account_ids


def matches(tx, compiled):
    if not direction_holds(tx, compiled.direction) or not account_holds(tx, compiled.account_ids):
        return False
    if not compiled.conditions:
        return True
    results = (condition_holds(tx, c) for c in compiled.conditions)
    return any(results) if compiled.match == MATCH_ANY else all(results)


def first_match(tx, compiled_in_order):
    """The first rule (already in `ordered` order) that matches `tx`, or None."""
    for compiled in compiled_in_order:
        if matches(tx, compiled):
            return compiled
    return None


def explain(tx, compiled):
    """Each part of the rule, and whether `tx` passes it -- for "why didn't it match?"."""
    conditions = [
        {"field": c.field, "op": c.op, "value": c.raw, "passed": condition_holds(tx, c)} for c in compiled.conditions
    ]
    return {
        "matched": matches(tx, compiled),
        "direction": {"value": compiled.direction, "passed": direction_holds(tx, compiled.direction)},
        "accounts": {"value": sorted(compiled.account_ids), "passed": account_holds(tx, compiled.account_ids)},
        "match": compiled.match,
        "conditions": conditions,
    }


def specificity(conditions, account_ids, direction):
    """How narrow a rule is: new rules go above broader ones (plan §9.3)."""
    return len(conditions or ()) + (1 if account_ids else 0) + (1 if direction != DIRECTION_ANY else 0)
