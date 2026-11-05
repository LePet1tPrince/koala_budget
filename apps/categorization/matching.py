"""
Does a rule match a bank row? Pure: no queries, no writes.

Text is compared through the history matcher's own normaliser and tokeniser
(`similar_transactions.normalize` / `signature_tokens`), so "the same payee"
means one thing across the app -- a rule and a history suggestion never
disagree about whether "BLUE-BOTTLE coffee" is "Blue Bottle Coffee".

A rule is compiled once (`compile_rule`) and tested against many rows; an
unsaved rule (the editor's live preview) compiles the same way.
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.bank_feed.services.similar_transactions import normalize, signature_tokens

from .models import (
    DIRECTION_INFLOW,
    DIRECTION_OUTFLOW,
    MATCH_ANY,
    MATCH_CONTAINS,
    MATCH_EQUALS,
    MATCH_WORDS,
)


class RuleConditionError(ValueError):
    """A rule whose conditions cannot match anything sensible. The message is user-facing."""


@dataclass(frozen=True)
class TextCondition:
    kind: str
    key: str  # normalized value
    tokens: frozenset

    def matches(self, text) -> bool:
        if self.kind == MATCH_ANY:
            return True
        if self.kind == MATCH_EQUALS:
            return normalize(text) == self.key
        if self.kind == MATCH_CONTAINS:
            # On word boundaries: "bottle" is in "sq blue bottle 4417", "bot" is not.
            return f" {self.key} " in f" {normalize(text)} "
        if self.kind == MATCH_WORDS:
            return self.tokens <= signature_tokens(text or "")
        return False


def text_condition(kind, value) -> TextCondition:
    kind = kind or MATCH_ANY
    if kind == MATCH_ANY:
        return TextCondition(MATCH_ANY, "", frozenset())
    key = normalize(value)
    tokens = frozenset(signature_tokens(value or ""))
    if kind == MATCH_WORDS and not tokens:
        # Every word was a number, too short or bank boilerplate: "has the words"
        # would then match every transaction.
        raise RuleConditionError(
            "None of those words is distinctive enough to match on (numbers, short words and words like "
            "“card” or “payment” are ignored). Use “is” or “contains” instead."
        )
    if not key:
        raise RuleConditionError("Enter the text to match.")
    return TextCondition(kind, key, tokens)


@dataclass(frozen=True)
class CompiledRule:
    rule: object
    payee: TextCondition
    description: TextCondition
    amount_min: Decimal | None
    amount_max: Decimal | None
    direction: str
    account_id: int | None

    def matches(self, row) -> bool:
        """`row` is a `BankTransaction` (or anything with its attributes)."""
        if self.account_id is not None and row.account_id != self.account_id:
            return False
        amount = row.amount or Decimal("0")
        # Plaid convention: positive = money out.
        if self.direction == DIRECTION_OUTFLOW and amount <= 0:
            return False
        if self.direction == DIRECTION_INFLOW and amount >= 0:
            return False
        magnitude = abs(amount)
        if self.amount_min is not None and magnitude < self.amount_min:
            return False
        if self.amount_max is not None and magnitude > self.amount_max:
            return False
        return self.payee.matches(row.merchant_name) and self.description.matches(row.description)


def compile_rule(rule) -> CompiledRule:
    """
    Compile `rule`'s conditions, or raise `RuleConditionError`.

    At least one of payee, description or amount must be set: an account or a
    direction alone would file every transaction in the account.
    """
    payee = text_condition(rule.payee_match, rule.payee_value)
    description = text_condition(rule.description_match, rule.description_value)
    amount_min = rule.amount_min
    amount_max = rule.amount_max
    if (amount_min is not None and amount_min < 0) or (amount_max is not None and amount_max < 0):
        raise RuleConditionError("Amounts are matched on their size: enter them without a minus sign.")
    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        raise RuleConditionError("The smallest amount is larger than the largest.")
    if payee.kind == MATCH_ANY and description.kind == MATCH_ANY and amount_min is None and amount_max is None:
        raise RuleConditionError("Add a payee, description or amount to match on.")
    return CompiledRule(
        rule=rule,
        payee=payee,
        description=description,
        amount_min=amount_min,
        amount_max=amount_max,
        direction=rule.direction,
        account_id=rule.account_id,
    )


def compile_rules(rules):
    """Compile every rule that compiles, in the order given; a broken one is skipped."""
    compiled = []
    for rule in rules:
        try:
            compiled.append(compile_rule(rule))
        except RuleConditionError:
            continue
    return compiled


def first_match(compiled_rules, row):
    """The first compiled rule (priority order) matching `row`, or None."""
    for compiled in compiled_rules:
        if compiled.matches(row):
            return compiled
    return None
