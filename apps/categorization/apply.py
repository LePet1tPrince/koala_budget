"""
Filing rows from suggestions -- the only writer in this app.

Every row goes through the bank feed's own write path
(`apps.bank_feed.services.categorize.categorize_single`), so every guard it runs
(budget accounts, reconciliation, void rows, any period lock added there later),
the transfer mirror and the audit signals all apply exactly as they do to a
row the user files by hand. Lines are never written here.

Each row is filed in its own savepoint and a refusal (any `ValueError` the write
path raises, or a `ValidationError`) is reported for that row alone: one
transaction that can't be filed never stops the rest.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.guards import assert_category_allowed
from apps.accounts.models import Account
from apps.audit.models import AuditEvent, AuditLog
from apps.audit.utils import log_event
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.categorize import categorize_single
from apps.bank_feed.services.similar_transactions import HISTORY_LIMIT
from apps.journal.models import counted_entries

from .actions import apply_after, apply_before
from .matching import compile_rule
from .models import (
    DIRECTION_INFLOW,
    DIRECTION_OUTFLOW,
    SOURCE_RULE,
    CategorizationDecision,
)

logger = logging.getLogger(__name__)

# How many row ids an audit event lists; the count is always exact.
AUDIT_ID_LIMIT = 200
PREVIEW_SAMPLE = 10


@dataclass
class ApplyResult:
    categorized: list = field(default_factory=list)  # [(row id, Suggestion)]
    refused: list = field(default_factory=list)  # [{"id", "error"}]
    skipped: list = field(default_factory=list)  # [{"id", "reason"}]

    @property
    def categorized_count(self):
        return len(self.categorized)

    def as_dict(self):
        return {
            "categorized": len(self.categorized),
            "categorized_ids": [row_id for row_id, _s in self.categorized],
            "refused": self.refused,
            "skipped": self.skipped,
        }


def eligible_rows(book):
    """
    Rows a provider may file: uncategorized, not void, not a transfer's mirror leg.

    A row with an entry -- categorized, split, either leg of a transfer -- is a
    decision already made, and is never touched.
    """
    return BankTransaction.objects.filter(
        book=book,
        journal_entry__isnull=True,
        is_void=False,
        is_transfer_mirror=False,
    )


def skip_reason(row, suggestion):
    if row.journal_entry_id:
        return _("Already categorized")
    if row.is_void:
        return _("Void")
    if row.is_transfer_mirror:
        return _("The other side of a transfer")
    if suggestion.category_id == row.account_id:
        return _("Its category is the account it is in")
    return None


def file_row(row, suggestion):
    """
    File one row the way `suggestion` says, inside the caller's savepoint.

    Re-reads the row under a lock so a row the user filed a moment ago is skipped
    rather than filed twice. Raises ValueError (or ValidationError) on a refusal.
    """
    row = BankTransaction.objects.select_for_update().select_related("account", "book").get(pk=row.pk)
    reason = skip_reason(row, suggestion)
    if reason:
        raise SkipRow(reason)

    category = Account.objects.select_related("account_group").filter(book=row.book, pk=suggestion.category_id).first()
    if category is None:
        raise ValueError(_("That category no longer exists."))
    if category.is_archived:
        raise ValueError(_("“%(name)s” is archived.") % {"name": category.name})
    assert_category_allowed(category)

    original_payee = row.merchant_name or ""
    original_description = row.description or ""
    if apply_before(row, suggestion.decisions):
        row.save()

    entry = categorize_single(row, category)
    apply_after(row, entry, suggestion.decisions)

    CategorizationDecision.objects.update_or_create(
        bank_transaction=row,
        defaults={
            "book": row.book,
            "journal_entry": entry,
            "category": category,
            "source": suggestion.source,
            "provider": suggestion.provider,
            "rule_id": suggestion.rule_id,
            "confidence": Decimal(str(round(float(suggestion.confidence), 3))),
            "reason": (suggestion.reason or "")[:500],
            "original_payee": original_payee[:255],
            "original_description": original_description[:255],
        },
    )
    return entry


class SkipRow(Exception):
    """Not a refusal: the row is no longer one a provider may file."""


def apply_suggestions(book, pairs, trigger, user=None) -> ApplyResult:
    """
    File each `(row, suggestion)` pair, row by row, and record what happened.

    One `AUTO_CATEGORIZED` audit event per rule (or per provider, for anything
    that isn't a rule), and the field-diff `AuditLog` rows those writes created
    are linked to it so a transaction's History tab can say "via rule …".
    """
    result = ApplyResult()
    started = timezone.now()
    entries_by_group = {}

    for row, suggestion in pairs:
        reason = skip_reason(row, suggestion)
        if reason:
            result.skipped.append({"id": row.id, "reason": str(reason)})
            continue
        try:
            with transaction.atomic():
                entry = file_row(row, suggestion)
        except SkipRow as skip:
            result.skipped.append({"id": row.id, "reason": str(skip)})
            continue
        except (ValueError, ValidationError) as error:
            message = "; ".join(error.messages) if isinstance(error, ValidationError) else str(error)
            logger.info("Automatic categorization refused for bank transaction %s: %s", row.id, message)
            result.refused.append({"id": row.id, "error": message})
            continue
        result.categorized.append((row.id, suggestion))
        group = (suggestion.source, suggestion.provider, suggestion.rule_id)
        entries_by_group.setdefault(group, {"suggestion": suggestion, "rows": [], "entries": []})
        entries_by_group[group]["rows"].append(row.id)
        entries_by_group[group]["entries"].append(entry.id)

    for (source, provider, rule_id), group in entries_by_group.items():
        suggestion = group["suggestion"]
        via = (
            _("rule “%(name)s”") % {"name": suggestion.rule_name}
            if source == SOURCE_RULE
            else _("%(provider)s suggestion") % {"provider": provider}
        )
        event = log_event(
            AuditEvent.AUTO_CATEGORIZED,
            user=user,
            book=book,
            metadata={
                "source": source,
                "provider": provider,
                "rule_id": rule_id,
                "rule_name": suggestion.rule_name,
                "trigger": trigger,
                "count": len(group["rows"]),
                "transaction_ids": group["rows"][:AUDIT_ID_LIMIT],
                "via": str(via),
            },
        )
        AuditLog.objects.filter(
            journal_entry_id__in=group["entries"], event__isnull=True, timestamp__gte=started
        ).update(event=event)

    return result


# --- A single rule, on demand ------------------------------------------------


def _prefiltered(queryset, rule):
    """Narrow in the database by what SQL can see (account, direction, amount); text is matched in Python."""
    if rule.account_id:
        queryset = queryset.filter(account_id=rule.account_id)
    if rule.direction == DIRECTION_OUTFLOW:
        queryset = queryset.filter(amount__gt=0)
    elif rule.direction == DIRECTION_INFLOW:
        queryset = queryset.filter(amount__lt=0)
    low, high = rule.amount_min, rule.amount_max
    if low is not None or high is not None:
        out = Q(amount__gte=0)
        into = Q(amount__lte=0)
        if low is not None:
            out &= Q(amount__gte=low)
            into &= Q(amount__lte=-low)
        if high is not None:
            out &= Q(amount__lte=high)
            into &= Q(amount__gte=-high)
        queryset = queryset.filter(out | into)
    return queryset


def matching_uncategorized(book, rule):
    """The uncategorized rows `rule` would file now, newest first. Raises RuleConditionError."""
    compiled = compile_rule(rule)
    rows = _prefiltered(eligible_rows(book), rule).select_related("account").order_by("-posted_date", "-id")
    return [row for row in rows if compiled.matches(row) and row.account_id != rule.category_id]


def _category_of(tx):
    lines = [line for line in tx.journal_entry.lines.all() if line.account_id != tx.account_id]
    return lines[0].account_id if len(lines) == 1 else None


def preview(book, rule, sample_size=PREVIEW_SAMPLE) -> dict:
    """
    Test `rule` (saved or not) against the book: how many uncategorized rows it
    would file now, a sample of them, and -- as a sanity check on the conditions
    -- how many already-filed rows it matches and how many of those agree.
    """
    matching = matching_uncategorized(book, rule)
    compiled = compile_rule(rule)
    history = (
        _prefiltered(
            BankTransaction.objects.filter(
                book=book, journal_entry__isnull=False, is_void=False, is_transfer_mirror=False
            ).filter(counted_entries("journal_entry__")),
            rule,
        )
        .prefetch_related("journal_entry__lines")
        .order_by("-posted_date", "-id")[:HISTORY_LIMIT]
    )
    categorized = [tx for tx in history if compiled.matches(tx)]
    agreeing = sum(1 for tx in categorized if rule.category_id and _category_of(tx) == rule.category_id)
    return {
        "count": len(matching),
        "sample": [row_payload(row) for row in matching[:sample_size]],
        "categorized_count": len(categorized),
        "agreeing_count": agreeing,
    }


def row_payload(row) -> dict:
    return {
        "id": row.id,
        "posted_date": row.posted_date.isoformat(),
        "description": row.description,
        "payee": row.merchant_name or "",
        "amount": str(row.amount),
        "account_name": row.account.name if row.account_id else "",
    }


def apply_rule(rule, user=None) -> ApplyResult:
    """File every uncategorized row `rule` matches, whatever its mode or priority (the user asked)."""
    from .pipeline import TRIGGER_APPLY_EXISTING
    from .providers.rules import suggestion_for

    suggestion = suggestion_for(rule)
    pairs = [(row, suggestion) for row in matching_uncategorized(rule.book, rule)]
    return apply_suggestions(rule.book, pairs, trigger=TRIGGER_APPLY_EXISTING, user=user)
