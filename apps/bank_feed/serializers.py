"""
Serializers for bank_feed app.
Provides serializers for BankTransaction and adapter functions for bank feed rows.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.accounts.serializers import AccountSerializer
from apps.journal.models import JournalLine
from apps.plaid.serializers import PlaidTransactionSerializer

from .models import BankTransaction

class BankTransactionSerializer(serializers.ModelSerializer):
    """Serializer for BankTransaction model."""

    # Nested PlaidTransaction details (accessed via reverse relation)
    plaid_transaction = PlaidTransactionSerializer(read_only=True)
    is_categorized = serializers.BooleanField(read_only=True)

    # Computed fields from PlaidTransaction (if it exists)
    pending = serializers.SerializerMethodField()
    plaid_category = serializers.SerializerMethodField()
    plaid_category_confidence = serializers.SerializerMethodField()
    payment_channel = serializers.SerializerMethodField()

    class Meta:
        model = BankTransaction
        fields = [
            "id",
            "source",
            "amount",
            "account",
            "posted_date",
            "pending",
            "description",
            "merchant_name",
            "plaid_category",
            "plaid_category_confidence",
            "payment_channel",
            "journal_entry",
            "is_categorized",
            "plaid_transaction",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_pending(self, obj):
        """Get pending status from PlaidTransaction if it exists."""
        if hasattr(obj, "plaid_transaction"):
            return obj.plaid_transaction.pending
        return False

    def get_plaid_category(self, obj):
        """Get Plaid category from PlaidTransaction if it exists."""
        if hasattr(obj, "plaid_transaction"):
            return obj.plaid_transaction.personal_finance_category
        return None

    def get_plaid_category_confidence(self, obj):
        """Get Plaid category confidence from PlaidTransaction if it exists."""
        if hasattr(obj, "plaid_transaction"):
            return obj.plaid_transaction.category_confidence
        return None

    def get_payment_channel(self, obj):
        """Get payment channel from PlaidTransaction if it exists."""
        if hasattr(obj, "plaid_transaction"):
            return obj.plaid_transaction.payment_channel
        return None


class TransactionRowSerializer(serializers.Serializer):
    """Serializer for a transaction row in categorize request."""

    id = serializers.IntegerField(help_text="Transaction ID")


class CategorizeTransactionsRequestSerializer(serializers.Serializer):
    """Serializer for categorize transactions request body."""

    rows = TransactionRowSerializer(many=True, help_text="List of transactions to categorize")
    category_account_id = serializers.IntegerField(help_text="ID of the category account")


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
        "payment_channel": None,
        "confidence": "manual",
        "journal_line_id": line.id,
        "imported_transaction_id": None,
        "is_editable": True,
    }


def bank_transaction_to_feed_row(tx: BankTransaction) -> dict:
    """
    Convert a BankTransaction to a BankFeedRow dict.
    Shows BankTransaction data + category from JournalEntry if categorized.
    """
    amount = abs(tx.amount)

    # Plaid convention: positive = outflow, negative = inflow
    inflow = amount if tx.amount < 0 else Decimal("0")
    outflow = amount if tx.amount > 0 else Decimal("0")

    # Get Plaid-specific fields from the related PlaidTransaction if it exists
    plaid_tx = getattr(tx, "plaid_transaction", None)
    authorized_date = plaid_tx.authorized_date if plaid_tx else None
    is_pending = plaid_tx.pending if plaid_tx else False
    payment_channel = plaid_tx.payment_channel if plaid_tx else None
    category_confidence = plaid_tx.category_confidence if plaid_tx else None

    # Get category from JournalEntry if categorized
    category = None
    if tx.journal_entry:
        # Find the category account (the one that's not the bank account)
        for line in tx.journal_entry.lines.all():
            if line.account != tx.account:
                category = line.account
                break

    return {
        "id": f"{tx.source}-{tx.id}",
        "source": tx.source,
        "date": tx.posted_date,
        "authorized_date": authorized_date,
        "description": tx.description,
        "merchant_name": tx.merchant_name,
        "account": tx.account,
        "category": category,
        "inflow": inflow,
        "outflow": outflow,
        "is_pending": is_pending,
        "is_cleared": bool(tx.journal_entry),  # If categorized, consider it cleared
        "payment_channel": payment_channel,
        "confidence": "manual" if tx.journal_entry else category_confidence,
        "journal_line_id": None,
        "imported_transaction_id": tx.id,
        "is_editable": not tx.journal_entry,  # Can't edit categorized transactions
    }
