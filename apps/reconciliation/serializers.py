"""Request bodies for the reconciliation API. Responses are built by `presenters`."""

from rest_framework import serializers

from apps.accounts.serializers import PayeeSerializer, PickerAccountSerializer

#: Abuse ceiling for one tick request; "Tick all through" is the bulk path.
MAX_TICK_IDS = 5000


class ReconciliationStartSerializer(serializers.Serializer):
    account = serializers.IntegerField(help_text="Asset or liability account id")
    statement_date = serializers.DateField()
    statement_balance = serializers.DecimalField(
        max_digits=15, decimal_places=2, help_text="Closing balance as printed on the statement"
    )
    line_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list, max_length=MAX_TICK_IDS
    )


class ReconciliationUpdateSerializer(serializers.Serializer):
    statement_date = serializers.DateField(required=False)
    statement_balance = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)


class ReconciliationTickSerializer(serializers.Serializer):
    line_ids = serializers.ListField(child=serializers.IntegerField(), max_length=MAX_TICK_IDS)
    ticked = serializers.BooleanField()


class ReconciliationTickThroughSerializer(serializers.Serializer):
    date = serializers.DateField()


class ReconciliationFinishSerializer(serializers.Serializer):
    adjust = serializers.BooleanField(default=False)
    expected_difference = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, allow_null=True)


# Responses. The payloads are built by `presenters`; these describe them for the
# OpenAPI schema (and the generated client). Amounts are decimal strings in
# STATEMENT sign.


class ReconcileAccountSerializer(serializers.Serializer):
    """An account as the reconciliation pages name it (`presenters.account_payload`)."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    type = serializers.CharField(help_text="The account type: asset or liability")
    is_liability = serializers.BooleanField()
    has_feed = serializers.BooleanField()


class StatementSerializer(serializers.Serializer):
    """A statement's header, without its lines (`presenters.statement_payload`)."""

    id = serializers.IntegerField()
    status = serializers.CharField(help_text="draft, completed or undone")
    statement_date = serializers.DateField()
    statement_balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    adjustment_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    completed_at = serializers.DateTimeField(allow_null=True)
    completed_by = serializers.CharField(allow_null=True, help_text="Who finished it")
    undone_at = serializers.DateTimeField(allow_null=True)
    intact = serializers.BooleanField(
        allow_null=True, help_text="Whether every line it locked is still reconciled (null when not asked)"
    )
    url = serializers.CharField(help_text="The statement's page")
    cleared_total = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)
    opening_balance = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)


class StatementLineSerializer(serializers.Serializer):
    """One ledger line a statement locked (`presenters.line_payload`, plus `moved`)."""

    id = serializers.IntegerField()
    entry_id = serializers.IntegerField()
    date = serializers.DateField()
    payee = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    category = serializers.CharField(allow_blank=True)
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    ticked = serializers.BooleanField()
    has_feed_row = serializers.BooleanField()
    source = serializers.CharField()
    after_statement = serializers.BooleanField()
    moved = serializers.BooleanField(help_text="No longer reconciled since the statement was finished")


class CompletedStatementSerializer(StatementSerializer):
    """A finished (or undone) statement and every line it locked -- the statement page."""

    account = ReconcileAccountSerializer()
    lines = StatementLineSerializer(many=True)


class HubAccountSerializer(ReconcileAccountSerializer):
    """A reconcilable account on the hub, with where it stands."""

    balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    reconciled_balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    last_statement = StatementSerializer(allow_null=True)
    draft = StatementSerializer(allow_null=True)
    url = serializers.CharField(help_text="The account's reconcile page")


class ReconciliationHubSerializer(serializers.Serializer):
    """Every reconcilable account and where it stands -- the hub."""

    accounts = HubAccountSerializer(many=True)
    all_intact = serializers.BooleanField(help_text="Every account has a finished statement that still holds")


class ReconcileAccountPageSerializer(serializers.Serializer):
    """What one account's reconcile page opens on."""

    account = ReconcileAccountSerializer()
    draft_id = serializers.IntegerField(allow_null=True, help_text="The open draft, if one is in progress")
    default_statement_date = serializers.DateField(help_text="Month-end after the last statement")
    previous = StatementSerializer(allow_null=True, help_text="The last finished statement")
    reconciled_balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    history = StatementSerializer(many=True)
    all_accounts = PickerAccountSerializer(
        many=True, help_text="The feed's category picker, for adding a missing transaction (empty without a feed)"
    )
    all_payees = PayeeSerializer(many=True, help_text="The feed's payees (empty for an account with no feed)")
