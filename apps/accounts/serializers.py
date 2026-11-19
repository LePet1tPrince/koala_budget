"""
Serializers for accounts app.
"""

from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.api.base import MonthField

from .models import ACCOUNT_TYPE_BUDGET, ACCOUNT_TYPE_CHOICES, Account, AccountGroup, Institution, Payee
from .services import natural_amount
from .validators import (
    GROUP_TYPE_LOCKED_MESSAGE,
    account_name_error,
    default_has_feed,
    group_type_locked,
    holds_institution,
    unique_name_error,
)


class AccountGroupSerializer(serializers.ModelSerializer):
    """Serializer for AccountGroup model."""

    class Meta:
        model = AccountGroup
        fields = [
            "id",
            "name",
            "account_type",
            "description",
            "created_at",
            "updated_at",
            "is_archived",
            "archived_at",
        ]
        read_only_fields = ["created_at", "updated_at", "archived_at"]


class AccountSerializer(serializers.ModelSerializer):
    """Serializer for Account model."""

    account_group_name = serializers.CharField(source="account_group.name", read_only=True)
    account_type = serializers.CharField(source="account_group.account_type", read_only=True)
    institution_name = serializers.CharField(source="institution.name", read_only=True, default=None)
    balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    categorized_balance = serializers.SerializerMethodField()
    reconciled_balance = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "account_group",
            "account_group_name",
            "account_type",
            "institution",
            "institution_name",
            "has_feed",
            "balance",
            "categorized_balance",
            "reconciled_balance",
            "created_at",
            "updated_at",
            "is_archived",
            "archived_at",
        ]
        read_only_fields = [
            "account_group_name",
            "account_type",
            "institution_name",
            "created_at",
            "updated_at",
            "balance",
            "categorized_balance",
            "reconciled_balance",
            "archived_at",
        ]

    def get_categorized_balance(self, obj) -> str | None:
        """Same as `balance` now that archived entries count nowhere; kept for API compatibility."""
        if hasattr(obj, "_balance"):
            return str(obj._balance)
        return None

    def get_reconciled_balance(self, obj) -> str | None:
        """Get reconciled_balance from annotation if available."""
        if hasattr(obj, "_reconciled_balance"):
            return str(obj._reconciled_balance)
        return None


class SimpleAccountSerializer(serializers.ModelSerializer):
    """Serializer for Account model."""

    account_group_name = serializers.CharField(source="account_group.name", read_only=True)
    account_type = serializers.CharField(source="account_group.account_type", read_only=True)
    institution_name = serializers.CharField(source="institution.name", read_only=True, default=None)

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "account_group",
            "account_group_name",
            "account_type",
            "institution_name",
            "has_feed",
            "is_system",
            "is_hidden",
            "is_archived",
            "archived_at",
        ]
        read_only_fields = ["account_group_name", "account_type", "institution_name", "is_system", "archived_at"]


class PickerAccountSerializer(SimpleAccountSerializer):
    """
    An account as a category picker shows it: whether it backs a goal, and what the
    goal has left.

    The equity type is stored as "goal", so nothing may infer goal-ness from the
    type; `is_goal` comes from the Goal relation, passed in as context
    (`goal_left`: {account_id: left}) so a list costs no query per account.
    """

    is_goal = serializers.SerializerMethodField()
    goal_left = serializers.SerializerMethodField()

    class Meta(SimpleAccountSerializer.Meta):
        fields = [*SimpleAccountSerializer.Meta.fields, "is_goal", "goal_left"]

    def get_is_goal(self, obj) -> bool:
        return obj.pk in self.context.get("goal_left", {})

    def get_goal_left(self, obj) -> str | None:
        left = self.context.get("goal_left", {}).get(obj.pk)
        return None if left is None else f"{left:.2f}"


