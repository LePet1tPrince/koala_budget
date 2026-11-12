"""
Run a book's rules over its uncategorized feed rows. The one place rules are applied.

For each eligible row (`eligible`), the winning rule (`engine.first_match`)
either posts the categorization (an auto-post rule, unless a hold applies) or
records a suggestion. Either way the row gets a `RuleMatch`, and the rule's
payee/description renames are applied at once (they are cosmetic and undoable:
`RuleMatch.before` keeps the originals).

Re-running is idempotent: a row is matched against its *original* payee and
description, so a rename never changes which rule wins, and a row no rule wins
any more gets its originals back.

Callers: Plaid sync and CSV import (new rows), and every rule change (all rows,
`allow_auto_post=False`: editing a rule never posts retroactively unless the
user asks, via `auto_post_rule_ids`). Nothing raised here may fail a sync, so a
guard's refusal on one row becomes a held suggestion and anything unexpected is
logged and skipped.
"""

import logging
import statistics
from types import SimpleNamespace

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.bank_feed.models import BankTransaction, VoidRowError
from apps.bank_feed.services.bank_revision import REVISION_OF
from apps.bank_feed.services.splits import SplitError
from apps.journal.services import period_lock
from apps.reconciliation.services.guards import ReconciledLineError

from .. import constants
from ..models import Rule, RuleMatch
from . import actions, engine

logger = logging.getLogger(__name__)

# Only rows a bank reported are a rule's business: a manual row was typed by the
# user, a system row is the app's own, and an imported YNAB row is history.
RULE_SOURCES = (BankTransaction.SOURCE_PLAID, BankTransaction.SOURCE_CSV)

GUARD_ERRORS = (period_lock.PeriodLockedError, ReconciledLineError, SplitError, VoidRowError, ValueError)


def eligible(book, ids=None):
    """Uncategorized bank-reported rows no settled match has claimed (plan §5.3)."""
    rows = (
        BankTransaction.objects.filter(
            book=book,
            journal_entry__isnull=True,
            is_void=False,
            is_transfer_mirror=False,
            source__in=RULE_SOURCES,
        )
        .exclude(raw__has_key=REVISION_OF)
        .exclude(rule_match__status__in=RuleMatch.SETTLED)
        .select_related("account", "rule_match")
    )
    if ids is not None:
        rows = rows.filter(pk__in=list(ids))
    return rows


class RuleSet:
    """A book's usable rules, compiled and in priority order, plus what posting needs."""

    def __init__(self, book, rules=None):
        self.book = book
        self.accounts_by_id = actions.book_accounts(book)
        if rules is None:
            rules = list(
                Rule.objects.filter(book=book, is_active=True).prefetch_related("accounts").order_by("priority", "id")
            )
        compiled = []
        for rule in rules:
            if actions.problem(rule, self.accounts_by_id):
                continue
            try:
                compiled.append(engine.compile_rule(rule))
            except engine.ConditionError:
                continue
        self.compiled = engine.ordered(compiled)
        self._samples = {}
        self._transfer_ids = None

    def first_match(self, tx):
        hit = engine.first_match(tx, self.compiled)
        return hit.rule if hit else None

    def transfer_ids(self):
        if self._transfer_ids is None:
            from apps.bank_feed.services.feed_query import transfer_candidate_ids

            self._transfer_ids = transfer_candidate_ids(self.book)
        return self._transfer_ids

    def samples(self, rule):
        """Absolute amounts the rule has posted or had confirmed (the anomaly guard's baseline)."""
        if rule.pk not in self._samples:
            amounts = RuleMatch.objects.filter(
                rule=rule, status__in=(RuleMatch.STATUS_CONFIRMED, RuleMatch.STATUS_AUTO_POSTED)
            ).values_list("transaction__amount", flat=True)
            self._samples[rule.pk] = [abs(a) for a in amounts]
        return self._samples[rule.pk]


def is_unusual(amount, samples):
    """The anomaly guard (plan §9.5): far above what this rule usually sees."""
    if len(samples) < constants.ANOMALY_MIN_SAMPLES:
        return False
    return abs(amount) > constants.ANOMALY_MULTIPLE * statistics.median(samples)


def hold_reason(tx, rule, ruleset):
    """Why an auto-post rule's match must only be suggested, or "" (plan §6.4)."""
    if rule.action == Rule.ACTION_CATEGORY and ruleset.accounts_by_id[rule.category_id].has_feed:
        # Validation refuses this; a transfer is never posted by a rule regardless.
        return RuleMatch.HELD_REFUSED
    if period_lock.is_locked(ruleset.book, tx.posted_date):
        return RuleMatch.HELD_CLOSED_PERIOD
    if is_unusual(tx.amount, ruleset.samples(rule)):
        return RuleMatch.HELD_UNUSUAL_AMOUNT
    if tx.pk in ruleset.transfer_ids():
        return RuleMatch.HELD_TRANSFER_CANDIDATE
    return RuleMatch.HELD_NONE


def original_view(tx):
    """`tx` as the bank reported it -- before any rule renamed it -- for matching."""
    merchant_name, description = _originals(tx, _match_of(tx))
    return SimpleNamespace(
        pk=tx.pk,
        amount=tx.amount,
        account_id=tx.account_id,
        posted_date=tx.posted_date,
        merchant_name=merchant_name,
        description=description,
    )


