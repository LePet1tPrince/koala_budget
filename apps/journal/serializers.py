"""
Serializers for journal app.
Handles nested journal entries with lines for double-entry bookkeeping.
"""

from decimal import Decimal

from rest_framework import serializers

from .models import JournalEntry, JournalLine


class JournalLineSerializer(serializers.ModelSerializer):
    """Serializer for JournalLine model with nested account details."""

    account_name = serializers.CharField(source="account.name", read_only=True)
    account_number = serializers.IntegerField(source="account.account_number", read_only=True)
    amount = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = JournalLine
        fields = [
            "id",
            "account",
            "account_name",
            "account_number",
            "dr_amount",
            "cr_amount",
            "amount",
            "is_cleared",
            "is_reconciled",
            # "budget",  # Uncomment when Budget model is ready
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["account_name", "account_number", "amount", "created_at", "updated_at"]

    def validate(self, data):
        """Validate that line has either debit or credit, not both or neither."""
        dr_amount = data.get("dr_amount", Decimal("0"))
        cr_amount = data.get("cr_amount", Decimal("0"))

        # Check that we don't have both debit and credit
        if dr_amount > 0 and cr_amount > 0:
            raise serializers.ValidationError("A journal line cannot have both debit and credit amounts.")

        # Check that we have at least one amount
        if dr_amount == 0 and cr_amount == 0:
            raise serializers.ValidationError("A journal line must have either a debit or credit amount.")

        # Ensure amounts are not negative
        if dr_amount < 0 or cr_amount < 0:
            raise serializers.ValidationError("Debit and credit amounts cannot be negative.")

        return data


class JournalEntrySerializer(serializers.ModelSerializer):
    """
    Serializer for JournalEntry model with nested lines.
    Supports creating/updating journal entries with lines in a single request.
    """

    lines = JournalLineSerializer(many=True)
    payee_name = serializers.CharField(source="payee.name", read_only=True, allow_null=True)
    total_debits = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_credits = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    is_balanced = serializers.BooleanField(read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            "id",
            "entry_date",
            "payee",
            "payee_name",
            "description",
            "source",
            "status",
            "lines",
            "total_debits",
            "total_credits",
            "is_balanced",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["payee_name", "total_debits", "total_credits", "is_balanced", "created_at", "updated_at"]

    def validate_lines(self, lines):
        """Validate that at least 2 lines are provided."""
        if len(lines) < 2:
            raise serializers.ValidationError("A journal entry must have at least 2 lines.")
        return lines

    def validate(self, data):
        """Validate that total debits equal total credits."""
        lines = data.get("lines", [])

        total_debits = sum(line.get("dr_amount", Decimal("0")) for line in lines)
        total_credits = sum(line.get("cr_amount", Decimal("0")) for line in lines)

        if total_debits != total_credits:
            raise serializers.ValidationError(
                {
                    "lines": f"Journal entry must balance. Total debits: {total_debits}, Total credits: {total_credits}"
                }
            )

        return data

    def create(self, validated_data):
        """Create journal entry with nested lines."""
        lines_data = validated_data.pop("lines")
        journal_entry = JournalEntry.objects.create(**validated_data)

        for line_data in lines_data:
            JournalLine.objects.create(journal_entry=journal_entry, team=journal_entry.team, **line_data)

        return journal_entry

    def update(self, instance, validated_data):
        """Update journal entry and replace all lines."""
        lines_data = validated_data.pop("lines", None)

        # Update journal entry fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # If lines data is provided, replace all existing lines
        if lines_data is not None:
            # Delete existing lines
            instance.lines.all().delete()

            # Create new lines
            for line_data in lines_data:
                JournalLine.objects.create(journal_entry=instance, team=instance.team, **line_data)

        return instance

