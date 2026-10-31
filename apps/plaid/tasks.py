"""
Celery tasks for Plaid app.
Handles background transaction syncing and updates.
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from plaid import ApiException

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.bank_feed.models import BankTransaction
from apps.bank_feed.services.bank_revision import Revision, difference_rows, revise
from apps.books.context import set_current_book, unset_current_book
from apps.journal.services import voiding

from . import item_status, sync_lock
from .item_status import TRANSIENT_CODES
from .models import PlaidAccount, PlaidItem, PlaidTransaction
from .services import plaid_error_code, sync_transactions

logger = logging.getLogger(__name__)


def json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def _as_dict(value):
    """A Plaid SDK model (which has `to_dict`), a plain dict, or None, as JSON-safe data."""
    if value is None:
        return None
    return json_safe(value.to_dict() if hasattr(value, "to_dict") else value)


def plaid_details(tx_data) -> dict:
    """
    The `PlaidTransaction` fields Plaid sends with a transaction, shared by the
    added and modified paths.

    Plaid documents `personal_finance_category`, `location` and
    `merchant_metadata` as nullable. A present-but-null value must read as "no
    detail", not crash: one such row would otherwise fail the whole sync and
    leave the cursor where it was, so every later sync would fail on it too.
    """
    category = tx_data.get("personal_finance_category") or {}
    return {
        "authorized_date": tx_data.get("authorized_date"),
        "pending": tx_data.get("pending") or False,
        "pending_transaction_id": tx_data.get("pending_transaction_id"),
        "personal_finance_category": category.get("primary"),
        "personal_finance_category_id": category.get("detailed"),
        "category_confidence": category.get("confidence_level"),
        "payment_channel": tx_data.get("payment_channel"),
        "transaction_type": tx_data.get("transaction_type"),
        "location": _as_dict(tx_data.get("location")),
        "merchant_metadata": _as_dict(tx_data.get("merchant_metadata")),
    }


#: How often a sync restarts from its saved cursor when Plaid reports that the
#: data changed under it mid-pagination, before giving up until the next sync.
MAX_PAGINATION_RESTARTS = 3

MUTATION_DURING_PAGINATION = "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"


class PaginationRestartsExhausted(RuntimeError):
    """Plaid kept changing the data mid-pagination; the next sync will try again."""


@dataclass
class SyncUpdates:
    added: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    next_cursor: str | None = None


def fetch_updates(plaid_item: PlaidItem) -> SyncUpdates:
    """
    Every page of /transactions/sync from the item's saved cursor, collected
    before anything is applied.

    Plaid's contract: if the data changes while the pages are being read, the
    call fails with TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION and the whole
    read must restart from the cursor it began with -- pages already read are
    void. Applying page by page (as this used to) would have committed them.
    """
    for _attempt in range(MAX_PAGINATION_RESTARTS + 1):
        updates = SyncUpdates()
        cursor = plaid_item.cursor
        try:
            while True:
                result = sync_transactions(access_token=plaid_item.access_token, cursor=cursor)
                updates.added.extend(result["added"])
                updates.modified.extend(result["modified"])
                updates.removed.extend(result["removed"])
                cursor = result["next_cursor"]
                if not result["has_more"]:
                    updates.next_cursor = cursor
                    return updates
        except ApiException as exc:
            if plaid_error_code(exc) != MUTATION_DURING_PAGINATION:
                raise
            logger.info("Plaid data changed mid-sync for item %s; restarting from the saved cursor", plaid_item.id)
    raise PaginationRestartsExhausted(f"Plaid kept changing data mid-sync for item {plaid_item.id}")


#: How many times one sync goes round for reruns requested while it ran.
MAX_RERUNS = 3


@shared_task
def sync_plaid_transactions(plaid_item_id: int, scheduled: bool = False):
    """
    Sync transactions for a specific Plaid item, holding its sync lock.

    When another sync holds the lock, a webhook- or user-triggered sync asks it
    to go round again (so the new data is not missed) and returns; a scheduled
    one just skips -- the item is being synced anyway.

    Args:
        plaid_item_id: ID of the PlaidItem to sync
        scheduled: True for the periodic catch-up (`sync_all_plaid_items`)
    """
    if not PlaidItem.objects.filter(pk=plaid_item_id).exists():
        return {"success": False, "error": "PlaidItem not found"}

    if not sync_lock.claim(plaid_item_id):
        if not scheduled and sync_lock.request_rerun(plaid_item_id):
            return {"success": True, "status": "rerun_requested"}
        if scheduled or not sync_lock.claim(plaid_item_id):
            return {"success": False, "status": "busy"}

    try:
        for _round in range(MAX_RERUNS + 1):
            result = _sync_item(plaid_item_id)
            if sync_lock.release(plaid_item_id):
                return result
        sync_lock.force_release(plaid_item_id)
        return result
    except BaseException:
        sync_lock.force_release(plaid_item_id)
        raise


def _display_message(exc) -> str:
    """Plaid's user-facing message from a failed API call, if it sent one."""
    try:
        body = json.loads(exc.body or "{}")
    except (TypeError, ValueError):
        return ""
    return (body.get("display_message") or body.get("error_message") or "") if isinstance(body, dict) else ""


