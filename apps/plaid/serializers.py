"""
Serializers for Plaid app.
"""

from rest_framework import serializers

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY, Account
from apps.accounts.serializers import AccountSerializer

from .models import PlaidAccount, PlaidItem, PlaidTransaction


class PlaidItemSerializer(serializers.ModelSerializer):
    """Serializer for PlaidItem model."""

    needs_attention = serializers.BooleanField(read_only=True)

    class Meta:
        model = PlaidItem
        fields = [
            "id",
            "plaid_item_id",
            "institution_name",
            "last_synced_at",
            "status",
            "error_code",
            "error_message",
            "consent_expiration_time",
            "new_accounts_available",
            "needs_attention",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "last_synced_at",
            "status",
            "error_code",
            "error_message",
            "consent_expiration_time",
            "new_accounts_available",
            "created_at",
            "updated_at",
        ]


class PlaidAccountSerializer(serializers.ModelSerializer):
    """Serializer for PlaidAccount model."""

    is_foreign_currency = serializers.BooleanField(read_only=True)

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
            "iso_currency_code",
            "is_foreign_currency",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["iso_currency_code", "is_foreign_currency", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scope writable FKs to the current book so a PATCH can't link a Plaid
        # account to another tenant's ledger account or item
        request = self.context.get("request")
        if request is not None and getattr(request, "book", None):
            self.fields["account"].queryset = Account.for_book.exclude_budget_buckets()
            self.fields["item"].queryset = PlaidItem.for_book.all()

    def validate_account(self, account):
        """
        A bank account feeds an asset or liability, and only one bank account
        feeds it: two would deliver every transaction twice.
        """
        if account is None:
            return account
        if account.is_system or account.account_group.account_type not in (
            ACCOUNT_TYPE_ASSET,
            ACCOUNT_TYPE_LIABILITY,
        ):
            raise serializers.ValidationError("A bank account can only feed an asset or liability account.")
        taken = PlaidAccount.objects.filter(account=account)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError(f"{account.name} is already fed by another bank account.")
        return account

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        # A mapped account's transactions land in the Inbox, which lists only
        # accounts with a feed -- without this they would arrive and be invisible.
        account = instance.account
        if account is not None and not account.has_feed:
            account.has_feed = True
            account.save(update_fields=["has_feed", "updated_at"])
        return instance


class LinkTokenResponseSerializer(serializers.Serializer):
    link_token = serializers.CharField()


class ItemRefreshResponseSerializer(serializers.Serializer):
    """After update mode: the bank's accounts this app hadn't seen, to be mapped."""

    item = PlaidItemSerializer()
    new_accounts = PlaidAccountSerializer(many=True)


class ExchangePublicTokenResponseSerializer(serializers.Serializer):
    """What linking a bank returns: the new item and the accounts to map."""

    success = serializers.BooleanField()
    item_id = serializers.IntegerField()
    accounts = PlaidAccountSerializer(many=True)


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
