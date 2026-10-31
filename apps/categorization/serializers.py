from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.guards import assert_category_allowed
from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY, Account

from .actions import ACTIONS, decisions_from_rule, describe
from .matching import RuleConditionError, compile_rule
from .models import CategorizationRule
from .rule_names import unique_rule_name


class CategorizationRuleSerializer(serializers.ModelSerializer):
    """
    A rule, read and written. Account and category are ids from the URL's book;
    the conditions are compiled on validation, so a rule that could match
    everything (or nothing) never saves.
    """

    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    category = serializers.PrimaryKeyRelatedField(queryset=Account.objects.none(), allow_null=False)
    account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.none(), allow_null=True, required=False)
    category_name = serializers.SerializerMethodField()
    account_name = serializers.SerializerMethodField()
    problem = serializers.SerializerMethodField()
    applied_count = serializers.SerializerMethodField()
    action_summary = serializers.SerializerMethodField()

    class Meta:
        model = CategorizationRule
        fields = [
            "id",
            "name",
            "priority",
            "is_enabled",
            "mode",
            "payee_match",
            "payee_value",
            "description_match",
            "description_value",
            "amount_min",
            "amount_max",
            "direction",
            "account",
            "account_name",
            "category",
            "category_name",
            *(action.rule_field for action in ACTIONS),
            "problem",
            "applied_count",
            "action_summary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["priority", "created_at", "updated_at"]
        # `unique_together` is checked by `validate_name` against the URL's book.
        validators = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        book = self.context.get("book")
        if book is not None:
            accounts = Account.objects.filter(book=book).exclude_budget_buckets().select_related("account_group")
            self.fields["category"].queryset = accounts
            self.fields["account"].queryset = accounts.filter(
                account_group__account_type__in=(ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)
            )

    def get_category_name(self, obj) -> str:
        return obj.category.name if obj.category_id else ""

    def get_account_name(self, obj) -> str:
        return obj.account.name if obj.account_id else ""

    def get_problem(self, obj) -> str:
        return obj.problem if obj.pk else ""

    def get_applied_count(self, obj) -> int:
        return getattr(obj, "applied_count", 0) or 0

    def get_action_summary(self, obj) -> list[str]:
        return describe(decisions_from_rule(obj))

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            return value
        book = self.context["book"]
        clash = CategorizationRule.objects.filter(book=book, name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(_("You already have a rule named “%(name)s”.") % {"name": value})
        return value

    def validate_category(self, category):
        if category.is_archived:
            raise serializers.ValidationError(_("“%(name)s” is archived.") % {"name": category.name})
        try:
            assert_category_allowed(category)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from None
        return category

    def validate(self, attrs):
        merged = {**self._current(), **attrs}
        candidate = CategorizationRule(
            **{key: value for key, value in merged.items() if key not in {"account", "category"}},
            account=merged.get("account"),
            category=merged.get("category"),
        )
        try:
            compile_rule(candidate)
        except RuleConditionError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from None
        if candidate.category_id and candidate.account_id and candidate.category_id == candidate.account_id:
            raise serializers.ValidationError(
                {"category": [_("A rule can't categorize transactions to the account they are in.")]}
            )
        for action in ACTIONS:
            if action.rule_field in attrs:
                attrs[action.rule_field] = (attrs[action.rule_field] or "").strip()
        if not merged.get("name"):
            attrs["name"] = unique_rule_name(
                self.context["book"], candidate, exclude_id=self.instance.pk if self.instance else None
            )
        return attrs

    def _current(self):
        if self.instance is None:
            return {}
        return {
            field: getattr(self.instance, field)
            for field in (
                "name",
                "mode",
                "is_enabled",
                "payee_match",
                "payee_value",
                "description_match",
                "description_value",
                "amount_min",
                "amount_max",
                "direction",
                "account",
                "category",
                *(action.rule_field for action in ACTIONS),
            )
        }


class RulePreviewRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    posted_date = serializers.DateField()
    description = serializers.CharField()
    payee = serializers.CharField(allow_blank=True)
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    account_name = serializers.CharField(allow_blank=True)


class RulePreviewSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Uncategorized transactions the rule would categorize now")
    sample = RulePreviewRowSerializer(many=True)
    categorized_count = serializers.IntegerField(help_text="Already-categorized transactions it matches")
    agreeing_count = serializers.IntegerField(help_text="Of those, how many are already in the rule's category")


class RuleApplyResultSerializer(serializers.Serializer):
    categorized = serializers.IntegerField()
    categorized_ids = serializers.ListField(child=serializers.IntegerField())
    refused = serializers.ListField(child=serializers.DictField())
    skipped = serializers.ListField(child=serializers.DictField())


class RuleReorderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False, max_length=1000)
