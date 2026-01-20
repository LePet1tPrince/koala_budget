"""
Serializers for Plaid app.
Includes the unified BankFeedRow serializer and adapter functions.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.accounts.serializers import AccountSerializer
from apps.journal.models import JournalLine

from .models import PlaidTransaction, PlaidAccount, PlaidItem


class PlaidItemSerializer(serializers.ModelSerializer):
    """Serializer for PlaidItem model."""

    class Meta:
        model = PlaidItem
        fields = [
            "id",
            "plaid_item_id",
            "institution_name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class PlaidAccountSerializer(serializers.ModelSerializer):
    """Serializer for PlaidAccount model."""

    account_details = AccountSerializer(source="account", read_only=True)
    item_details = PlaidItemSerializer(source="item", read_only=True)

    class Meta:
        model = PlaidAccount
        fields = [
            "id",
            "plaid_account_id",
            "item",
            "item_details",
            "account",
            "account_details",
            "name",
            "mask",
            "subtype",
            "type",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class PlaidTransactionSerializer(serializers.ModelSerializer):
    """Serializer for PlaidTransaction model."""

    plaid_account_details = PlaidAccountSerializer(source="plaid_account", read_only=True)

    class Meta:
        model = PlaidTransaction
        fields = [
            "id",
            "plaid_transaction_id",
            "plaid_account",
            "plaid_account_details",
            "iso_currency_code",
            "authorized_date",
            "pending",
            "personal_finance_category",
            "category_confidence",
            "payment_channel",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class BankFeedRowSerializer(serializers.Serializer):
    """
    Unified bank feed row serializer.
    This is NOT a model - it's a projection that combines data from
    JournalLine (ledger) and PlaidTransaction (Plaid staging).
    """

    id = serializers.CharField(help_text="Composite ID: 'ledger-{id}' or 'plaid-{id}'")
    source = serializers.ChoiceField(choices=["ledger", "plaid"], help_text="Source of this row")

    date = serializers.DateField(help_text="Transaction date")
    authorized_date = serializers.DateField(allow_null=True, help_text="Authorization date (Plaid only)")

    description = serializers.CharField(help_text="Transaction description")
    merchant_name = serializers.CharField(allow_null=True, help_text="Merchant name")

    account = AccountSerializer(help_text="The account this transaction affects")
    category = AccountSerializer(allow_null=True, help_text="Category account (null if uncategorized)")

    inflow = serializers.DecimalField(max_digits=12, decimal_places=2, help_text="Money coming in")
    outflow = serializers.DecimalField(max_digits=12, decimal_places=2, help_text="Money going out")

    is_pending = serializers.BooleanField(help_text="Whether transaction is pending")
    is_cleared = serializers.BooleanField(help_text="Whether transaction is cleared")

    payment_channel = serializers.CharField(allow_null=True, help_text="Payment channel (Plaid)")
    confidence = serializers.CharField(allow_null=True, help_text="Categorization confidence")

    journal_line_id = serializers.IntegerField(allow_null=True, help_text="ID of journal line (if ledger)")
    imported_transaction_id = serializers.IntegerField(allow_null=True, help_text="ID of imported tx (if Plaid)")

    is_editable = serializers.BooleanField(help_text="Whether this row can be edited")


# Adapter Functions


def journal_line_to_feed_row(line: JournalLine) -> dict:
    """
    Convert a JournalLine to a BankFeedRow dict.
    Assumes a 2-line journal entry (simple transaction).
    """
    # Get the sibling line (category)
    all_lines = list(line.journal_entry.lines.all())
    sibling = None
    if len(all_lines) == 2:
        sibling = all_lines[0] if all_lines[1].id == line.id else all_lines[1]

    # Calculate inflow/outflow
    inflow = line.dr_amount if line.dr_amount > 0 else Decimal("0")
    outflow = line.cr_amount if line.cr_amount > 0 else Decimal("0")

    return {
        "id": f"ledger-{line.id}",
        "source": "ledger",
        "date": line.journal_entry.entry_date,
        "authorized_date": None,
        "description": line.journal_entry.description,
        "merchant_name": line.journal_entry.payee.name if line.journal_entry.payee else None,
        "account": line.account,
        "category": sibling.account if sibling else None,
        "inflow": inflow,
        "outflow": outflow,
        "is_pending": False,
        "is_cleared": line.is_cleared,
        "payment_channel": None,
        "confidence": "manual",
        "journal_line_id": line.id,
        "imported_transaction_id": None,
        "is_editable": True,
    }


def imported_tx_to_feed_row(tx: PlaidTransaction) -> dict:
    """
    Convert a PlaidTransaction to a BankFeedRow dict.
    Only called for uncategorized transactions (bank_transaction.journal_entry is null).
    """
    # Access the related BankTransaction for common fields
    bank_tx = tx.bank_transaction
    amount = abs(bank_tx.amount)

    # Plaid convention: positive = outflow, negative = inflow
    inflow = amount if bank_tx.amount < 0 else Decimal("0")
    outflow = amount if bank_tx.amount > 0 else Decimal("0")

    return {
        "id": f"plaid-{tx.id}",
        "source": "plaid",
        "date": bank_tx.posted_date,
        "authorized_date": tx.authorized_date,
        "description": bank_tx.description,
        "merchant_name": bank_tx.merchant_name,
        "account": tx.plaid_account.account,
        "category": None,  # Uncategorized
        "inflow": inflow,
        "outflow": outflow,
        "is_pending": tx.pending,
        "is_cleared": False,
        "payment_channel": tx.payment_channel,
        "confidence": tx.category_confidence,
        "journal_line_id": None,
        "imported_transaction_id": tx.id,
        "is_editable": True,
    }
