from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.guards import assert_category_allowed
from apps.accounts.models import Account
from apps.bank_feed.services.splits import MAX_LEGS, MIN_LEGS

from . import constants
from .models import Rule, RuleMatch, RuleProposal
from .services import engine

HUNDRED = Decimal("100")


class BookAccountField(serializers.PrimaryKeyRelatedField):
    """An account of the request's book; another book's id is "does not exist"."""

    def __init__(self, **kwargs):
        # A class-level queryset tells the schema generator the field's model;
        # validation always goes through `get_queryset`, narrowed to the book.
        kwargs.setdefault("queryset", Account.objects.none())
        super().__init__(**kwargs)

    def get_queryset(self):
        request = self.context.get("request")
        if request is None or getattr(request, "book", None) is None:
            return Account.objects.none()
        return Account.objects.filter(book=request.book).select_related("account_group")


class ConditionSerializer(serializers.Serializer):
    field = serializers.ChoiceField(choices=engine.FIELDS)
    op = serializers.ChoiceField(choices=sorted({*engine.TEXT_OPS, *engine.AMOUNT_OPS}))
    value = serializers.JSONField(help_text="Text, an amount, or [low, high] for 'between'")


class SplitShareSerializer(serializers.Serializer):
    category = serializers.IntegerField()
    percent = serializers.DecimalField(max_digits=6, decimal_places=3)


def check_conditions(raw):
    if len(raw) > constants.MAX_CONDITIONS_PER_RULE:
        raise serializers.ValidationError(
            _("A rule can have at most %(n)d conditions.") % {"n": constants.MAX_CONDITIONS_PER_RULE}
        )
    cleaned = []
    for index, condition in enumerate(raw, start=1):
        try:
            engine.compile_condition(condition)
        except engine.ConditionError as e:
            raise serializers.ValidationError(_("Condition %(n)d: %(error)s") % {"n": index, "error": e}) from None
        value = condition["value"]
        if condition["field"] == engine.FIELD_AMOUNT:
            value = [str(v) for v in value] if condition["op"] == engine.OP_BETWEEN else str(value)
        cleaned.append({"field": condition["field"], "op": condition["op"], "value": value})
    return cleaned


class RuleSerializer(serializers.ModelSerializer):
    accounts = BookAccountField(many=True, required=False)
    category = BookAccountField(allow_null=True, required=False)
    conditions = ConditionSerializer(many=True, required=False)
    splits = SplitShareSerializer(many=True, allow_null=True, required=False)
    priority = serializers.IntegerField(required=False, min_value=0)
    category_name = serializers.SerializerMethodField()
    problem = serializers.SerializerMethodField()
    proposal_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Rule
        fields = [
            "id",
            "name",
            "is_active",
            "priority",
            "mode",
            "direction",
            "accounts",
            "match",
            "conditions",
            "action",
            "category",
            "category_name",
            "splits",
            "payee_name",
            "description",
            "origin",
            "times_applied",
            "times_confirmed",
            "times_overridden",
            "confirm_streak",
            "last_matched_at",
            "graduation_declined_at",
            "demoted_at",
            "problem",
            "proposal_id",
            "created_at",
        ]
        read_only_fields = [
            "times_applied",
            "times_confirmed",
            "times_overridden",
            "confirm_streak",
            "last_matched_at",
            "graduation_declined_at",
            "demoted_at",
            "created_at",
        ]

    def get_category_name(self, rule) -> str | None:
        return rule.category.name if rule.category_id and rule.category else None

    def get_problem(self, rule) -> str:
        from .services.actions import problem

        accounts = self.context.get("accounts_by_id")
        if accounts is None:
            from .services.actions import book_accounts

            accounts = book_accounts(rule.book)
        return problem(rule, accounts) or ""

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(_("Give the rule a name."))
        book = self.context["request"].book
        taken = Rule.objects.filter(book=book, name=value)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError(_("Another rule already has this name."))
        return value

    def validate_conditions(self, value):
        return check_conditions(value)

    def validate_accounts(self, value):
        for account in value:
            if not account.has_feed:
                raise serializers.ValidationError(
                    _("“%(name)s” has no bank feed, so no rule can apply to it.") % {"name": account.name}
                )
        return value

    def validate(self, data):
        def current(name, default=None):
            if name in data:
                return data[name]
            if self.instance is not None:
                if name == "accounts":
                    return list(self.instance.accounts.all())
                return getattr(self.instance, name)
            return default

        if self.instance is None:
            book = self.context["request"].book
            if Rule.objects.filter(book=book).count() >= constants.MAX_RULES_PER_BOOK:
                raise serializers.ValidationError(
                    _("A set of books can have at most %(n)d rules.") % {"n": constants.MAX_RULES_PER_BOOK}
                )

        action = current("action", Rule.ACTION_CATEGORY)
        mode = current("mode", Rule.MODE_SUGGEST)
        category = current("category")
        splits = current("splits")
        accounts = current("accounts", [])
        conditions = current("conditions", [])
        direction = current("direction", Rule.DIRECTION_ANY)
        payee_name = (current("payee_name", "") or "").strip()
        description = (current("description", "") or "").strip()
        data["payee_name"], data["description"] = payee_name, description

        if not conditions and direction == Rule.DIRECTION_ANY and not accounts:
            raise serializers.ValidationError(
                {"conditions": _("Add a condition, a direction or an account: a rule must narrow something down.")}
            )

        if action == Rule.ACTION_CATEGORY:
            if category is None:
                raise serializers.ValidationError({"category": _("Pick the category to set.")})
            try:
                assert_category_allowed(category)
            except ValueError as e:
                raise serializers.ValidationError({"category": str(e)}) from None
            if any(a.pk == category.pk for a in accounts):
                raise serializers.ValidationError(
                    {"category": _("A transaction cannot be categorized to the account it is in.")}
                )
            if category.has_feed and mode == Rule.MODE_AUTO_POST:
                raise serializers.ValidationError(
                    {
                        "mode": _(
                            "A transfer to another bank account is only ever suggested, never posted automatically."
                        )
                    }
                )
            data["splits"] = None
        elif action == Rule.ACTION_SPLIT:
            data["splits"] = self._check_splits(splits)
            data["category"] = None
        else:
            if not (payee_name or description):
                raise serializers.ValidationError(
                    {"payee_name": _("A rename-only rule needs a new payee or description.")}
                )
            data["category"] = None
            data["splits"] = None
        return data

    # `conditions` and `splits` are nested serializers over JSON columns, which
    # ModelSerializer will not write; the values are already plain lists here.
    def create(self, validated_data):
        accounts = validated_data.pop("accounts", [])
        validated_data.pop("proposal_id", None)
        rule = Rule(**validated_data)
        rule.save()
        rule.accounts.set(accounts)
        return rule

    def update(self, instance, validated_data):
        accounts = validated_data.pop("accounts", None)
        validated_data.pop("proposal_id", None)
        for name, value in validated_data.items():
            setattr(instance, name, value)
        instance.save()
        if accounts is not None:
            instance.accounts.set(accounts)
        return instance

    def _check_splits(self, splits):
        if not splits or len(splits) < MIN_LEGS:
            raise serializers.ValidationError(
                {"splits": _("A split needs at least %(n)d categories.") % {"n": MIN_LEGS}}
            )
        if len(splits) > MAX_LEGS:
            raise serializers.ValidationError(
                {"splits": _("A split cannot have more than %(n)d categories.") % {"n": MAX_LEGS}}
            )
        book = self.context["request"].book
        accounts = {a.pk: a for a in Account.objects.filter(book=book, pk__in=[s["category"] for s in splits])}
        total = Decimal("0")
        cleaned = []
        for index, share in enumerate(splits, start=1):
            account = accounts.get(share["category"])
            if account is None:
                raise serializers.ValidationError({"splits": _("Split %(n)d: category not found.") % {"n": index}})
            try:
                assert_category_allowed(account)
            except ValueError as e:
                raise serializers.ValidationError({"splits": f"{index}: {e}"}) from None
            if account.has_feed:
                raise serializers.ValidationError(
                    {"splits": _("Split %(n)d: a rule's split cannot include a transfer.") % {"n": index}}
                )
            try:
                percent = Decimal(str(share["percent"]))
            except (InvalidOperation, TypeError):
                raise serializers.ValidationError(
                    {"splits": _("Split %(n)d: not a percentage.") % {"n": index}}
                ) from None
            if percent <= 0:
                raise serializers.ValidationError({"splits": _("Split %(n)d: must be more than 0%%.") % {"n": index}})
            total += percent
            cleaned.append({"category": account.pk, "percent": str(percent.normalize())})
        if total != HUNDRED:
            raise serializers.ValidationError({"splits": _("The split must add up to 100%.")})
        return cleaned