def _sync_item(plaid_item_id: int):
    """
    One pass of /transactions/sync for an item, from its saved cursor.

    Args:
        plaid_item_id: ID of the PlaidItem to sync
    """
    logger.info("Starting Plaid sync for item %s", plaid_item_id)
    plaid_item = None
    context_token = None
    try:
        plaid_item = PlaidItem.objects.select_related("book__team").get(id=plaid_item_id)

        # The item's book is the task's tenant. Unset in `finally`: a Celery worker
        # runs the next task in the same context, which must not inherit this one.
        context_token = set_current_book(plaid_item.book)

        log_event(AuditEvent.PLAID_SYNC_STARTED, book=plaid_item.book, metadata={"plaid_item_id": plaid_item_id})

        try:
            updates = fetch_updates(plaid_item)
        except ApiException as exc:
            code = plaid_error_code(exc)
            if not (item_status.record_error(plaid_item, code, _display_message(exc)) or code in TRANSIENT_CODES):
                raise
            # The connection needs the user (or the bank needs time): nothing to
            # retry until then, so report it rather than raise into a retry loop.
            log_event(
                AuditEvent.PLAID_SYNC_FAILED,
                book=plaid_item.book,
                metadata={"plaid_item_id": plaid_item_id, "error_code": code},
            )
            return {"success": False, "error_code": code}

        # The rows and the cursor commit together. Saving the cursor separately
        # would let a crash between the two either skip updates (cursor saved,
        # rows not) or re-apply them; applying everything at once also means a
        # posted transaction and the removal of its pending one are always seen
        # side by side, whichever page Plaid put them on.
        outcomes = Counter()
        sync_started = timezone.now()
        with transaction.atomic():
            # Added first: a posted transaction must claim its pending row before
            # the pending one's removal is processed.
            for tx_data in updates.added:
                outcomes[process_added_transaction(plaid_item, tx_data)] += 1
            for tx_data in updates.modified:
                outcomes[process_modified_transaction(plaid_item, tx_data)] += 1
            for tx_data in updates.removed:
                outcomes[f"removed_{process_removed_transaction(plaid_item, tx_data)}"] += 1

            # Only from the cursor this sync started at: if it was reset meanwhile
            # (an account was just mapped -- linking.backfill_item), the reset
            # must survive, and the rerun that reset queued reads from the start.
            now = timezone.now()
            PlaidItem.objects.filter(pk=plaid_item.pk, cursor=plaid_item.cursor).update(
                cursor=updates.next_cursor, last_synced_at=now, updated_at=now
            )
            plaid_item.refresh_from_db()
            item_status.record_sync_success(plaid_item)

        total_added = len(updates.added)
        total_modified = len(updates.modified)
        total_removed = len(updates.removed)

        # After the rows and the cursor have committed, so a rule that can't file a
        # row (or anything else going wrong there) can never undo or retry the sync.
        auto_categorized = _categorize_new_rows(plaid_item, sync_started) if updates.added else 0

        log_event(
            AuditEvent.PLAID_SYNC_COMPLETED,
            book=plaid_item.book,
            metadata={
                "plaid_item_id": plaid_item_id,
                "added": total_added,
                "modified": total_modified,
                "removed": total_removed,
                "outcomes": dict(outcomes),
                "auto_categorized": auto_categorized,
            },
        )

        return {
            "success": True,
            "added": total_added,
            "modified": total_modified,
            "removed": total_removed,
        }

    except PlaidItem.DoesNotExist:
        return {"success": False, "error": "PlaidItem not found"}
    except Exception as e:
        logger.exception("Plaid sync failed for item %s", plaid_item_id)
        log_event(
            AuditEvent.PLAID_SYNC_FAILED,
            book=plaid_item.book if plaid_item else None,
            metadata={"plaid_item_id": plaid_item_id, "error": str(e)},
        )
        raise
    finally:
        if context_token is not None:
            unset_current_book(context_token)


