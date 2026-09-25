"""
Everything that writes a reconciliation.

A draft's ticks are `JournalLine.reconciliation` pointing at it with
`is_reconciled` still False, so ticking is a cheap `UPDATE` with no audit row --
a tick is not history. Finishing is the moment of record: each line is flipped
with its own `save()` so `AuditLog` captures every one, the same choice the
feed made for archiving.
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.bank_feed.models import BankTransaction
from apps.journal.models import JournalEntry

from ..models import Reconciliation
from . import candidates
from .adjustment import create_adjustment
from .signs import is_reconcilable, to_ledger, to_statement


class ReconciliationError(ValueError):
    """Something the user needs told. The message is user-facing."""


class StaleDifference(ReconciliationError):
    """The difference moved between the user reading it and confirming the adjustment."""


def _check_account(account):
    if not is_reconcilable(account):
        raise ReconciliationError(_("Only asset and liability accounts can be reconciled against a statement."))


def last_completed(account):
    return (
        Reconciliation.objects.filter(account=account, status=Reconciliation.STATUS_COMPLETED)
        .order_by("-statement_date", "-id")
        .first()
    )


def _check_statement_date(account, statement_date: date, *, exclude_id=None):
    latest = last_completed(account)
    if latest is not None and latest.id != exclude_id and statement_date <= latest.statement_date:
        raise ReconciliationError(
            _("The statement date must be after your last reconciled statement (%(date)s).")
            % {"date": latest.statement_date.isoformat()}
        )


def draft_for(account):
    return Reconciliation.objects.filter(account=account, status=Reconciliation.STATUS_DRAFT).first()


def start(account, statement_date: date, statement_balance: Decimal, user, preselect_line_ids=(), request=None):
    """
    Open a draft for `account`, or return the one already open.

    `statement_balance` is in STATEMENT sign (what the paper says). An existing
    draft keeps its own date and balance -- a second household member opening
    the page joins the work rather than resetting it -- but still takes any
    preselected lines.
    """
    _check_account(account)
    draft = draft_for(account)
    if draft is None:
        _check_statement_date(account, statement_date)
        try:
            with transaction.atomic():
                draft = Reconciliation.objects.create(
                    book=account.book,
                    account=account,
                    statement_date=statement_date,
                    statement_balance=to_ledger(account, statement_balance),
                    started_by=user,
                )
        except IntegrityError:
            # Two starts raced; the constraint let one through. Join it.
            draft = draft_for(account)
        else:
            log_event(
                AuditEvent.RECONCILIATION_STARTED,
                request=request,
                book=account.book,
                metadata={"account": account.id, "statement_date": statement_date.isoformat()},
            )
    if preselect_line_ids:
        tick(draft, preselect_line_ids, True)
    return draft


def update_statement(draft, *, statement_date=None, statement_balance=None):
    """Change a draft's date or balance (statement sign)."""
    _require_draft(draft)
    if statement_date is not None:
        _check_statement_date(draft.account, statement_date, exclude_id=draft.id)
        draft.statement_date = statement_date
    if statement_balance is not None:
        draft.statement_balance = to_ledger(draft.account, statement_balance)
    draft.save()
    return draft


def _require_draft(reconciliation):
    if not reconciliation.is_draft:
        raise ReconciliationError(_("This statement is already finished."))


def tick(draft, line_ids, ticked: bool) -> list[int]:
    """Tick or untick lines. Idempotent; refuses a line this draft may not hold."""
    _require_draft(draft)
    ids = {int(i) for i in line_ids}
    if not ids:
        return []
    if ticked:
        allowed = candidates.candidate_lines(draft).filter(id__in=ids)
        if allowed.count() != len(ids):
            raise ReconciliationError(_("One or more transactions can't be reconciled on this statement."))
        allowed.update(reconciliation=draft)
    else:
        draft.lines.filter(id__in=ids, is_reconciled=False).update(reconciliation=None)
    return sorted(ids)