class PayeeSerializer(serializers.ModelSerializer):
    """Serializer for Payee model."""

    class Meta:
        model = Payee
        fields = ["id", "name", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


# =============================================================================
# The accounts app's own API (chart of accounts, payees, institutions, board,
# account activity). Named apart from the serializers above, which other apps
# embed and whose OpenAPI components ("Account", "AccountGroup", "Payee") they own.
# Validation is the forms' own, from `validators`.
# =============================================================================


def _book(serializer):
    request = serializer.context.get("request")
    return getattr(request, "book", None)


def _money(value) -> str:
    return f"{value:.2f}"


class BookRowField(serializers.PrimaryKeyRelatedField):
    """A row of the request's book; another book's id is "does not exist"."""

    model = None

    def __init__(self, **kwargs):
        # A class-level queryset tells the schema generator the field's model;
        # validation always goes through `get_queryset`, narrowed to the book.
        kwargs.setdefault("queryset", self.model.objects.none())
        super().__init__(**kwargs)

    def book_queryset(self, book):
        return self.model.objects.filter(book=book)

    def get_queryset(self):
        book = _book(self)
        return self.book_queryset(book) if book is not None else self.model.objects.none()


class BookAccountGroupField(BookRowField):
    """A group the user may put accounts in: never the budget group."""

    model = AccountGroup

    def book_queryset(self, book):
        return super().book_queryset(book).exclude(account_type=ACCOUNT_TYPE_BUDGET)


class BookInstitutionField(BookRowField):
    model = Institution


def _unique_name(serializer, model, value):
    name = value.strip()
    error = unique_name_error(model, _book(serializer), name, serializer.instance)
    if error:
        raise serializers.ValidationError(error)
    return name


class ManagedAccountGroupSerializer(serializers.ModelSerializer):
    """An account group. Its type is fixed once it holds accounts (or is a system group)."""

    account_type = serializers.ChoiceField(choices=ACCOUNT_TYPE_CHOICES)
    account_count = serializers.SerializerMethodField()

    class Meta:
        model = AccountGroup
        fields = [
            "id",
            "name",
            "account_type",
            "description",
            "is_system",
            "sort_order",
            "account_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["is_system", "sort_order", "created_at", "updated_at"]

    def get_account_count(self, obj) -> int:
        count = getattr(obj, "account_count", None)
        return obj.accounts.count() if count is None else count

    def validate_name(self, value):
        return _unique_name(self, AccountGroup, value)

    def validate_account_type(self, value):
        if self.instance is not None and value != self.instance.account_type and group_type_locked(self.instance):
            raise serializers.ValidationError(GROUP_TYPE_LOCKED_MESSAGE)
        return value


class ManagedAccountSerializer(serializers.ModelSerializer):
    """
    An account of the chart of accounts (never a budget bucket).

    `balance` is the ledger's dr - cr; `natural_balance` is signed the way the
    account type is read (a card's debt and a salary positive) and, for a goal's
    account, is what the goal has left. The account type is its group's.
    """

    account_group = BookAccountGroupField()
    account_group_name = serializers.CharField(source="account_group.name", read_only=True)
    account_type = serializers.CharField(source="account_group.account_type", read_only=True)
    institution = BookInstitutionField(allow_null=True, required=False)
    institution_name = serializers.CharField(source="institution.name", read_only=True, default=None)
    has_feed = serializers.BooleanField(
        required=False, help_text="Defaults to true for a new asset or liability account, false otherwise."
    )
    is_hidden = serializers.BooleanField(
        required=False, help_text="Left out of every account picker and the Inbox; it still counts everywhere."
    )
    balance = serializers.SerializerMethodField()
    natural_balance = serializers.SerializerMethodField()
    is_goal = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "account_group",
            "account_group_name",
            "account_type",
            "institution",
            "institution_name",
            "has_feed",
            "is_hidden",
            "is_system",
            "is_archived",
            "sort_order",
            "balance",
            "natural_balance",
            "is_goal",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["is_system", "is_archived", "sort_order", "created_at", "updated_at"]

    def _goal_left(self, obj):
        return self.context.get("goal_left", {}).get(obj.pk)

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_balance(self, obj) -> str:
        return _money(obj.balance)

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_natural_balance(self, obj) -> str:
        left = self._goal_left(obj)
        if left is not None:
            return _money(left)
        return _money(natural_amount(obj.balance, obj.account_group.account_type))

    def get_is_goal(self, obj) -> bool:
        return self._goal_left(obj) is not None

    def validate_name(self, value):
        return value.strip()

    def validate(self, attrs):
        instance = self.instance
        group = attrs.get("account_group", instance.account_group if instance else None)
        name = attrs.get("name", instance.name if instance else None)
        account_type = group.account_type
        error = account_name_error(_book(self), name, account_type, instance)
        if error:
            raise serializers.ValidationError({"name": [error]})
        if not holds_institution(account_type):
            # Only assets and liabilities are held at an institution (AccountForm drops the field).
            if attrs.get("institution") is not None:
                raise serializers.ValidationError(
                    {"institution": [_("Only asset and liability accounts are held at an institution.")]}
                )
            attrs["institution"] = None
        if instance is None and "has_feed" not in attrs:
            attrs["has_feed"] = default_has_feed(account_type)
        return attrs


class FeedsGoalSerializer(serializers.Serializer):
    goal_id = serializers.IntegerField(source="goal.id")
    goal_name = serializers.CharField(source="goal.name")
    start_date = serializers.DateField(help_text="Its activity counts toward the goal from this day")


class ManagedAccountDetailSerializer(ManagedAccountSerializer):
    """One account, with what its page shows beside the activity."""

    reconcilable = serializers.SerializerMethodField()
    feeds_goal = serializers.SerializerMethodField()

    class Meta(ManagedAccountSerializer.Meta):
        fields = [*ManagedAccountSerializer.Meta.fields, "reconcilable", "feeds_goal"]

    def get_reconcilable(self, obj) -> bool:
        from apps.reconciliation.services.signs import is_reconcilable

        return is_reconcilable(obj)

    @extend_schema_field(FeedsGoalSerializer(allow_null=True))
    def get_feeds_goal(self, obj):
        from apps.budget.models import GoalAccountLink

        link = GoalAccountLink.objects.open().filter(account=obj).select_related("goal").first()
        return FeedsGoalSerializer(link).data if link else None


class ManagedPayeeSerializer(serializers.ModelSerializer):
    """A payee, with how often (and how recently) its transactions count."""

    transaction_count = serializers.IntegerField(read_only=True, default=0)
    first_used = serializers.DateField(read_only=True, allow_null=True, default=None)
    last_used = serializers.DateField(read_only=True, allow_null=True, default=None)

    class Meta:
        model = Payee
        fields = ["id", "name", "transaction_count", "first_used", "last_used", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_name(self, value):
        return _unique_name(self, Payee, value)


class ManagedInstitutionSerializer(serializers.ModelSerializer):
    """A bank or other institution accounts are held at."""

    account_count = serializers.SerializerMethodField()

    class Meta:
        model = Institution
        fields = ["id", "name", "account_count", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def get_account_count(self, obj) -> int:
        count = getattr(obj, "account_count", None)
        return obj.accounts.count() if count is None else count

    def validate_name(self, value):
        return _unique_name(self, Institution, value)


# --- Institution account checklist ------------------------------------------


class InstitutionRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class InstitutionAccountChoiceSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="account.id")
    name = serializers.CharField(source="account.name")
    linked = serializers.BooleanField(source="checked", help_text="Held at this institution")
    elsewhere = InstitutionRefSerializer(
        allow_null=True, help_text="The other institution it is held at, if any (linking it here moves it)"
    )


class InstitutionAccountGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="group.id")
    name = serializers.CharField(source="group.name")
    choices = InstitutionAccountChoiceSerializer(many=True)


class InstitutionAccountSectionSerializer(serializers.Serializer):
    account_type = serializers.CharField(source="type")
    label = serializers.CharField()
    groups = InstitutionAccountGroupSerializer(many=True)


class InstitutionAccountsSerializer(serializers.Serializer):
    """The checklist: the book's assets and liabilities, each marked linked here or elsewhere."""

    sections = InstitutionAccountSectionSerializer(many=True)


class InstitutionAccountsUpdateSerializer(serializers.Serializer):
    account_ids = serializers.ListField(
        child=serializers.IntegerField(),
        max_length=1000,
        help_text="Every account that should be held here: listed ones are linked, the rest unlinked.",
    )


# --- Board --------------------------------------------------------------------


class BoardAccountSerializer(serializers.Serializer):
    """An account row on the board. `balance` is as the board shows it: income cr - dr, a goal what is left."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    is_goal = serializers.BooleanField()
    institution_id = serializers.IntegerField(allow_null=True)
    institution_name = serializers.CharField(allow_null=True)
    is_hidden = serializers.BooleanField()
    is_system = serializers.BooleanField()


class BoardGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    account_type = serializers.CharField()
    is_system = serializers.BooleanField()
    accounts = BoardAccountSerializer(many=True)


class BoardSectionSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="The section: an account type, or 'equity' for goal-type groups with no goal")
    account_type = serializers.CharField(help_text="The stored account type of the section's groups")
    label = serializers.CharField()
    creates_goals = serializers.BooleanField(help_text="Accounts here are made from the Goals page, not the board")
    groups = BoardGroupSerializer(many=True)


class BoardSerializer(serializers.Serializer):
    sections = BoardSectionSerializer(many=True)


class BoardGroupOrderSerializer(serializers.Serializer):
    group_id = serializers.IntegerField()
    account_ids = serializers.ListField(child=serializers.IntegerField(), max_length=1000)


class ReorderAccountsSerializer(serializers.Serializer):
    """
    Each entry is the full ordered list of accounts now in that group; an account
    listed under a different group than its current one is moved there (same
    account type only). All-or-nothing.
    """

    groups = BoardGroupOrderSerializer(many=True, max_length=100)

    def validate(self, attrs):
        book = _book(self)
        group_ids = [entry["group_id"] for entry in attrs["groups"]]
        placements = {}  # account_id -> (group_id, position)
        for entry in attrs["groups"]:
            for position, account_id in enumerate(entry["account_ids"]):
                if account_id in placements:
                    raise serializers.ValidationError(_("An account appears more than once."))
                placements[account_id] = (entry["group_id"], position)

        groups = {
            g.pk: g
            for g in AccountGroup.objects.filter(book=book, pk__in=group_ids).exclude(account_type=ACCOUNT_TYPE_BUDGET)
        }
        if len(groups) != len(set(group_ids)):
            raise serializers.ValidationError(_("Unknown account group."))
        accounts = {
            a.pk: a
            for a in Account.objects.filter(book=book, pk__in=placements)
            .exclude_budget_buckets()
            .select_related("account_group")
        }
        if len(accounts) != len(placements):
            raise serializers.ValidationError(_("Unknown account."))

        resolved = {}
        for account_id, (group_id, position) in placements.items():
            account, group = accounts[account_id], groups[group_id]
            if account.account_group_id != group_id and account.account_group.account_type != group.account_type:
                raise serializers.ValidationError(_("Accounts can only be moved between groups of the same type."))
            resolved[account] = (group, position)
        attrs["placements"] = resolved
        return attrs


class ReorderGroupsSerializer(serializers.Serializer):
    account_type = serializers.ChoiceField(choices=ACCOUNT_TYPE_CHOICES)
    group_ids = serializers.ListField(child=serializers.IntegerField(), max_length=1000)

    def validate(self, attrs):
        group_ids = attrs["group_ids"]
        groups = {
            g.pk: g
            for g in AccountGroup.objects.filter(book=_book(self), account_type=attrs["account_type"], pk__in=group_ids)
        }
        if len(groups) != len(group_ids) or len(set(group_ids)) != len(group_ids):
            raise serializers.ValidationError({"group_ids": [_("Unknown account group.")]})
        attrs["groups"] = [groups[pk] for pk in group_ids]
        return attrs


class BoardCreateAccountSerializer(serializers.Serializer):
    """An account at the bottom of a group (the board's inline "+" form)."""

    name = serializers.CharField(max_length=200)
    group_id = BookAccountGroupField()

    def validate_name(self, value):
        return value.strip()

    def validate(self, attrs):
        error = account_name_error(_book(self), attrs["name"], attrs["group_id"].account_type)
        if error:
            raise serializers.ValidationError({"name": [error]})
        return attrs


class BoardCreateGroupSerializer(serializers.Serializer):
    """A group at the bottom of a type section (the board's inline "+" form)."""

    name = serializers.CharField(max_length=200)
    account_type = serializers.ChoiceField(choices=ACCOUNT_TYPE_CHOICES)

    def validate_name(self, value):
        return _unique_name(self, AccountGroup, value)


class SetHiddenSerializer(serializers.Serializer):
    """
    Hide or show an account. A hidden account is left out of every account picker
    and the Inbox; its transactions still count in every balance and report.
    """

    account_id = serializers.IntegerField()
    is_hidden = serializers.BooleanField()


# --- Account activity and charts ------------------------------------------------


class DateRangeQuerySerializer(serializers.Serializer):
    """`?start_date=&end_date=` (YYYY-MM-DD, both or neither); neither is the book's default report range."""

    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)

    def validate(self, attrs):
        start, end = attrs.get("start_date"), attrs.get("end_date")
        if (start is None) != (end is None):
            raise serializers.ValidationError(_("Give both start_date and end_date, or neither."))
        if start is not None and start > end:
            raise serializers.ValidationError({"end_date": [_("The end date is before the start date.")]})
        return attrs


class ActivityAccountRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ActivityTransactionSerializer(serializers.Serializer):
    entry_id = serializers.IntegerField()
    date = serializers.DateField()
    payee_id = serializers.IntegerField(allow_null=True)
    payee_name = serializers.CharField(source="payee", allow_blank=True)
    memo = serializers.CharField(allow_blank=True)
    amount = serializers.DecimalField(
        max_digits=15, decimal_places=2, help_text="Signed so positive means the account's balance (or total) grew"
    )
    balance = serializers.DecimalField(
        max_digits=15, decimal_places=2, allow_null=True, default=None, help_text="Running balance (balance accounts)"
    )
    source = serializers.CharField(source="source_code")
    source_label = serializers.CharField(source="source")
    contra_accounts = ActivityAccountRefSerializer(many=True)
    editable = serializers.BooleanField(help_text="A transaction (opens the edit modal), not a budget entry")


class AccountActivitySerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    is_balance_account = serializers.BooleanField()
    starting_balance = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True)
    ending_balance = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True)
    total = serializers.DecimalField(max_digits=15, decimal_places=2)
    transactions = ActivityTransactionSerializer(many=True)