def _categorize_new_rows(plaid_item, since) -> int:
    """Run the book's auto rules (apps.categorization) over the rows this sync added. Never raises."""
    from apps.categorization.pipeline import TRIGGER_PLAID, categorize_on_arrival

    rows = BankTransaction.objects.filter(
        book=plaid_item.book,
        plaid_transaction__plaid_account__item=plaid_item,
        created_at__gte=since,
        journal_entry__isnull=True,
    )
    result = categorize_on_arrival(plaid_item.book, list(rows), trigger=TRIGGER_PLAID)
    return result.categorized_count if result else 0


def _revision(tx_data) -> Revision:
    return Revision(
        amount=Decimal(str(tx_data["amount"])),
        posted_date=tx_data["date"],
        description=tx_data["name"],
        merchant_name=tx_data.get("merchant_name"),
    )


def _plaid_tx(plaid_item, transaction_id):
    """The item's PlaidTransaction for a Plaid transaction id, or None."""
    return (
        PlaidTransaction.objects.select_related("bank_transaction")
        .filter(plaid_transaction_id=transaction_id, plaid_account__item=plaid_item)
        .first()
    )


def _apply_plaid_fields(plaid_tx, tx_data):
    plaid_tx.iso_currency_code = tx_data.get("iso_currency_code")
    plaid_tx.unofficial_currency_code = tx_data.get("unofficial_currency_code")
    for name, value in plaid_details(tx_data).items():
        setattr(plaid_tx, name, value)


@transaction.atomic
def process_added_transaction(plaid_item: PlaidItem, tx_data: dict) -> str:
    """
    Process a newly added transaction from Plaid: a new feed row, or -- for a
    posted transaction that settles a pending one -- the pending row carried
    forward. Returns what happened ("added", "settled" or "skipped").
    """
    if PlaidTransaction.objects.filter(plaid_transaction_id=tx_data["transaction_id"]).exists():
        return "skipped"

    pending_id = tx_data.get("pending_transaction_id")
    if pending_id:
        pending = _plaid_tx(plaid_item, pending_id)
        if pending is not None and not pending.bank_transaction.is_void:
            settle_pending(pending, tx_data)
            return "settled"

    plaid_account = PlaidAccount.objects.filter(
        item=plaid_item,
        plaid_account_id=tx_data["account_id"],
    ).first()

    if not plaid_account or not plaid_account.account:
        # Skip if account not found or not mapped to ledger account
        return "skipped"

    # Create bank transaction
    bank_transaction = BankTransaction.objects.create(
        book=plaid_item.book,
        account=plaid_account.account,
        amount=tx_data["amount"],
        posted_date=tx_data["date"],
        description=tx_data["name"],
        merchant_name=tx_data.get("merchant_name"),
        source=BankTransaction.SOURCE_PLAID,
        raw=_as_dict(tx_data),
    )

    # Create plaid transaction
    PlaidTransaction.objects.create(
        book=plaid_item.book,
        plaid_transaction_id=tx_data["transaction_id"],
        bank_transaction=bank_transaction,
        plaid_account=plaid_account,
        iso_currency_code=tx_data.get("iso_currency_code"),
        unofficial_currency_code=tx_data.get("unofficial_currency_code"),
        **plaid_details(tx_data),
    )
    return "added"


@transaction.atomic
def settle_pending(pending: PlaidTransaction, tx_data: dict):
    """
    Carry a posted transaction onto the row its pending authorization made.

    Plaid reports a settlement as a new posted transaction (whose
    `pending_transaction_id` names the pending one) plus the pending one in
    `removed`. Taken literally, that deletes or orphans the row the user may
    already have categorized and adds a second, uncategorized row for the same
    money -- which double-counts once categorized. Instead the existing row
    becomes the posted transaction: it takes the posted id (so the removal of
    the pending id finds nothing) and the bank's posted amount and date, through
    `bank_revision.revise`, which keeps the category and respects reconciliation.
    """
    bank_tx = pending.bank_transaction
    pending.plaid_transaction_id = tx_data["transaction_id"]
    _apply_plaid_fields(pending, tx_data)
    pending.pending_transaction_id = pending.pending_transaction_id or tx_data.get("pending_transaction_id")
    pending.save()

    revise(bank_tx, _revision(tx_data))
    BankTransaction.objects.filter(pk=bank_tx.pk).update(raw=_as_dict(tx_data))


