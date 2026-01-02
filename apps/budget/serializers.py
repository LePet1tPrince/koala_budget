from rest_framework import serializers
from .models import Budget


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
