"""
Serializers for journal app.
Handles nested journal entries with lines for double-entry bookkeeping.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.accounts.models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    Payee,
)

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


class SimpleTransactionSerializer(serializers.Serializer):
    """
    Simplified transaction serializer for easy client-side usage.
    Converts between simple transaction format and journal entry format.

    Simple format:
    - date: transaction date
    - account: the account money is moving from/to (e.g., bank account)
    - category: the category account (e.g., groceries, salary)
    - amount: positive amount
    - description: transaction description
    - payee: optional payee ID

    This gets converted to a journal entry with 2 lines based on account types.
    """

    id = serializers.IntegerField(read_only=True)
    date = serializers.DateField()
    account = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.none(),  # Will be set in __init__
        help_text="The account money is moving from/to (e.g., bank account)",
    )
    category = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.none(),  # Will be set in __init__
        help_text="The category account (e.g., groceries, salary)",
    )
    amount = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal("0.01"))
    description = serializers.CharField(allow_blank=True)
    payee = serializers.PrimaryKeyRelatedField(
        queryset=Payee.objects.none(),  # Will be set in __init__
        required=False,
        allow_null=True,
    )

    # Read-only fields from journal entry
    account_name = serializers.CharField(read_only=True)
    category_name = serializers.CharField(read_only=True)
    payee_name = serializers.CharField(read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def __init__(self, *args, **kwargs):
        """Initialize with team context for querysets."""
        super().__init__(*args, **kwargs)
        # Get team from context
        request = self.context.get("request")
        if request and hasattr(request, "team"):
            self.fields["account"].queryset = Account.for_team.all()
            self.fields["category"].queryset = Account.for_team.all()
            self.fields["payee"].queryset = Payee.for_team.all()

    def _determine_debit_credit(self, account, category, amount):
        """
        Determine which account gets debited and which gets credited.

        Double-entry bookkeeping rules:
        - Assets increase with debits, decrease with credits
        - Liabilities increase with credits, decrease with debits
        - Income increases with credits, decreases with debits
        - Expenses increase with debits, decrease with credits
        - Equity increases with credits, decrease with debits

        For a simple transaction:
        - If spending money (expense): Debit expense, Credit asset
        - If receiving money (income): Debit asset, Credit income
        - If transferring between assets: Debit destination, Credit source
        - If paying off liability: Debit liability, Credit asset
        - If borrowing (liability): Debit asset, Credit liability
        """
        account_type = account.account_group.account_type
        category_type = category.account_group.account_type

        # Determine which line gets debit and which gets credit
        if category_type == ACCOUNT_TYPE_EXPENSE:
            # Spending money: Debit expense, Credit asset/liability
            return (category, account, amount, Decimal("0")), (account, category, Decimal("0"), amount)
        elif category_type == ACCOUNT_TYPE_INCOME:
            # Receiving money: Debit asset, Credit income
            return (account, category, amount, Decimal("0")), (category, account, Decimal("0"), amount)
        elif account_type == ACCOUNT_TYPE_ASSET and category_type == ACCOUNT_TYPE_ASSET:
            # Transfer between assets: Debit destination, Credit source
            return (category, account, amount, Decimal("0")), (account, category, Decimal("0"), amount)
        elif account_type == ACCOUNT_TYPE_ASSET and category_type == ACCOUNT_TYPE_LIABILITY:
            # Paying off liability: Debit liability, Credit asset
            return (category, account, amount, Decimal("0")), (account, category, Decimal("0"), amount)
        elif account_type == ACCOUNT_TYPE_LIABILITY and category_type == ACCOUNT_TYPE_ASSET:
            # Borrowing: Debit asset, Credit liability
            return (category, account, amount, Decimal("0")), (account, category, Decimal("0"), amount)
        else:
            # Default: treat category as the "to" account
            return (category, account, amount, Decimal("0")), (account, category, Decimal("0"), amount)

    def create(self, validated_data):
        """Create a journal entry from simple transaction data."""
        request = self.context.get("request")
        team = request.team

        account = validated_data["account"]
        category = validated_data["category"]
        amount = validated_data["amount"]

        # Determine debit/credit for each line
        line1_data, line2_data = self._determine_debit_credit(account, category, amount)

        # Create journal entry
        journal_entry = JournalEntry.objects.create(
            team=team,
            entry_date=validated_data["date"],
            description=validated_data["description"],
            payee=validated_data.get("payee"),
            source=JournalEntry.SOURCE_MANUAL,
            status=JournalEntry.STATUS_DRAFT,
        )

        # Create journal lines
        line1_account, _, line1_dr, line1_cr = line1_data
        line2_account, _, line2_dr, line2_cr = line2_data

        JournalLine.objects.create(
            journal_entry=journal_entry,
            team=team,
            account=line1_account,
            dr_amount=line1_dr,
            cr_amount=line1_cr,
        )

        JournalLine.objects.create(
            journal_entry=journal_entry,
            team=team,
            account=line2_account,
            dr_amount=line2_dr,
            cr_amount=line2_cr,
        )

        return journal_entry

    def update(self, instance, validated_data):
        """Update a journal entry from simple transaction data."""
        account = validated_data["account"]
        category = validated_data["category"]
        amount = validated_data["amount"]

        # Update journal entry fields
        instance.entry_date = validated_data["date"]
        instance.description = validated_data["description"]
        instance.payee = validated_data.get("payee")
        instance.save()

        # Delete existing lines
        instance.lines.all().delete()

        # Determine debit/credit for each line
        line1_data, line2_data = self._determine_debit_credit(account, category, amount)

        # Create new journal lines
        line1_account, _, line1_dr, line1_cr = line1_data
        line2_account, _, line2_dr, line2_cr = line2_data

        JournalLine.objects.create(
            journal_entry=instance,
            team=instance.team,
            account=line1_account,
            dr_amount=line1_dr,
            cr_amount=line1_cr,
        )

        JournalLine.objects.create(
            journal_entry=instance,
            team=instance.team,
            account=line2_account,
            dr_amount=line2_dr,
            cr_amount=line2_cr,
        )

        return instance

    def to_representation(self, instance):
        """Convert journal entry to simple transaction format."""
        # Get the two lines
        lines = list(instance.lines.all())
        if len(lines) != 2:
            # If not exactly 2 lines, can't represent as simple transaction
            # Return basic info
            return {
                "id": instance.id,
                "date": instance.entry_date,
                "description": instance.description,
                "amount": instance.total_debits,
                "status": instance.status,
                "created_at": instance.created_at,
                "updated_at": instance.updated_at,
            }

        # Determine which line is the account and which is the category
        # We'll use the account types to figure this out
        line1, line2 = lines
        account_line = None
        category_line = None

        # Try to identify which is the "main" account (asset/liability)
        # and which is the category (expense/income)
        line1_type = line1.account.account_group.account_type
        line2_type = line2.account.account_group.account_type

        if line1_type in [ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY]:
            account_line = line1
            category_line = line2
        elif line2_type in [ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY]:
            account_line = line2
            category_line = line1
        else:
            # Both are same type, just pick first as account
            account_line = line1
            category_line = line2

        return {
            "id": instance.id,
            "date": instance.entry_date,
            "account": account_line.account.account_id,
            "account_name": account_line.account.name,
            "category": category_line.account.account_id,
            "category_name": category_line.account.name,
            "amount": str(account_line.amount),
            "description": instance.description,
            "payee": instance.payee.id if instance.payee else None,
            "payee_name": instance.payee.name if instance.payee else None,
            "status": instance.status,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }


class SimpleLineSerializer(serializers.Serializer):
    """
    Simplified line serializer for journal lines.
    Presents journal lines in a transaction-like format with data from:
    - The journal line itself (account, inflow, outflow, is_cleared, is_reconciled)
    - The parent journal entry (date, description, payee, source)
    - The sibling journal line (category)

    This is designed for displaying transactions from the perspective of a single account,
    similar to a bank register view.

    For create/update operations:
    - date: transaction date
    - account: the account for this line
    - category: the account for the sibling line
    - inflow: debit amount (money coming in)
    - outflow: credit amount (money going out)
    - description: transaction description
    - payee: optional payee
    - is_cleared: whether the line is cleared
    - is_reconciled: whether the line is reconciled
    """

    line_id = serializers.IntegerField(read_only=True, source="id")
    journal_id = serializers.IntegerField(read_only=True, source="journal_entry.id")
    date = serializers.DateField()
    account = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.none(),  # Will be set in __init__
        help_text="The account for this line",
    )
    account_name = serializers.CharField(read_only=True, source="account.name")
    category = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.none(),  # Will be set in __init__
        help_text="The category account (for the sibling line)",
    )
    category_name = serializers.SerializerMethodField()
    inflow = serializers.DecimalField(
        max_digits=15, decimal_places=2, min_value=Decimal("0"), default=Decimal("0")
    )
    outflow = serializers.DecimalField(
        max_digits=15, decimal_places=2, min_value=Decimal("0"), default=Decimal("0")
    )
    description = serializers.CharField(allow_blank=True)
    payee = serializers.PrimaryKeyRelatedField(
        queryset=Payee.objects.none(),  # Will be set in __init__
        required=False,
        allow_null=True,
    )
    payee_name = serializers.SerializerMethodField()
    is_cleared = serializers.BooleanField(default=False)
    is_reconciled = serializers.BooleanField(default=False)
    source = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def __init__(self, *args, **kwargs):
        """Initialize with team context for querysets."""
        super().__init__(*args, **kwargs)
        # Get team from context
        request = self.context.get("request")
        if request and hasattr(request, "team"):
            self.fields["account"].queryset = Account.for_team.all()
            self.fields["category"].queryset = Account.for_team.all()
            self.fields["payee"].queryset = Payee.for_team.all()

    def validate(self, data):
        """Validate that exactly one of inflow or outflow is non-zero."""
        inflow = data.get("inflow", Decimal("0"))
        outflow = data.get("outflow", Decimal("0"))

        if inflow > 0 and outflow > 0:
            raise serializers.ValidationError("Cannot have both inflow and outflow. Use one or the other.")

        if inflow == 0 and outflow == 0:
            raise serializers.ValidationError("Must specify either inflow or outflow.")

        return data

    def get_category_name(self, obj):
        """Get the category account name from the sibling line."""
        sibling = self._get_sibling_line(obj)
        return sibling.account.name if sibling else None

    def get_payee_name(self, obj):
        """Get the payee name from the journal entry."""
        return obj.journal_entry.payee.name if obj.journal_entry.payee else None

    def _get_sibling_line(self, obj):
        """
        Get the sibling journal line (the other line in the journal entry).
        For a 2-line journal entry, returns the line that is not this one.
        For entries with more than 2 lines, returns None.
        """
        # Get all lines for this journal entry
        all_lines = list(obj.journal_entry.lines.all())

        # Only return sibling if there are exactly 2 lines
        if len(all_lines) == 2:
            # Return the line that is not this one
            return all_lines[0] if all_lines[1].id == obj.id else all_lines[1]

        return None

    def create(self, validated_data):
        """Create a journal entry with two lines from simple line data."""
        request = self.context.get("request")
        team = request.team

        account = validated_data["account"]
        category = validated_data["category"]
        inflow = validated_data.get("inflow", Decimal("0"))
        outflow = validated_data.get("outflow", Decimal("0"))

        # Create journal entry
        journal_entry = JournalEntry.objects.create(
            team=team,
            entry_date=validated_data["date"],
            description=validated_data["description"],
            payee=validated_data.get("payee"),
            source=JournalEntry.SOURCE_MANUAL,
            status=JournalEntry.STATUS_DRAFT,
        )

        # Create the main line (this account)
        main_line = JournalLine.objects.create(
            journal_entry=journal_entry,
            team=team,
            account=account,
            dr_amount=inflow,
            cr_amount=outflow,
            is_cleared=validated_data.get("is_cleared", False),
            is_reconciled=validated_data.get("is_reconciled", False),
        )

        # Create the sibling line (category account) with opposite amounts
        JournalLine.objects.create(
            journal_entry=journal_entry,
            team=team,
            account=category,
            dr_amount=outflow,  # Opposite of main line
            cr_amount=inflow,  # Opposite of main line
        )

        return main_line

    def update(self, instance, validated_data):
        """Update a journal entry and its lines from simple line data."""
        account = validated_data["account"]
        category = validated_data["category"]
        inflow = validated_data.get("inflow", Decimal("0"))
        outflow = validated_data.get("outflow", Decimal("0"))

        # Update journal entry fields
        journal_entry = instance.journal_entry
        journal_entry.entry_date = validated_data["date"]
        journal_entry.description = validated_data["description"]
        journal_entry.payee = validated_data.get("payee")
        journal_entry.save()

        # Update the main line
        instance.account = account
        instance.dr_amount = inflow
        instance.cr_amount = outflow
        instance.is_cleared = validated_data.get("is_cleared", False)
        instance.is_reconciled = validated_data.get("is_reconciled", False)
        instance.save()

        # Update or create the sibling line
        sibling = self._get_sibling_line(instance)
        if sibling:
            sibling.account = category
            sibling.dr_amount = outflow  # Opposite of main line
            sibling.cr_amount = inflow  # Opposite of main line
            sibling.save()
        else:
            # If no sibling exists, create one
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=instance.team,
                account=category,
                dr_amount=outflow,
                cr_amount=inflow,
            )

        return instance

    def to_representation(self, instance):
        """Convert journal line to simple line format."""
        # Get the sibling line for category
        sibling = self._get_sibling_line(instance)

        return {
            "line_id": instance.id,
            "journal_id": instance.journal_entry.id,
            "date": instance.journal_entry.entry_date,
            "account": instance.account.account_id,
            "account_name": instance.account.name,
            "category": sibling.account.account_id if sibling else None,
            "category_name": sibling.account.name if sibling else None,
            "inflow": instance.dr_amount,
            "outflow": instance.cr_amount,
            "description": instance.journal_entry.description,
            "payee": instance.journal_entry.payee.id if instance.journal_entry.payee else None,
            "payee_name": instance.journal_entry.payee.name if instance.journal_entry.payee else None,
            "is_cleared": instance.is_cleared,
            "is_reconciled": instance.is_reconciled,
            "source": instance.journal_entry.source,
            "status": instance.journal_entry.status,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }
