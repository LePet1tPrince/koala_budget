"""
The categorization provider contract. See `docs/categorization-rules-plan.md` §8, §10.

A provider looks at a batch of uncategorized bank rows and says, per row, which
categories it thinks they are -- with a confidence and a one-sentence reason.
Providers never write: `pipeline.py` merges what they say, `policy.py` decides
whether any of it may file a row by itself, and `apply.py` does the filing
through the bank feed's own write path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Protocol, runtime_checkable


@dataclass
class Suggestion:
    """One provider's view that one row is one category."""

    category_id: int
    source: str  # "rule" | "history" | "ai": recorded on every decision this files
    provider: str  # the provider's `key`
    confidence: float  # 0..1
    reason: str  # one user-facing sentence
    # The provider asks to file the row itself. Only a rule in `auto` mode sets
    # it today; `policy.may_auto_apply` has the last word whatever it says.
    auto: bool = False
    category_name: str = ""  # filled in by the pipeline when a provider leaves it blank
    rule_id: int | None = None
    rule_name: str = ""
    # History's evidence, for the UI's "N×" and its note. None = no history.
    count: int | None = None
    # The UI contract (`similar_categories`): payee | description | similar | rule | ai.
    match_type: str = ""
    payee: str = ""
    # Decisions beyond the category, keyed as in `actions.ACTIONS` ("payee",
    # "description"); room for a business flag or a tax code later.
    decisions: dict = field(default_factory=dict)

    def as_payload(self, transaction_id) -> dict:
        return {
            "transaction_id": transaction_id,
            "category_id": self.category_id,
            "category_name": self.category_name,
            "count": self.count,
            "match_type": self.match_type or self.source,
            "payee": self.payee,
            "source": self.source,
            "provider": self.provider,
            "confidence": round(float(self.confidence), 3),
            "reason": self.reason,
            "auto": self.auto,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "decisions": dict(self.decisions),
        }


class ProviderContext:
    """
    What every provider is handed besides the rows: the book, and -- lazily, so a
    provider that doesn't need it costs nothing -- the book's pickable categories
    in the shape the pickers show them (`picker_accounts_data`).
    """

    def __init__(self, book):
        self.book = book

    @cached_property
    def categories(self) -> list[dict]:
        from apps.budget.services import picker_accounts_data

        return list(picker_accounts_data(self.book))

    @cached_property
    def allowed_category_ids(self) -> frozenset:
        """
        Accounts a suggestion may name: anything a picker offers that is not
        archived. A row's own account is excluded per row by the pipeline.
        """
        from apps.accounts.models import Account

        return frozenset(
            Account.objects.filter(book=self.book, is_archived=False)
            .exclude_budget_buckets()
            .values_list("id", flat=True)
        )


@runtime_checkable
class CategorizationProvider(Protocol):
    """
    Implement these four attributes and register the class's dotted path in
    `settings.CATEGORIZATION_PROVIDERS`.
    """

    key: str  # unique, short: "rules", "history", "ai"
    source: str  # the Suggestion.source it produces
    can_auto_apply: bool  # may its results ever file a row? (still gated by policy.py)

    def suggest(self, context: ProviderContext, rows) -> dict[int, list[Suggestion]]:
        """`{row id: [Suggestion, ...]}`, strongest first; omit rows with nothing."""
        ...
