from rest_framework import serializers
from .models import Budget
from apps.journal.models import JournalLine
from apps.journal.serializers import JournalLineSerializer
from apps.accounts.serializers import AccountSerializer

# class BudgetBaseSerializer(serializers.ModelSerializer):
#     actual_amount = serializers.DecimalField(
#         max_digits=15,
#         decimal_places=2,
#         read_only=True,
#     )
#     available = serializers.SerializerMethodField()

#     category = AccountSerializer()
#     category_name = serializers.CharField(
#         source="category.name",
#         read_only=True,
#     )

#     journal_lines = JournalLineSerializer(
#         many=True,
#         read_only=True,
#     )

#     class Meta:
#         model = Budget
#         fields = [
#             "id",
#             "month",
#             "category",
#             "category_name",
#             "budget_amount",
#             "actual_amount",
#             "available",

#         ]
#         read_only_fields = [
#             "actual_amount",
#             "category_name"
#             "available",
#         ]

#     def get_available(self, obj):
#         # Requires queryset annotated with with_actual_amount()
#         return obj.budget_amount - obj.actual_amount


# class BudgetListSerializer(BudgetBaseSerializer):
#     class Meta(BudgetBaseSerializer.Meta):
#         pass


# class BudgetUpdateSerializer(BudgetBaseSerializer):
#     class Meta(BudgetBaseSerializer.Meta):
#         read_only_fields = (
#             "month",
#             "category",
#             "actual_amount",
#             "available",
#         )


class BudgetSerializer(serializers.ModelSerializer):
    category_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Budget
        fields = [
            "id",
            "category_id",
            "month",
            "budget_amount",
        ]

    def create(self, validated_data):
        team = self.context["request"].team

        budget, _ = Budget.objects.update_or_create(
            team=team,
            category_id=validated_data["category_id"],
            month=validated_data["month"],
            defaults={
                "budget_amount": validated_data["budget_amount"],
            },
        )

        return budget
