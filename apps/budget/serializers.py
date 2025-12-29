from rest_framework import serializers
from .models import Budget
from apps.journal.models import JournalLine
from apps.journal.serializers import JournalLineSerializer
from apps.accounts.serializers import AccountSerializer

class BudgetBaseSerializer(serializers.ModelSerializer):
    actual_amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        read_only=True,
    )
    available = serializers.SerializerMethodField()

    category = AccountSerializer()
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )

    journal_lines = JournalLineSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = Budget
        fields = [
            "id",
            "month",
            "category",
            "category_name",
            "budget_amount",
            "actual_amount",
            "available",

        ]
        read_only_fields = [
            "actual_amount",
            "category_name"
            "available",
        ]

    def get_available(self, obj):
        # Requires queryset annotated with with_actual_amount()
        return obj.budget_amount - obj.actual_amount


class BudgetListSerializer(BudgetBaseSerializer):
    class Meta(BudgetBaseSerializer.Meta):
        pass


class BudgetUpdateSerializer(BudgetBaseSerializer):
    class Meta(BudgetBaseSerializer.Meta):
        read_only_fields = (
            "month",
            "category",
            "actual_amount",
            "available",
        )
