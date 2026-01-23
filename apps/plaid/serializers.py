"""
Serializers for Plaid app.
"""

from rest_framework import serializers

from apps.accounts.serializers import AccountSerializer

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
