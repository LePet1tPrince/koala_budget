"""
The ordered list of categorization providers, and what comes out of it.

`settings.CATEGORIZATION_PROVIDERS` names the providers, strongest first:
rules, then history; an AI provider is appended after them. Two entry points:

- `suggest(book, rows)`  -- merged, deduped suggestions per row, for
  categorize mode (`similar_categories`). Never writes.
- `categorize_on_arrival(book, rows, trigger)` -- files the rows `policy.py`
  allows to be filed automatically (an `auto` rule, today), for the Plaid sync
  and the CSV upload. Never raises.
"""

import logging
from functools import lru_cache

from django.conf import settings
from django.utils.module_loading import import_string

from apps.bank_feed.services.similar_transactions import DEFAULT_LIMIT

from . import policy
from .providers.base import ProviderContext

logger = logging.getLogger(__name__)

DEFAULT_PROVIDERS = (
    "apps.categorization.providers.rules.RuleProvider",
    "apps.categorization.providers.history.HistoryProvider",
)

TRIGGER_PLAID = "plaid_sync"
TRIGGER_CSV = "csv_upload"
TRIGGER_APPLY_EXISTING = "apply_existing"


@lru_cache(maxsize=8)
def _load(paths):
    return tuple(import_string(path)() for path in paths)


def get_providers():
    """The registered providers, instantiated, in order."""
    return _load(tuple(getattr(settings, "CATEGORIZATION_PROVIDERS", DEFAULT_PROVIDERS)))


def _run(context, rows, providers):
    """`{row id: [(provider, suggestion), ...]}` merged and deduped, strongest first."""
    rows = list(rows)
    raw = []
    for provider in providers:
        try:
            raw.append((provider, provider.suggest(context, rows) or {}))
        except Exception:
            # One provider failing (an AI timeout, say) must not take the others
            # down with it: its suggestions are simply missing.
            logger.exception("Categorization provider %s failed", getattr(provider, "key", provider))

    merged = {}
    allowed = None
    for row in rows:
        seen = {}
        ordered = []
        for provider, results in raw:
            for suggestion in results.get(row.id, ()):
                if allowed is None:
                    allowed = context.allowed_category_ids
                # Anything a picker wouldn't offer, and the row's own account (a
                # transfer to itself), is dropped whoever suggested it.
                if suggestion.category_id not in allowed or suggestion.category_id == row.account_id:
                    continue
                earlier = seen.get(suggestion.category_id)
                if earlier is not None:
                    # A later provider's evidence for a category an earlier one
                    # already put forward: fold it in rather than list it twice.
                    if earlier.count is None and suggestion.count is not None:
                        earlier.count = suggestion.count
                    if not earlier.payee and suggestion.payee:
                        earlier.payee = suggestion.payee
                    continue
                seen[suggestion.category_id] = suggestion
                ordered.append((provider, suggestion))
        if ordered:
            merged[row.id] = ordered
    return merged


def suggest(book, rows, limit=DEFAULT_LIMIT):
    """`{row id: [Suggestion, ...]}`, at most `limit` per row (a rule always counts towards it first)."""
    merged = _run(ProviderContext(book), rows, get_providers())
    result = {row_id: [s for _p, s in pairs[:limit]] for row_id, pairs in merged.items()}
    _fill_names(book, result)
    return result


def _fill_names(book, result):
    """A provider may name a category by id alone; the UI contract carries its name too."""
    from apps.accounts.models import Account

    missing = {s.category_id for suggestions in result.values() for s in suggestions if not s.category_name}
    if not missing:
        return
    names = dict(Account.objects.filter(book=book, id__in=missing).values_list("id", "name"))
    for suggestions in result.values():
        for s in suggestions:
            if not s.category_name:
                s.category_name = names.get(s.category_id, "")


def auto_suggestions(book, rows):
    """`[(row, suggestion)]` for every row whose top suggestion policy lets file the row."""
    providers = [p for p in get_providers() if policy.provider_may_auto(book, p)]
    if not providers:
        return []
    rows = list(rows)
    merged = _run(ProviderContext(book), rows, providers)
    chosen = []
    for row in rows:
        pairs = merged.get(row.id)
        if not pairs:
            continue
        provider, top = pairs[0]
        if policy.may_auto_apply(book, provider, top):
            chosen.append((row, top))
    return chosen


def categorize_on_arrival(book, rows, trigger):
    """
    File the new rows an auto rule (or, one day, an allowed provider) decides.

    Called after the rows are committed. Never raises: categorization is a
    convenience on top of an import, and a failure here must not fail the
    import or send a Plaid sync into Celery's retry loop. Returns the
    `apply.ApplyResult`, or None if something unexpected went wrong.
    """
    from .apply import apply_suggestions, eligible_rows

    try:
        ids = [row.id for row in rows]
        if not ids:
            return None
        fresh = list(eligible_rows(book).filter(id__in=ids).select_related("account"))
        if not fresh:
            return None
        chosen = auto_suggestions(book, fresh)
        if not chosen:
            return None
        return apply_suggestions(book, chosen, trigger=trigger)
    except Exception:
        logger.exception("Automatic categorization failed for %s (%s rows)", trigger, len(rows))
        return None
