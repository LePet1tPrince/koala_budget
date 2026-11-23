"""
Request and response shapes of the YNAB import API (`/a/{team}/{book}/ynab-import/api/...`).

The responses are what `services.payload` builds from an `Analysis` and an
`ImportPlan`; the shapes are declared here so the generated client types them.
The wizard's `choices` are read by `services.build.parse_choices`, which ignores
anything it does not recognise, so they travel as JSON.
"""

from rest_framework import serializers

from apps.api.base import UploadField
from apps.utils.progress_serializers import ImportStartedFields, ImportStatusSerializer

MONEY = {"max_digits": 15, "decimal_places": 2}

CHOICES_HELP = (
    "The wizard's answers: `{accounts: {<name>: {...}}, income: {<payee>: {...}}, categories: {<key>: {...}}}`. "
    "Anything not recognised is ignored."
)


# --- what the export holds ---------------------------------------------------------


class YnabAccountSerializer(serializers.Serializer):
    name = serializers.CharField()
    account_type = serializers.CharField(help_text="What it was inferred to be: asset or liability.")
    group = serializers.CharField(help_text="The account group it was inferred to belong in.")
    on_budget = serializers.BooleanField()
    rows = serializers.IntegerField(help_text="Register rows on the account.")
    reason = serializers.CharField(allow_blank=True, help_text="Why it was given that type.")
    closing_balance = serializers.DecimalField(**MONEY)
    starting_balance = serializers.DecimalField(**MONEY, allow_null=True)
    first_date = serializers.DateField()
    last_date = serializers.DateField()
    has_feed = serializers.BooleanField(help_text="Suggested as a bank-feed account.")


class YnabIncomeSerializer(serializers.Serializer):
    payee = serializers.CharField(allow_blank=True)
    label = serializers.CharField(help_text="The payee, or “(no payee)”.")
    count = serializers.IntegerField()
    total = serializers.DecimalField(**MONEY)
    kind = serializers.CharField(help_text="What the payee's inflows were read as.")
    account = serializers.CharField(allow_blank=True, help_text="The income account they land in.")


class YnabCategorySerializer(serializers.Serializer):
    key = serializers.CharField(help_text="`<group>: <name>`; the key in `choices.categories`.")
    group = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.CharField(help_text="expense, or a savings category that can become a goal.")
    transfer_legs = serializers.IntegerField()
    plain_rows = serializers.IntegerField()
    saved = serializers.DecimalField(**MONEY)


class YnabGroupSerializer(serializers.Serializer):
    name = serializers.CharField()
    account_type = serializers.CharField()


# --- what the import will make -----------------------------------------------------


class YnabChartGroupSerializer(serializers.Serializer):
    name = serializers.CharField()
    accounts = serializers.ListField(child=serializers.CharField(), help_text="Account names.")


class YnabChartSectionSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="asset, liability, income, expense or equity.")
    label = serializers.CharField()
    groups = YnabChartGroupSerializer(many=True)


class YnabGoalSerializer(serializers.Serializer):
    name = serializers.CharField()
    target = serializers.DecimalField(**MONEY)
    months = serializers.IntegerField(help_text="Months of allocations it carries.")


class YnabPlanSerializer(serializers.Serializer):
    summary = serializers.JSONField(help_text="The counts the preview reports (`rows`, `entries`, `accounts`, ...).")
    notes = serializers.ListField(child=serializers.CharField(), help_text="Everything the import decided for you.")
    chart = YnabChartSectionSerializer(many=True, help_text="The chart of accounts it will create.")
    goals = YnabGoalSerializer(many=True)


class YnabUploadResultSerializer(YnabPlanSerializer):
    import_id = serializers.IntegerField()
    can_import = serializers.BooleanField(help_text="The book is empty enough to import into.")
    accounts = YnabAccountSerializer(many=True)
    income = YnabIncomeSerializer(many=True)
    categories = YnabCategorySerializer(many=True, help_text="Only the categories with a decision to make.")
    groups = YnabGroupSerializer(many=True, help_text="The account groups the accounts screen offers.")
    income_accounts = serializers.ListField(child=serializers.CharField())
    other_income = serializers.CharField(help_text="Where a payee switched back to income lands by default.")


class YnabReconciliationCheckSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()
    passed = serializers.BooleanField()
    checked = serializers.IntegerField()
    mismatched = serializers.IntegerField()
    detail = serializers.CharField(allow_blank=True)
    samples = serializers.ListField(child=serializers.CharField())


class YnabReconciliationSerializer(serializers.Serializer):
    passed = serializers.BooleanField()
    export_month = serializers.DateField(allow_null=True)
    checks = YnabReconciliationCheckSerializer(many=True)


class YnabPreviewResultSerializer(YnabPlanSerializer):
    import_id = serializers.IntegerField()
    reconciliation = YnabReconciliationSerializer(help_text="The import checked against YNAB's own numbers.")


# --- requests ----------------------------------------------------------------------


class YnabUploadRequestSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=UploadField(),
        help_text="Both CSVs of a YNAB export, the register and the plan, in either order.",
    )


class YnabChoicesRequestSerializer(serializers.Serializer):
    import_id = serializers.IntegerField()
    choices = serializers.JSONField(required=False, default=dict, help_text=CHOICES_HELP)


# --- the page and the import itself ------------------------------------------------


class YnabStatusSerializer(ImportStatusSerializer):
    pass


class YnabStartedSerializer(ImportStartedFields, YnabStatusSerializer):
    pass


class YnabPageSerializer(serializers.Serializer):
    book_name = serializers.CharField()
    can_import = serializers.BooleanField(help_text="False once the book has transactions.")
    resume = YnabStatusSerializer(
        allow_null=True, help_text="An import still running, or one that finished or failed in the last day."
    )