def tick_through(draft, through: date) -> list[int]:
    """Tick every candidate dated on or before `through`, in one UPDATE."""
    _require_draft(draft)
    queryset = candidates.candidate_lines(draft).filter(journal_entry__entry_date__lte=through)
    ids = list(queryset.values_list("id", flat=True))
    queryset.update(reconciliation=draft)
    return ids


def untick_all(draft) -> None:
    _require_draft(draft)
    draft.lines.filter(is_reconciled=False).update(reconciliation=None)


@transaction.atomic
def finish(draft, user, *, adjust: bool = False, expected_difference=None, request=None) -> Reconciliation:
    """
    Lock the ticked lines and record the statement.

    With a difference, the caller must ask for an adjustment AND name the
    difference it showed the user (statement sign): if the numbers moved in the
    meantime -- another member ticked something -- the adjustment would post an
    amount nobody saw, so it is refused instead.
    """
    draft = Reconciliation.objects.select_for_update().get(pk=draft.pk)
    _require_draft(draft)
    account = draft.account

    current = candidates.summary(draft)
    difference = current.difference
    if difference != 0:
        if not adjust:
            raise ReconciliationError(
                _("The statement is off by %(diff)s. Resolve the difference, or finish with an adjustment.")
                % {"diff": to_statement(account, difference)}
            )
        if expected_difference is None or to_ledger(account, Decimal(expected_difference)) != difference:
            raise StaleDifference(_("The numbers changed while you were looking. Review the difference again."))

    lines = list(candidates.ticked_lines(draft))
    for line in lines:
        line.is_reconciled = True
        line.save()

    if difference != 0:
        create_adjustment(draft, difference)

    draft.opening_balance = current.opening
    draft.cleared_total = current.ticked_total + difference
    draft.adjustment_amount = difference
    draft.status = Reconciliation.STATUS_COMPLETED
    draft.completed_by = user
    draft.completed_at = timezone.now()
    draft.save()

    log_event(
        AuditEvent.RECONCILIATION_COMPLETED,
        request=request,
        book=draft.book,
        metadata={
            "reconciliation": draft.id,
            "account": account.id,
            "statement_date": draft.statement_date.isoformat(),
            "statement_balance": str(to_statement(account, draft.statement_balance)),
            "lines": len(lines),
            "adjustment": str(to_statement(account, difference)),
        },
    )
    return draft


def discard(draft) -> None:
    """Throw a draft away; `SET_NULL` releases its ticks."""
    _require_draft(draft)
    draft.delete()


@transaction.atomic
def undo(reconciliation, user, *, request=None) -> Reconciliation:
    """
    Reverse a completed statement -- any one, not only the latest.

    Its lines are unreconciled but keep their link, so the drift check can say
    "these came from the Jul 31 statement you undid"; they are candidates again
    for the next session. Its adjustment is voided and the adjustment's feed row
    archived. The statement row stays, marked undone, as history.
    """
    reconciliation = Reconciliation.objects.select_for_update().get(pk=reconciliation.pk)
    if not reconciliation.is_completed:
        raise ReconciliationError(_("Only a finished statement can be undone."))

    adjustment_entries = set()
    for line in reconciliation.lines.select_related("journal_entry").filter(is_reconciled=True):
        if line.journal_entry.source == JournalEntry.SOURCE_RECONCILIATION:
            adjustment_entries.add(line.journal_entry)
        line.is_reconciled = False
        line.save()

    for entry in adjustment_entries:
        entry.status = JournalEntry.STATUS_VOID
        entry.save()
        for bank_tx in BankTransaction.objects.filter(journal_entry=entry, is_archived=False):
            bank_tx.archive()

    reconciliation.status = Reconciliation.STATUS_UNDONE
    reconciliation.undone_at = timezone.now()
    reconciliation.save()

    log_event(
        AuditEvent.RECONCILIATION_UNDONE,
        request=request,
        book=reconciliation.book,
        metadata={
            "reconciliation": reconciliation.id,
            "account": reconciliation.account_id,
            "statement_date": reconciliation.statement_date.isoformat(),
        },
    )
    return reconciliation
