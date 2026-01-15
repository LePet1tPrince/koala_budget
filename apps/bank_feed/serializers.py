"""
Serializers for bank_feed app.
Provides serializers for BankTransaction and adapter functions for bank feed rows.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.accounts.serializers import AccountSerializer
from apps.journal.models import JournalLine
from apps.plaid.serializers import PlaidAccountSerializer, PlaidItemSerializer

from .models import BankTransaction

class BankTransactionSerializer(serializers.ModelSerializer):
    """Serializer for BankTransaction model."""

    plaid_account_details = PlaidAccountSerializer(source="plaid_account", read_only=True)
    is_categorized = serializers.BooleanField(read_only=True)

    class Meta:
        model = BankTransaction
        fields = [
            "id",
            "source",
            "plaid_transaction_id",
            "plaid_account",
            "plaid_account_details",
            "amount",
            "account",
            "iso_currency_code",
            "date",
            "authorized_date",
            "pending",
            "description",
            "merchant_name",
            "plaid_category",
            "plaid_category_confidence",
            "payment_channel",
            "journal_entry",
            "is_categorized",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class BankFeedRowSerializer(serializers.Serializer):
    """
    Unified bank feed row serializer.
    This is NOT a model - it's a projection that combines data from
    JournalLine (ledger) and BankTransaction (bank feed staging).
    """

    id = serializers.CharField(help_text="Composite ID: 'ledger-{id}' or 'plaid-{id}'")
    source = serializers.ChoiceField(
        choices=["ledger", "plaid", "csv", "system"],
        help_text="Source of this row",
    )

    date = serializers.DateField(help_text="Transaction date")
    authorized_date = serializers.DateField(
        allow_null=True,
        help_text="Authorization date (Plaid only)",
    )

    description = serializers.CharField(help_text="Transaction description")
    merchant_name = serializers.CharField(allow_null=True, help_text="Merchant name")

    account = AccountSerializer(help_text="The account this transaction affects")
    category = AccountSerializer(
        allow_null=True,
        help_text="Category account (null if uncategorized)",
    )

    inflow = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Money coming in",
    )
    outflow = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Money going out",
    )

    is_pending = serializers.BooleanField(help_text="Whether transaction is pending")
    is_cleared = serializers.BooleanField(help_text="Whether transaction is cleared")

    payment_channel = serializers.CharField(
        allow_null=True,
        help_text="Payment channel (Plaid)",
    )
    confidence = serializers.CharField(
        allow_null=True,
        help_text="Categorization confidence",
    )

    journal_line_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of journal line (if ledger)",
    )
    imported_transaction_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of imported tx (if bank feed)",
    )

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

    # Derive is_cleared from reconciled_date (backwards compatible API)
    is_cleared = bool(line.reconciled_date) or line.is_cleared

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
        "is_cleared": is_cleared,
        "payment_channel": None,
        "confidence": "manual",
        "journal_line_id": line.id,
        "imported_transaction_id": None,
        "is_editable": True,
    }


def imported_tx_to_feed_row(tx: BankTransaction) -> dict:
    """
    Convert an BankTransaction to a BankFeedRow dict.
    Only called for uncategorized transactions (journal_entry is null).
    """
    amount = abs(tx.amount)

    # Plaid convention: positive = outflow, negative = inflow
    inflow = amount if tx.amount < 0 else Decimal("0")
    outflow = amount if tx.amount > 0 else Decimal("0")

    # Get account from plaid_account if available, otherwise None
    account = tx.plaid_account.account if tx.plaid_account else None

    return {
        "id": f"plaid-{tx.id}",
        "source": "plaid",
        "date": tx.date,
        "authorized_date": tx.authorized_date,
        "description": tx.name,
        "merchant_name": tx.merchant_name,
        "account": account,
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
