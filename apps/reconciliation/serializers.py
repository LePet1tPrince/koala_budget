"""Request bodies for the reconciliation API. Responses are built by `presenters`."""

from rest_framework import serializers

#: Abuse ceiling for one tick request; "Tick all through" is the bulk path.
MAX_TICK_IDS = 5000


class StartSerializer(serializers.Serializer):
    account = serializers.IntegerField(help_text="Asset or liability account id")
    statement_date = serializers.DateField()
    statement_balance = serializers.DecimalField(
        max_digits=15, decimal_places=2, help_text="Closing balance as printed on the statement"
    )
    line_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list, max_length=MAX_TICK_IDS
    )


class UpdateSerializer(serializers.Serializer):
    statement_date = serializers.DateField(required=False)
    statement_balance = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)


class TickSerializer(serializers.Serializer):
    line_ids = serializers.ListField(child=serializers.IntegerField(), max_length=MAX_TICK_IDS)
    ticked = serializers.BooleanField()


class TickThroughSerializer(serializers.Serializer):
    date = serializers.DateField()


class FinishSerializer(serializers.Serializer):
    adjust = serializers.BooleanField(default=False)
    expected_difference = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, allow_null=True)
