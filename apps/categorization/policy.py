"""
When may a provider's suggestion file a transaction by itself?

1. Never, if the provider says it can't (`can_auto_apply = False`).
2. A rule may, when its mode is `auto` (`suggestion.auto`).
3. Any other provider (history, AI) only when the book has explicitly allowed it
   (`book_allows_auto`) *and* the suggestion is confident enough. The book-level
   switch does not exist yet, so today they only ever suggest.
"""

from django.conf import settings

from .models import SOURCE_RULE

DEFAULT_AUTO_MIN_CONFIDENCE = 0.9


def auto_min_confidence() -> float:
    return float(getattr(settings, "CATEGORIZATION_AUTO_MIN_CONFIDENCE", DEFAULT_AUTO_MIN_CONFIDENCE))


def book_allows_auto(book, provider) -> bool:
    """
    The hook for a per-book "let {provider} file transactions" setting.

    Off for every book and every non-rule provider until such a setting exists.
    When it does, read it here (e.g. a `Book` field or a per-provider row) --
    it should be an explicit opt-in, shown with the consequence, never a default.
    """
    return False


def provider_may_auto(book, provider) -> bool:
    """Could anything this provider says file a row in this book? (Arrival skips providers that can't.)"""
    if not getattr(provider, "can_auto_apply", False):
        return False
    if provider.source == SOURCE_RULE:
        return True
    return book_allows_auto(book, provider)


def may_auto_apply(book, provider, suggestion) -> bool:
    if not provider_may_auto(book, provider):
        return False
    if provider.source == SOURCE_RULE:
        return bool(suggestion.auto)
    return float(suggestion.confidence) >= auto_min_confidence()