class BalancePointSerializer(serializers.Serializer):
    date = serializers.DateField()
    balance = serializers.DecimalField(max_digits=15, decimal_places=2, help_text="End-of-day balance")


class BalanceChartSerializer(serializers.Serializer):
    """The balance over the range: a step function from `starting_balance` through each day with activity."""

    start_date = serializers.DateField()
    end_date = serializers.DateField()
    starting_balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    ending_balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    points = BalancePointSerializer(many=True)


class BudgetChartSerializer(serializers.Serializer):
    """
    Per month: budgeted vs actual and the rolling available (income/expense), or
    for a goal's account allocated vs spent and the running left (`kind` "goal").
    """

    kind = serializers.ChoiceField(choices=["income", "expense", "goal"], source="account_type")
    months = serializers.ListField(child=MonthField())
    budgeted = serializers.ListField(child=serializers.DecimalField(max_digits=15, decimal_places=2))
    actual = serializers.ListField(child=serializers.DecimalField(max_digits=15, decimal_places=2))
    available = serializers.ListField(child=serializers.DecimalField(max_digits=15, decimal_places=2))


class AccountChartsSerializer(serializers.Serializer):
    """The account page's charts for a range; a chart the account has none of is null."""

    balance = BalanceChartSerializer(allow_null=True)
    budget = BudgetChartSerializer(allow_null=True)