@transaction.atomic
def process_modified_transaction(plaid_item: PlaidItem, tx_data: dict) -> str:
    """
    Process a modified transaction from Plaid: the bank's new figures carried
    onto the existing row, categorized or not (`bank_revision.revise`).
    """
    plaid_tx = _plaid_tx(plaid_item, tx_data["transaction_id"])
    if plaid_tx is None:
        # If not found, treat as new
        return process_added_transaction(plaid_item, tx_data)

    _apply_plaid_fields(plaid_tx, tx_data)
    plaid_tx.save()
    revise(plaid_tx.bank_transaction, _revision(tx_data))
    BankTransaction.objects.filter(pk=plaid_tx.bank_transaction_id).update(raw=_as_dict(tx_data))
    return "revised"


@transaction.atomic
def process_removed_transaction(plaid_item: PlaidItem, tx_data: dict) -> str:
    """
    Process a transaction Plaid no longer reports -- typically a pending
    authorization that was cancelled (a settled one was already carried forward
    by `settle_pending`, so its pending id finds nothing here).

    - Uncategorized: deleted; nothing refers to it.
    - Categorized: voided (with any difference rows), so it drops out of every
      balance but stays in the Inbox's Voided view, where the user can restore
      it if the bank was wrong. Keeping it live would leave spending in the
      books that never happened.
    - Reconciled: kept, since voiding would falsify a statement; logged.
    """
    plaid_tx = _plaid_tx(plaid_item, tx_data["transaction_id"])
    if plaid_tx is None:
        return "skipped"
    bank_tx = plaid_tx.bank_transaction
    if bank_tx.is_void:
        return "skipped"
    if bank_tx.journal_entry_id is None:
        # Delete bank transaction (this will cascade to plaid transaction due to OneToOneField)
        bank_tx.delete()
        return "deleted"
    try:
        voiding.void(rows=[bank_tx, *difference_rows(bank_tx).filter(is_void=False)])
    except voiding.VoidRefused:
        logger.warning(
            "Plaid removed transaction %s, but its row %s is reconciled; kept", tx_data["transaction_id"], bank_tx.pk
        )
        return "kept"
    return "voided"


@shared_task
def sync_all_plaid_items():
    """
    The scheduled catch-up (SCHEDULED_TASKS["plaid-sync-catch-up"]).

    Sync is driven by Plaid's webhooks; this catches what a missed or failed
    webhook would otherwise leave behind. It queues only items not synced in
    PLAID_SCHEDULED_SYNC_MIN_AGE_HOURS (so a webhook-fed item costs nothing),
    stalest first, at most PLAID_SCHEDULED_SYNC_BATCH_SIZE per run, staggered
    PLAID_SCHEDULED_SYNC_STAGGER_SECONDS apart so a run doesn't hit Plaid all at
    once. Each runs with `scheduled=True`: an item already syncing is skipped.
    """
    cutoff = timezone.now() - timedelta(hours=settings.PLAID_SCHEDULED_SYNC_MIN_AGE_HOURS)
    items = list(
        PlaidItem.objects.filter(is_archived=False)
        # Nothing to fetch until the user reconnects; Plaid would only refuse again.
        .exclude(status__in=PlaidItem.BLOCKED_STATUSES)
        .filter(Q(last_synced_at__isnull=True) | Q(last_synced_at__lt=cutoff))
        .order_by(F("last_synced_at").asc(nulls_first=True), "pk")
        .values_list("pk", flat=True)[: settings.PLAID_SCHEDULED_SYNC_BATCH_SIZE]
    )

    results = []
    for position, item_id in enumerate(items):
        task = sync_plaid_transactions.apply_async(
            args=[item_id],
            kwargs={"scheduled": True},
            countdown=position * settings.PLAID_SCHEDULED_SYNC_STAGGER_SECONDS,
        )
        results.append({"item_id": item_id, "task_id": task.id})

    return {"success": True, "synced_items": len(results), "tasks": results}
