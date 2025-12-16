"""
Serializers for budgeting app.
Keep these simple - just data transformation, no business logic.
"""

from rest_framework import serializers

from .models import Account, AccountType, Budget, Goal, Payee, Transaction


class AccountTypeSerializer(serializers.ModelSerializer):
    """Serializer for AccountType model."""

    class Meta:
        model = AccountType
        fields = [
            "id",
            "type_name",
            "subtype_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class AccountSerializer(serializers.ModelSerializer):
    """Serializer for Account model."""

    account_balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    account_type_name = serializers.CharField(source="account_type.type_name", read_only=True)
    subtype_name = serializers.CharField(source="subtype.subtype_name", read_only=True)

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "account_number",
            "account_type",
            "account_type_name",
            "subtype",
            "subtype_name",
            "has_feed",
            "account_balance",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["account_balance", "account_type_name", "subtype_name", "created_at", "updated_at"]


class PayeeSerializer(serializers.ModelSerializer):
    """Serializer for Payee model."""

    class Meta:
        model = Payee
        fields = ["id", "name", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for Transaction model."""

    payee_name = serializers.CharField(source="payee.name", read_only=True, allow_null=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    account_number = serializers.IntegerField(source="account.account_number", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, allow_null=True)
    category_number = serializers.IntegerField(source="category.account_number", read_only=True, allow_null=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "date_posted",
            "amount",
            "payee",
            "payee_name",
            "account",
            "account_name",
            "account_number",
            "category",
            "category_name",
            "category_number",
            "notes",
            "imported_on",
            "import_method",
            "status",
            "is_cleared",
            "is_reconciled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "payee_name",
            "account_name",
            "account_number",
            "category_name",
            "category_number",
            "created_at",
            "updated_at",
        ]


class BudgetSerializer(serializers.ModelSerializer):
    """Serializer for Budget model."""

    category_name = serializers.CharField(source="category.name", read_only=True)
    actual = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    available = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = Budget
        fields = [
            "id",
            "month",
            "category",
            "category_name",
            "budget",
            "actual",
            "available",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["actual", "available", "category_name", "created_at", "updated_at"]


class GoalSerializer(serializers.ModelSerializer):
    """Serializer for Goal model."""

    class Meta:
        model = Goal
        fields = [
            "id",
            "name",
            "description",
            "target_amount",
            "saved_amount",
            "remaining_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["remaining_amount", "created_at", "updated_at"]


# Serializers for reports
class IncomeExpenseReportSerializer(serializers.Serializer):
    """Serializer for income/expense report data."""

    income = serializers.ListField(child=serializers.DictField())
    expenses = serializers.ListField(child=serializers.DictField())
    total_income = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_expenses = serializers.DecimalField(max_digits=15, decimal_places=2)
    net = serializers.DecimalField(max_digits=15, decimal_places=2)
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class BalanceSheetReportSerializer(serializers.Serializer):
    """Serializer for balance sheet report data."""

    assets = serializers.ListField(child=serializers.DictField())
    liabilities = serializers.ListField(child=serializers.DictField())
    equity = serializers.ListField(child=serializers.DictField())
    total_assets = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_liabilities = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_equity = serializers.DecimalField(max_digits=15, decimal_places=2)
    net_worth = serializers.DecimalField(max_digits=15, decimal_places=2)


class BudgetPerformanceReportSerializer(serializers.Serializer):
    """Serializer for budget performance report data."""

    month = serializers.DateField()
    budgets = serializers.ListField(child=serializers.DictField())
    total_budgeted = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_actual = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_available = serializers.DecimalField(max_digits=15, decimal_places=2)
