"""
Celery tasks for Plaid app.
Handles background transaction syncing and updates.
"""

from celery import shared_task
from django.db import transaction

from apps.teams.context import set_current_team

from .models import ImportedTransaction, PlaidAccount, PlaidItem
from .services import sync_transactions
from datetime import date, datetime
from decimal import Decimal

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


@shared_task
def sync_plaid_transactions(plaid_item_id: int):
    """
    Sync transactions for a specific Plaid item.
    Uses the /transactions/sync endpoint with cursor-based pagination.

    Args:
        plaid_item_id: ID of the PlaidItem to sync
    """
    try:
        plaid_item = PlaidItem.objects.select_related("team").get(id=plaid_item_id)

        # Set team context for the task
        set_current_team(plaid_item.team)

        # Get the cursor for incremental sync
        cursor = plaid_item.cursor

        has_more = True
        total_added = 0
        total_modified = 0
        total_removed = 0

        while has_more:
            # Sync transactions
            result = sync_transactions(
                access_token=plaid_item.access_token,
                cursor=cursor,
            )

            # Process added transactions
            for tx_data in result["added"]:
                process_added_transaction(plaid_item, tx_data)
                total_added += 1

            # Process modified transactions
            for tx_data in result["modified"]:
                process_modified_transaction(plaid_item, tx_data)
                total_modified += 1

            # Process removed transactions
            for tx_data in result["removed"]:
                process_removed_transaction(plaid_item, tx_data)
                total_removed += 1

            # Update cursor and check if there's more
            cursor = result["next_cursor"]
            has_more = result["has_more"]

        # Save the final cursor
        plaid_item.cursor = cursor
        plaid_item.save()

        return {
            "success": True,
            "added": total_added,
            "modified": total_modified,
            "removed": total_removed,
        }

    except PlaidItem.DoesNotExist:
        return {"success": False, "error": "PlaidItem not found"}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        print(type(e), e)
        raise



@transaction.atomic
def process_added_transaction(plaid_item: PlaidItem, tx_data: dict):
    """
    Process a newly added transaction from Plaid.
    Creates an ImportedTransaction record.
    """
    # Get the plaid account
    plaid_account = PlaidAccount.objects.filter(
        item=plaid_item,
        plaid_account_id=tx_data["account_id"],
    ).first()

    if not plaid_account:
        # Skip if account not found (shouldn't happen)
        return

    # Check if transaction already exists
    if ImportedTransaction.objects.filter(
        plaid_transaction_id=tx_data["transaction_id"]
    ).exists():
        return

    # Create imported transaction
    ImportedTransaction.objects.create(
        team=plaid_item.team,
        plaid_transaction_id=tx_data["transaction_id"],
        plaid_account=plaid_account,
        amount=tx_data["amount"],
        iso_currency_code=tx_data.get("iso_currency_code"),
        unofficial_currency_code=tx_data.get("unofficial_currency_code"),
        date=tx_data["date"],
        authorized_date=tx_data.get("authorized_date"),
        pending=tx_data.get("pending", False),
        pending_transaction_id=tx_data.get("pending_transaction_id"),
        name=tx_data["name"],
        merchant_name=tx_data.get("merchant_name"),
        personal_finance_category=tx_data.get("personal_finance_category", {}).get("primary"),
        personal_finance_category_id=tx_data.get("personal_finance_category", {}).get("detailed"),
        category_confidence=tx_data.get("personal_finance_category", {}).get("confidence_level"),
        payment_channel=tx_data.get("payment_channel"),
        transaction_type=tx_data.get("transaction_type"),
        location = json_safe(
            tx_data.get("location").to_dict()
            if tx_data.get("location")
            else None
        ),
        merchant_metadata = json_safe(
            tx_data.get("merchant_metadata").to_dict()
            if tx_data.get("merchant_metadata")
            else None
        ),
        raw = json_safe(
            tx_data.to_dict() if hasattr(tx_data, "to_dict") else tx_data
        )
    )


@transaction.atomic
def process_modified_transaction(plaid_item: PlaidItem, tx_data: dict):
    """
    Process a modified transaction from Plaid.
    Updates the existing ImportedTransaction record.
    """
    try:
        imported_tx = ImportedTransaction.objects.get(
            plaid_transaction_id=tx_data["transaction_id"],
            team=plaid_item.team,
        )

        # Only update if not yet categorized (journal_entry is null)
        if imported_tx.journal_entry is None:
            imported_tx.amount = tx_data["amount"]
            imported_tx.date = tx_data["date"]
            imported_tx.authorized_date = tx_data.get("authorized_date")
            imported_tx.pending = tx_data.get("pending", False)
            imported_tx.name = tx_data["name"]
            imported_tx.merchant_name = tx_data.get("merchant_name")
            imported_tx.raw = tx_data.to_dict() if hasattr(tx_data, 'to_dict') else tx_data
            imported_tx.save()

    except ImportedTransaction.DoesNotExist:
        # If not found, treat as new
        process_added_transaction(plaid_item, tx_data)


@transaction.atomic
def process_removed_transaction(plaid_item: PlaidItem, tx_data: dict):
    """
    Process a removed transaction from Plaid.
    Deletes the ImportedTransaction if it hasn't been categorized.
    """
    try:
        imported_tx = ImportedTransaction.objects.get(
            plaid_transaction_id=tx_data["transaction_id"],
            team=plaid_item.team,
        )

        # Only delete if not yet categorized (journal_entry is null)
        if imported_tx.journal_entry is None:
            imported_tx.delete()

    except ImportedTransaction.DoesNotExist:
        # Already deleted or never existed
        pass


@shared_task
def sync_all_plaid_items():
    """
    Sync transactions for all active Plaid items.
    This can be run on a schedule (e.g., every hour).
    """
    active_items = PlaidItem.objects.filter(is_active=True)

    results = []
    for item in active_items:
        result = sync_plaid_transactions.delay(item.id)
        results.append({"item_id": item.id, "task_id": result.id})

    return {"success": True, "synced_items": len(results), "tasks": results}
