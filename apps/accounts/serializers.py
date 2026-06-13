"""
Serializers for accounts app.
"""

from rest_framework import serializers

from .models import Account, AccountGroup, Institution, Payee


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
            "is_archived",
            "archived_at",
        ]
        read_only_fields = ["created_at", "updated_at", "archived_at"]


class AccountSerializer(serializers.ModelSerializer):
    """Serializer for Account model."""

    account_group_name = serializers.CharField(source="account_group.name", read_only=True)
    account_type = serializers.CharField(source="account_group.account_type", read_only=True)
    institution_name = serializers.CharField(source="institution.name", read_only=True, default=None)
    balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    reconciled_balance = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "account_group",
            "account_group_name",
            "account_type",
            "institution",
            "institution_name",
            "has_feed",
            "balance",
            "reconciled_balance",
            "created_at",
            "updated_at",
            "is_archived",
            "archived_at",
        ]
        read_only_fields = [
            "account_group_name",
            "account_type",
            "institution_name",
            "created_at",
            "updated_at",
            "balance",
            "reconciled_balance",
            "archived_at",
        ]

    def get_reconciled_balance(self, obj) -> str | None:
        """Get reconciled_balance from annotation if available."""
        if hasattr(obj, "_reconciled_balance"):
            return str(obj._reconciled_balance)
        return None


class SimpleAccountSerializer(serializers.ModelSerializer):
    """Serializer for Account model."""

    account_group_name = serializers.CharField(source="account_group.name", read_only=True)
    account_type = serializers.CharField(source="account_group.account_type", read_only=True)
    institution_name = serializers.CharField(source="institution.name", read_only=True, default=None)

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "account_group",
            "account_group_name",
            "account_type",
            "institution_name",
            "has_feed",
            "is_archived",
            "archived_at",
        ]
        read_only_fields = ["account_group_name", "account_type", "institution_name", "archived_at"]


class InstitutionSerializer(serializers.ModelSerializer):
    """Serializer for Institution model."""

    class Meta:
        model = Institution
        fields = ["id", "name", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class PayeeSerializer(serializers.ModelSerializer):
    """Serializer for Payee model."""

    class Meta:
        model = Payee
        fields = ["id", "name", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
