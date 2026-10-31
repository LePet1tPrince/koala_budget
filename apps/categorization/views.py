"""
The rules page and its API, under `/a/{team}/{book}/bankfeed/rules/`.

Members read; only book admins write -- a rule changes what happens to every
future transaction in the book (`RulePermissions`).
"""

from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY, Account
from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.bank_feed.models import BankTransaction
from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name
from apps.books.permissions import BookModelAccessPermissions
from apps.budget.services import picker_accounts_data
from apps.teams.roles import is_admin

from . import apply as rule_apply
from .matching import RuleConditionError
from .models import CategorizationRule
from .rule_names import draft_from_row
from .serializers import (
    CategorizationRuleSerializer,
    RuleApplyResultSerializer,
    RulePreviewSerializer,
    RuleReorderSerializer,
)


class RulePermissions(BookModelAccessPermissions):
    """Members of the book's team read; admins write, including creating, reordering and applying."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.method in permissions.SAFE_METHODS or is_admin(request.user, request.team)


def applied_count():
    """Rows a rule filed that are still filed that way (see CategorizationDecision.stands_for)."""
    return Count(
        "decisions",
        distinct=True,
        filter=Q(
            decisions__journal_entry_id=F("decisions__bank_transaction__journal_entry_id"),
            decisions__journal_entry__lines__account_id=F("decisions__category_id"),
        ),
    )


def _log_change(request, action_name, rule=None, **extra):
    metadata = {"action": action_name, **extra}
    if rule is not None:
        metadata.update({"rule_id": rule.id, "name": rule.name})
    log_event(AuditEvent.CATEGORIZATION_RULE_CHANGED, request=request, metadata=metadata)


@extend_schema_view(
    list=extend_schema(operation_id="categorization_rules_list", tags=["categorization"]),
    create=extend_schema(operation_id="categorization_rules_create", tags=["categorization"]),
    retrieve=extend_schema(operation_id="categorization_rules_retrieve", tags=["categorization"]),
    update=extend_schema(operation_id="categorization_rules_update", tags=["categorization"]),
    partial_update=extend_schema(operation_id="categorization_rules_partial_update", tags=["categorization"]),
    destroy=extend_schema(operation_id="categorization_rules_destroy", tags=["categorization"]),
)
class CategorizationRuleViewSet(viewsets.ModelViewSet):
    serializer_class = CategorizationRuleSerializer
    permission_classes = [RulePermissions]
    pagination_class = None
    queryset = CategorizationRule.objects.none()  # for drf-spectacular

    def get_queryset(self):
        return (
            CategorizationRule.objects.filter(book=self.request.book)
            .select_related("category__account_group", "account")
            .annotate(applied_count=applied_count())
            .in_order()
        )

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "book": self.request.book}

    def perform_create(self, serializer):
        top = CategorizationRule.objects.filter(book=self.request.book).aggregate(top=Max("priority"))["top"]
        rule = serializer.save(book=self.request.book, priority=0 if top is None else top + 1)
        _log_change(self.request, "created", rule)

    def perform_update(self, serializer):
        rule = serializer.save()
        _log_change(self.request, "updated", rule)

    def perform_destroy(self, instance):
        _log_change(self.request, "deleted", instance)
        instance.delete()

    @extend_schema(
        operation_id="categorization_rules_reorder",
        tags=["categorization"],
        request=RuleReorderSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"])
    def reorder(self, request, team_slug=None, book_slug=None):
        """Every rule of the book, by id, in the new order (first runs first)."""
        serializer = RuleReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        rules = {rule.id: rule for rule in CategorizationRule.objects.filter(book=request.book)}
        if len(set(ids)) != len(ids) or set(ids) != set(rules):
            return Response(
                {"error": _("Send every rule of this book exactly once.")}, status=status.HTTP_400_BAD_REQUEST
            )
        with transaction.atomic():
            for priority, rule_id in enumerate(ids):
                rule = rules[rule_id]
                if rule.priority != priority:
                    rule.priority = priority
                    rule.save(update_fields=["priority", "updated_at"])
        _log_change(request, "reordered", count=len(ids))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="categorization_rules_preview",
        tags=["categorization"],
        request=CategorizationRuleSerializer,
        responses={200: RulePreviewSerializer},
    )
    @action(detail=False, methods=["post"])
    def preview(self, request, team_slug=None, book_slug=None):
        """
        Test an unsaved rule (the editor's fields) against the book. Writes nothing.
        Pass `id` to test an edit of an existing rule.
        """
        instance = None
        rule_id = request.data.get("id")
        if rule_id:
            instance = CategorizationRule.objects.filter(book=request.book, pk=rule_id).first()
        # Partial: the conditions can be tested before a category is chosen.
        serializer = CategorizationRuleSerializer(
            instance, data=request.data, partial=True, context=self.get_serializer_context()
        )
        # A preview of a half-typed rule is "matches nothing yet", not an error page.
        if not serializer.is_valid():
            return Response({"errors": serializer.errors, **_empty_preview()})
        merged = {**serializer._current(), **serializer.validated_data}
        rule = CategorizationRule(
            book=request.book,
            **{k: v for k, v in merged.items() if k not in {"account", "category"}},
            account=merged.get("account"),
            category=merged.get("category"),
        )
        try:
            result = rule_apply.preview(request.book, rule)
        except RuleConditionError as error:
            return Response({"errors": {"non_field_errors": [str(error)]}, **_empty_preview()})
        return Response(RulePreviewSerializer(result).data)

    @extend_schema(
        operation_id="categorization_rules_test",
        tags=["categorization"],
        request=None,
        responses={200: RulePreviewSerializer},
    )
    @action(detail=True, methods=["get"], url_path="test", url_name="test")
    def test_rule(self, request, team_slug=None, book_slug=None, pk=None):
        """Test a saved rule against the book. Writes nothing."""
        rule = self.get_object()
        try:
            result = rule_apply.preview(request.book, rule)
        except RuleConditionError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RulePreviewSerializer(result).data)

    @extend_schema(
        operation_id="categorization_rules_apply",
        tags=["categorization"],
        request=None,
        responses={200: RuleApplyResultSerializer},
    )
    @action(detail=True, methods=["post"])
    def apply(self, request, team_slug=None, book_slug=None, pk=None):
        """File every uncategorized transaction this rule matches, now."""
        rule = self.get_object()
        if rule.problem:
            return Response({"error": rule.problem}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = rule_apply.apply_rule(rule, user=request.user)
        except RuleConditionError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RuleApplyResultSerializer(result.as_dict()).data)

    @extend_schema(
        operation_id="categorization_rules_draft",
        tags=["categorization"],
        parameters=[
            OpenApiParameter("transaction", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("category", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def draft(self, request, team_slug=None, book_slug=None):
        """An unsaved rule matching one bank transaction, for the editor to open on."""
        try:
            tx_id = int(request.query_params.get("transaction", ""))
        except ValueError:
            return Response({"error": _("transaction is required")}, status=status.HTTP_400_BAD_REQUEST)
        row = BankTransaction.objects.filter(book=request.book, pk=tx_id).select_related("book").first()
        if row is None:
            return Response({"error": _("Transaction not found")}, status=status.HTTP_404_NOT_FOUND)
        category = None
        category_id = request.query_params.get("category")
        if category_id and category_id.isdigit():
            category = Account.objects.filter(book=request.book, pk=int(category_id)).exclude_budget_buckets().first()
        if category is None and row.journal_entry_id:
            lines = [line for line in row.journal_entry.lines.all() if line.account_id != row.account_id]
            category = lines[0].account if len(lines) == 1 else None
        return Response(draft_from_row(row, category))


def _empty_preview():
    return {"count": 0, "sample": [], "categorized_count": 0, "agreeing_count": 0}


def rule_feed_accounts(book):
    """Asset and liability accounts a rule may be scoped to (bank feed accounts first)."""
    accounts = (
        Account.objects.filter(
            book=book,
            is_system=False,
            account_group__account_type__in=(ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY),
        )
        .exclude_budget_buckets()
        .order_by("-has_feed", *Account._meta.ordering)
    )
    return [{"id": a.id, "name": a.name, "has_feed": a.has_feed} for a in accounts]


@login_and_book_required
def rules_home(request, team_slug, book_slug):
    """The rules page: list, edit, reorder, test and apply. A React app over the API above."""
    book = request.book
    return render(
        request,
        "categorization/rules_home.html",
        {
            "active_tab": "settings",
            "settings_section": "categorization_rules",
            "settings_page_title": gettext_lazy("Categorization rules"),
            "settings_page_blurb": gettext_lazy(
                "Rules file transactions that look alike the same way, the moment they arrive from your bank "
                "or a CSV — or suggest a category in Categorize mode, if you'd rather confirm."
            ),
            "page_title": _("Categorization rules | {name}").format(name=book_display_name(book)),
            "rules_props": {
                "canEdit": is_admin(request.user, request.team),
                "accounts": list(picker_accounts_data(book)),
                "feedAccounts": rule_feed_accounts(book),
                "inboxUrl": reverse("bank_feed:bank_feed_home", args=book.url_args),
                "categorizeUrl": reverse("bank_feed:categorize_mode", args=book.url_args),
            },
        },
    )