def _originals(tx, existing):
    if existing is not None and existing.before:
        return existing.before.get("merchant_name"), existing.before.get("description", tx.description)
    return tx.merchant_name, tx.description


def _set_names(tx, merchant_name, description):
    changed = []
    if tx.merchant_name != merchant_name:
        tx.merchant_name = merchant_name
        changed.append("merchant_name")
    if tx.description != description:
        tx.description = description
        changed.append("description")
    if changed:
        tx.save(update_fields=[*changed, "updated_at"])


def apply_one(tx, ruleset, *, allow_auto_post=True, auto_post_rule_ids=None):
    """
    Match one eligible row and record the outcome. Returns the `RuleMatch`, or
    None when no rule matches. Runs inside the caller's savepoint.
    """
    existing = _match_of(tx)
    if existing is not None and existing.status != RuleMatch.STATUS_SUGGESTED:
        return existing
    merchant_name, description = _originals(tx, existing)
    rule = ruleset.first_match(original_view(tx))

    if rule is None:
        if existing is not None:
            _set_names(tx, merchant_name, description)
            existing.delete()
        return None

    _set_names(tx, rule.payee_name or merchant_name, rule.description or description)
    legs = actions.legs_for(rule, tx.amount, ruleset.accounts_by_id)

    match = existing or RuleMatch(book=ruleset.book, transaction=tx)
    match.rule = rule
    match.rule_name = rule.name
    match.before = {"merchant_name": merchant_name, "description": description}
    match.category = legs[0][0] if len(legs) == 1 else None
    match.splits = actions.serialize_legs(legs) if len(legs) > 1 else None
    match.payee_name = rule.payee_name
    match.status = RuleMatch.STATUS_SUGGESTED
    match.held_reason = RuleMatch.HELD_NONE

    may_post = (
        allow_auto_post
        and rule.mode == Rule.MODE_AUTO_POST
        and legs
        and (auto_post_rule_ids is None or rule.pk in auto_post_rule_ids)
    )
    if may_post:
        held = hold_reason(tx, rule, ruleset)
        if not held:
            try:
                with transaction.atomic():
                    actions.post(tx, legs, payee_name=rule.payee_name, description=rule.description)
            except GUARD_ERRORS:
                held = RuleMatch.HELD_REFUSED
                tx.refresh_from_db()
            else:
                match.status = RuleMatch.STATUS_AUTO_POSTED
                match.was_auto_posted = True
                Rule.objects.filter(pk=rule.pk).update(times_applied=F("times_applied") + 1)
                ruleset.samples(rule).append(abs(tx.amount))
        match.held_reason = held
    match.save()
    return match


def run(book, transactions=None, *, allow_auto_post=True, auto_post_rule_ids=None, ruleset=None):
    """
    Apply `book`'s rules to `transactions` (ids or rows; None = every eligible row).

    Returns `{"suggested": n, "auto_posted": n, "cleared": n}`. Never raises for
    one row's sake: a row that fails is logged and left as it was.
    """
    ruleset = ruleset or RuleSet(book)
    ids = None
    if transactions is not None:
        ids = [getattr(t, "pk", t) for t in transactions]
        if not ids:
            return {"suggested": 0, "auto_posted": 0, "cleared": 0}
    rows = list(eligible(book, ids))
    counts = {"suggested": 0, "auto_posted": 0, "cleared": 0}
    matched_rule_ids = set()
    posted = {}
    for tx in rows:
        had_match = _match_of(tx) is not None
        try:
            with transaction.atomic():
                match = apply_one(tx, ruleset, allow_auto_post=allow_auto_post, auto_post_rule_ids=auto_post_rule_ids)
        except Exception:
            logger.exception("Rules: could not apply to feed row %s", tx.pk)
            continue
        if match is None:
            if had_match:
                counts["cleared"] += 1
            continue
        matched_rule_ids.add(match.rule_id)
        if match.status == RuleMatch.STATUS_AUTO_POSTED:
            counts["auto_posted"] += 1
            posted[match.rule_id] = posted.get(match.rule_id, 0) + 1
        else:
            counts["suggested"] += 1

    if matched_rule_ids:
        Rule.objects.filter(pk__in=matched_rule_ids).update(last_matched_at=timezone.now())
    if posted:
        from apps.audit.models import AuditEvent
        from apps.audit.utils import log_event

        log_event(
            AuditEvent.RULE_AUTO_POSTED,
            book=book,
            metadata={"rules": {str(k): v for k, v in posted.items()}, "count": sum(posted.values())},
        )
    return counts


def _match_of(tx):
    # A reverse one-to-one raises when there is no row; its error is also an AttributeError.
    return getattr(tx, "rule_match", None)


def run_safely(book, transactions=None, **kwargs):
    """`run` for ingestion: a failure is logged, never raised into the import that called it."""
    try:
        return run(book, transactions, **kwargs)
    except Exception:
        logger.exception("Rules: run failed for book %s", getattr(book, "pk", book))
        return None


def refresh(book):
    """After a rule changes: re-evaluate every eligible row, suggesting only."""
    return run(book, allow_auto_post=False)


def pending_matches(book):
    """Suggested matches on rows still uncategorized (the feed's suggestion chips)."""
    return RuleMatch.objects.filter(
        book=book, status=RuleMatch.STATUS_SUGGESTED, transaction__journal_entry__isnull=True
    ).filter(Q(transaction__is_void=False))
