"""
What the user did with a rule's work, and what the rule learns from it.

`record` runs after every user categorization in the feed (categorize, edit,
batch edit, Categorize Mode): it compares the row's categorization now with what
its rule offered or posted, and marks the match confirmed or overridden. `accept`,
`dismiss` and `undo` are the explicit actions on a match.

From those outcomes: a suggest rule confirmed `GRADUATE_STREAK` times running is
offered auto-post (`graduation_offers`); an auto-post rule overridden
`DEMOTE_OVERRIDES` times in its last `DEMOTE_WINDOW` auto-posts is demoted to
suggest (`check_demotion`).
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.bank_feed.services import edit
from apps.bank_feed.services.transfer_mirror import sync_transfer

from .. import constants
from ..models import Rule, RuleMatch
from . import actions

OPEN = (RuleMatch.STATUS_SUGGESTED, RuleMatch.STATUS_AUTO_POSTED)


class MatchError(ValueError):
    """An action on a match that does not apply to it (accepting a posted one, undoing a suggestion)."""


def offered_legs(match):
    """`{(category id, amount)}` the match offered or posted; empty for a rename-only rule."""
    if match.splits:
        return {(int(leg["category"]), Decimal(leg["amount"])) for leg in match.splits}
    if match.category_id:
        return {(match.category_id, match.transaction.amount)}
    return set()


def current_legs(tx):
    """`{(category id, amount)}` of the row's categorization now; empty when uncategorized."""
    if not tx.journal_entry_id:
        return set()
    legs = set()
    for line in tx.journal_entry.lines.all():
        if line.account_id == tx.account_id:
            continue
        legs.add((line.account_id, line.dr_amount - line.cr_amount))
    if len(legs) == 1:
        # A single-category row is offered as (category, row amount): compare on that.
        ((category_id, _amount),) = legs
        return {(category_id, tx.amount)}
    return legs


def _bump(rule_id, **fields):
    Rule.objects.filter(pk=rule_id).update(**fields)


def _confirmed(match):
    match.status = RuleMatch.STATUS_CONFIRMED
    match.resolved_at = timezone.now()
    match.save(update_fields=["status", "resolved_at", "updated_at"])
    if match.rule_id:
        _bump(match.rule_id, times_confirmed=F("times_confirmed") + 1, confirm_streak=F("confirm_streak") + 1)


def _overridden(match):
    was_posted = match.status == RuleMatch.STATUS_AUTO_POSTED
    match.status = RuleMatch.STATUS_OVERRIDDEN
    match.resolved_at = timezone.now()
    match.save(update_fields=["status", "resolved_at", "updated_at"])
    if match.rule_id:
        _bump(match.rule_id, times_overridden=F("times_overridden") + 1, confirm_streak=0)
        if was_posted:
            check_demotion(match.rule_id)


def record(transactions):
    """
    After the user categorized (or re-categorized, or cleared) `transactions`:
    settle each one's open rule match. Returns `{"confirmed": n, "overridden": n}`.
    """
    ids = [getattr(t, "pk", t) for t in transactions]
    matches = (
        RuleMatch.objects.filter(transaction_id__in=ids, status__in=OPEN)
        .select_related("transaction__journal_entry")
        .prefetch_related("transaction__journal_entry__lines")
    )
    counts = {"confirmed": 0, "overridden": 0}
    for match in matches:
        tx = match.transaction
        now = current_legs(tx)
        if match.status == RuleMatch.STATUS_SUGGESTED and not now:
            continue  # still uncategorized: the suggestion stands
        offered = offered_legs(match)
        if not offered:
            # A rename-only rule offered no category: any categorization agrees with it.
            if now:
                _confirmed(match)
                counts["confirmed"] += 1
            continue
        if now == offered:
            if match.status == RuleMatch.STATUS_SUGGESTED:
                _confirmed(match)
                counts["confirmed"] += 1
            continue
        _overridden(match)
        counts["overridden"] += 1
    return counts


@transaction.atomic
def accept(match):
    """Post a suggestion as offered. Raises the feed's guard errors (period lock, void, reconciled)."""
    if match.status != RuleMatch.STATUS_SUGGESTED:
        raise MatchError("This suggestion has already been resolved.")
    tx = match.transaction
    if tx.journal_entry_id:
        raise MatchError("This transaction is already categorized.")
    if match.splits or match.category_id:
        accounts = actions.book_accounts(match.book)
        if match.splits:
            legs = actions.deserialize_legs(match.splits, accounts)
        else:
            legs = [(accounts[match.category_id], tx.amount)]
        # Renames were applied when the rule matched; the entry takes the row's current names.
        actions.post(tx, legs, payee_name=match.payee_name)
    _confirmed(match)


@transaction.atomic
def dismiss(match):
    """Decline a suggestion: the row gets its original names back and the rule leaves it alone."""
    if match.status != RuleMatch.STATUS_SUGGESTED:
        raise MatchError("Only a suggestion can be dismissed.")
    tx = match.transaction
    _restore_names(tx, match)
    match.status = RuleMatch.STATUS_DISMISSED
    match.resolved_at = timezone.now()
    match.save(update_fields=["status", "resolved_at", "updated_at"])
    if match.rule_id:
        _bump(match.rule_id, confirm_streak=0)


@transaction.atomic
def undo(match):
    """
    Take back an auto-post: the row is uncategorized again, with its original
    names. Raises the reconciled-line and period-lock guards' errors.
    """
    if match.status != RuleMatch.STATUS_AUTO_POSTED:
        raise MatchError("Only an auto-posted transaction can be undone.")
    tx = match.transaction
    if tx.journal_entry_id:
        edit.decategorize(tx)
    _restore_names(tx, match)
    _overridden(match)


def _restore_names(tx, match):
    before = match.before or {}
    fields = []
    if "merchant_name" in before and tx.merchant_name != before["merchant_name"]:
        tx.merchant_name = before["merchant_name"]
        fields.append("merchant_name")
    if "description" in before and tx.description != before["description"]:
        tx.description = before["description"]
        fields.append("description")
    if fields:
        tx.save(update_fields=[*fields, "updated_at"])
        if tx.journal_entry_id:
            sync_transfer(tx)


def check_demotion(rule_id):
    """Demote an auto-post rule overridden too often lately. Returns True when it was demoted."""
    rule = Rule.objects.filter(pk=rule_id).first()
    if rule is None or rule.mode != Rule.MODE_AUTO_POST:
        return False
    recent = list(
        RuleMatch.objects.filter(rule=rule, was_auto_posted=True)
        .order_by("-created_at", "-id")
        .values_list("status", flat=True)[: constants.DEMOTE_WINDOW]
    )
    if recent.count(RuleMatch.STATUS_OVERRIDDEN) < constants.DEMOTE_OVERRIDES:
        return False
    rule.mode = Rule.MODE_SUGGEST
    rule.demoted_at = timezone.now()
    rule.save(update_fields=["mode", "demoted_at", "updated_at"])
    log_event(AuditEvent.RULE_DEMOTED, book=rule.book, metadata={"rule_id": rule.pk, "name": rule.name})
    return True


def graduation_offers(book):
    """Suggest rules confirmed often enough, unchanged, to be offered auto-post (plan §9.4)."""
    rules = Rule.objects.filter(
        book=book,
        is_active=True,
        mode=Rule.MODE_SUGGEST,
        confirm_streak__gte=constants.GRADUATE_STREAK,
        graduation_declined_at__isnull=True,
    ).exclude(action=Rule.ACTION_RENAME)
    # A transfer is never auto-posted, so never offered.
    return [r for r in rules.select_related("category") if not (r.category and r.category.has_feed)]
