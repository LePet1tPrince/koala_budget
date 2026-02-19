"""
Celery tasks for Plaid app.
Handles background transaction syncing and updates.
"""

from datetime import date, datetime
from decimal import Decimal

from celery import shared_task
from django.db import transaction

from apps.teams.context import set_current_team

from .models import PlaidTransaction, PlaidAccount, PlaidItem
from apps.bank_feed.models import BankTransaction
from .services import sync_transactions


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
    print("STARTING THE PLAID SYNC")
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
    if PlaidTransaction.objects.filter(
        plaid_transaction_id=tx_data["transaction_id"]
    ).exists():
        return

    # Create bank transaction
    bank_transaction = BankTransaction.objects.create(
        team=plaid_item.team,
        account=plaid_account.account,
        amount=tx_data["amount"],
        posted_date=tx_data["date"],
        description=tx_data["name"],
        merchant_name=tx_data.get("merchant_name"),
        source=BankTransaction.SOURCE_PLAID,
        raw=json_safe(
            tx_data.to_dict() if hasattr(tx_data, "to_dict") else tx_data
        )
    )

    # Create plaid transaction
    PlaidTransaction.objects.create(
        team=plaid_item.team,
        plaid_transaction_id=tx_data["transaction_id"],
        bank_transaction=bank_transaction,
        plaid_account=plaid_account,
        iso_currency_code=tx_data.get("iso_currency_code"),
        unofficial_currency_code=tx_data.get("unofficial_currency_code"),
        authorized_date=tx_data.get("authorized_date"),
        pending=tx_data.get("pending", False),
        pending_transaction_id=tx_data.get("pending_transaction_id"),
        personal_finance_category=tx_data.get("personal_finance_category", {}).get("primary"),
        personal_finance_category_id=tx_data.get("personal_finance_category", {}).get("detailed"),
        category_confidence=tx_data.get("personal_finance_category", {}).get("confidence_level"),
        payment_channel=tx_data.get("payment_channel"),
        transaction_type=tx_data.get("transaction_type"),
        location=json_safe(
            tx_data.get("location").to_dict()
            if tx_data.get("location")
            else None
        ),
        merchant_metadata=json_safe(
            tx_data.get("merchant_metadata").to_dict()
            if tx_data.get("merchant_metadata")
            else None
        ),
    )


@transaction.atomic
def process_modified_transaction(plaid_item: PlaidItem, tx_data: dict):
    """
    Process a modified transaction from Plaid.
    Updates the existing BankTransaction and PlaidTransaction records.
    """
    try:
        plaid_tx = PlaidTransaction.objects.select_related('bank_transaction').get(
            plaid_transaction_id=tx_data["transaction_id"],
            team=plaid_item.team,
        )

        # Only update if not yet categorized (journal_entry is null)
        if plaid_tx.bank_transaction.journal_entry is None:
            # Update bank transaction
            plaid_tx.bank_transaction.amount = tx_data["amount"]
            plaid_tx.bank_transaction.posted_date = tx_data["date"]
            plaid_tx.bank_transaction.description = tx_data["name"]
            plaid_tx.bank_transaction.merchant_name = tx_data.get("merchant_name")
            plaid_tx.bank_transaction.raw = json_safe(
                tx_data.to_dict() if hasattr(tx_data, "to_dict") else tx_data
            )
            plaid_tx.bank_transaction.save()

            # Update plaid transaction
            plaid_tx.authorized_date = tx_data.get("authorized_date")
            plaid_tx.pending = tx_data.get("pending", False)
            plaid_tx.pending_transaction_id = tx_data.get("pending_transaction_id")
            plaid_tx.personal_finance_category = tx_data.get("personal_finance_category", {}).get("primary")
            plaid_tx.personal_finance_category_id = tx_data.get("personal_finance_category", {}).get("detailed")
            plaid_tx.category_confidence = tx_data.get("personal_finance_category", {}).get("confidence_level")
            plaid_tx.payment_channel = tx_data.get("payment_channel")
            plaid_tx.transaction_type = tx_data.get("transaction_type")
            plaid_tx.location = json_safe(
                tx_data.get("location").to_dict()
                if tx_data.get("location")
                else None
            )
            plaid_tx.merchant_metadata = json_safe(
                tx_data.get("merchant_metadata").to_dict()
                if tx_data.get("merchant_metadata")
                else None
            )
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
        plaid_tx = PlaidTransaction.objects.select_related('bank_transaction').get(
            plaid_transaction_id=tx_data["transaction_id"],
            team=plaid_item.team,
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
