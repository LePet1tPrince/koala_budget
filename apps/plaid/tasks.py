"""
Celery tasks for Plaid app.
Handles background transaction syncing and updates.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from plaid import ApiException

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.bank_feed.models import BankTransaction
from apps.books.context import set_current_book, unset_current_book

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


@shared_task
def sync_plaid_transactions(plaid_item_id: int):
    """
    Sync transactions for a specific Plaid item.
    Uses the /transactions/sync endpoint with cursor-based pagination.

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

        updates = fetch_updates(plaid_item)

        # The rows and the cursor commit together. Saving the cursor separately
        # would let a crash between the two either skip updates (cursor saved,
        # rows not) or re-apply them; applying everything at once also means a
        # posted transaction and the removal of its pending one are always seen
        # side by side, whichever page Plaid put them on.
        with transaction.atomic():
            for tx_data in updates.added:
                process_added_transaction(plaid_item, tx_data)
            for tx_data in updates.modified:
                process_modified_transaction(plaid_item, tx_data)
            for tx_data in updates.removed:
                process_removed_transaction(plaid_item, tx_data)

            plaid_item.cursor = updates.next_cursor
            plaid_item.last_synced_at = timezone.now()
            plaid_item.save(update_fields=["cursor", "last_synced_at", "updated_at"])

        total_added = len(updates.added)
        total_modified = len(updates.modified)
        total_removed = len(updates.removed)

        log_event(
            AuditEvent.PLAID_SYNC_COMPLETED,
            book=plaid_item.book,
            metadata={
                "plaid_item_id": plaid_item_id,
                "added": total_added,
                "modified": total_modified,
                "removed": total_removed,
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


@transaction.atomic
def process_added_transaction(plaid_item: PlaidItem, tx_data: dict):
    """
    Process a newly added transaction from Plaid.
    Creates BankTransaction and PlaidTransaction records.
    """
    # Get the plaid account
    plaid_account = PlaidAccount.objects.filter(
        item=plaid_item,
        plaid_account_id=tx_data["account_id"],
    ).first()

    if not plaid_account or not plaid_account.account:
        # Skip if account not found or not mapped to ledger account
        return

    # Check if transaction already exists
    if PlaidTransaction.objects.filter(plaid_transaction_id=tx_data["transaction_id"]).exists():
        return

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


@transaction.atomic
def process_modified_transaction(plaid_item: PlaidItem, tx_data: dict):
    """
    Process a modified transaction from Plaid.
    Updates the existing BankTransaction and PlaidTransaction records.
    """
    try:
        plaid_tx = PlaidTransaction.objects.select_related("bank_transaction").get(
            plaid_transaction_id=tx_data["transaction_id"],
            book=plaid_item.book,
        )

        # Only update if not yet categorized (journal_entry is null)
        if plaid_tx.bank_transaction.journal_entry is None:
            # Update bank transaction
            plaid_tx.bank_transaction.amount = tx_data["amount"]
            plaid_tx.bank_transaction.posted_date = tx_data["date"]
            plaid_tx.bank_transaction.description = tx_data["name"]
            plaid_tx.bank_transaction.merchant_name = tx_data.get("merchant_name")
            plaid_tx.bank_transaction.raw = _as_dict(tx_data)
            plaid_tx.bank_transaction.save()

            # Update plaid transaction
            for field, value in plaid_details(tx_data).items():
                setattr(plaid_tx, field, value)
            plaid_tx.save()

    except PlaidTransaction.DoesNotExist:
        # If not found, treat as new
        process_added_transaction(plaid_item, tx_data)


@transaction.atomic
def process_removed_transaction(plaid_item: PlaidItem, tx_data: dict):
    """
    Process a removed transaction from Plaid.
    Deletes the BankTransaction and PlaidTransaction if it hasn't been categorized.
    """
    try:
        plaid_tx = PlaidTransaction.objects.select_related("bank_transaction").get(
            plaid_transaction_id=tx_data["transaction_id"],
            book=plaid_item.book,
        )

        # Only delete if not yet categorized (journal_entry is null)
        if plaid_tx.bank_transaction.journal_entry is None:
            # Delete bank transaction (this will cascade to plaid transaction due to OneToOneField)
            plaid_tx.bank_transaction.delete()

    except PlaidTransaction.DoesNotExist:
        # Already deleted or never existed
        pass


@shared_task
def sync_all_plaid_items():
    """
    Sync transactions for all Plaid items.
    This can be run on a schedule (e.g., every hour).
    """
    all_items = PlaidItem.objects.all()

    results = []
    for item in all_items:
        result = sync_plaid_transactions.delay(item.id)
        results.append({"item_id": item.id, "task_id": result.id})

    return {"success": True, "synced_items": len(results), "tasks": results}