class RuleDraftSerializer(serializers.Serializer):
    """A rule as the builder has it so far: enough to test, not necessarily enough to save."""

    id = serializers.IntegerField(required=False, allow_null=True)
    priority = serializers.IntegerField(required=False, allow_null=True)
    direction = serializers.ChoiceField(choices=[c for c, _label in Rule.DIRECTION_CHOICES], default="any")
    accounts = BookAccountField(many=True, required=False)
    match = serializers.ChoiceField(choices=[c for c, _label in Rule.MATCH_CHOICES], default="all")
    conditions = ConditionSerializer(many=True, required=False)
    action = serializers.ChoiceField(choices=[c for c, _label in Rule.ACTION_CHOICES], default="category")
    category = BookAccountField(allow_null=True, required=False)
    splits = SplitShareSerializer(many=True, allow_null=True, required=False)
    payee_name = serializers.CharField(required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_conditions(self, value):
        return check_conditions(value)


class RuleTestResultSerializer(serializers.Serializer):
    pending = serializers.DictField()
    backtest = serializers.DictField()
    conflicts = serializers.DictField()


class ReorderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class TransactionIdSerializer(serializers.Serializer):
    transaction_id = serializers.IntegerField()


class ExplainRequestSerializer(serializers.Serializer):
    rule = RuleDraftSerializer()
    transaction_id = serializers.IntegerField()


class GraduateSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class DeclineDraftSerializer(serializers.Serializer):
    signature = serializers.CharField(max_length=255)
    category = serializers.IntegerField(required=False, allow_null=True)


class AcceptMatchesSerializer(serializers.Serializer):
    transaction_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False, max_length=1000)


class RuleMatchSerializer(serializers.ModelSerializer):
    transaction_id = serializers.IntegerField(read_only=True)
    # A plain string: a blank-or-choice field generates a TypeScript union the client generator gets wrong.
    held_reason = serializers.CharField(read_only=True)

    class Meta:
        model = RuleMatch
        fields = ["transaction_id", "rule", "rule_name", "status", "held_reason", "category", "splits", "payee_name"]
        read_only_fields = fields


class RuleProposalSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = RuleProposal
        fields = [
            "id",
            "signature",
            "field",
            "value",
            "direction",
            "category",
            "category_name",
            "evidence_count",
            "consistency",
            "status",
        ]
        read_only_fields = fields
