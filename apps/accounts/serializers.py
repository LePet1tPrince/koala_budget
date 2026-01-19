"""
Serializers for accounts app.
"""

from rest_framework import serializers

from .models import Account, AccountGroup, Payee


class AccountGroupSerializer(serializers.ModelSerializer):
    """Serializer for AccountGroup model."""

    class Meta:
        model = AccountGroup
        fields = [
            "id",
            "name",
            "account_type",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class AccountSerializer(serializers.ModelSerializer):
    """Serializer for Account model."""

    account_group_name = serializers.CharField(source="account_group.name", read_only=True)
    account_type = serializers.CharField(source="account_group.account_type", read_only=True)
    journal_lines = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "account_number",
            "account_group",
            "account_group_name",
            "account_type",
            "has_feed",
            "journal_lines",
            "balance",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["account_group_name", "account_type",
                            "created_at", "updated_at",
                            "journal_lines","account_balance"]


class PayeeSerializer(serializers.ModelSerializer):
    """Serializer for Payee model."""

    class Meta:
        model = Payee
        fields = ["id", "name", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
