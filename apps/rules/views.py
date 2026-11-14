"""
Transaction rules: the Rules page and its API (docs/transaction-rules-plan.md §7–8).

Who may do what follows the rest of the book: any member reads rules and acts on
a rule's suggestions (accept, dismiss, undo -- they are categorizations, which
members make in the feed); only an admin creates, edits, reorders or deletes a
rule, as only an admin edits any other book-scoped row.
"""

from django.db import transaction
from django.db.models import F
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.bank_feed.models import BankTransaction
from apps.books.decorators import login_and_book_required
from apps.books.helpers import book_display_name
from apps.books.permissions import BookAccessPermissions, BookAdminWritePermissions, BookModelAccessPermissions
from apps.budget.services import picker_accounts_data
from apps.teams.roles import is_admin

from .models import Rule, RuleMatch, RuleProposal
from .serializers import (
    AcceptMatchesSerializer,
    DeclineDraftSerializer,
    ExplainRequestSerializer,
    GraduateSerializer,
    ReorderSerializer,
    RuleDraftSerializer,
    RuleMatchSerializer,
    RuleProposalSerializer,
    RuleSerializer,
    RuleTestResultSerializer,
    TransactionIdSerializer,
)
from .services import analysis, apply, engine, feedback, ordering
from .services.actions import book_accounts
from .services.apply import GUARD_ERRORS


def _draft_rule(book, data):
    """An unsaved `Rule` from builder data, and its account ids, for testing and explaining."""
    instance = None
    if data.get("id"):
        instance = Rule.objects.filter(book=book, pk=data["id"]).first()
    account_ids = [a.pk for a in data.get("accounts", [])]
    if instance is not None:
        priority = instance.priority if data.get("priority") is None else data["priority"]
        pk = instance.pk
    else:
        pk = None
        if data.get("priority") is not None:
            # Asked to go at this position: just above the rule there now.
            priority = data["priority"] - 0.5
        else:
            index, _rules = analysis.insertion_index(book, data.get("conditions"), account_ids, data["direction"])
            priority = index - 0.5
    category = data.get("category")
    rule = Rule(
        book=book,
        priority=0,
        direction=data["direction"],
        match=data["match"],
        conditions=data.get("conditions") or [],
        action=data["action"],
        category=category,
        splits=[{"category": s["category"], "percent": str(s["percent"])} for s in (data.get("splits") or [])] or None,
        payee_name=data.get("payee_name", ""),
        description=data.get("description", ""),
    )
    rule.pk = pk
    rule.priority = priority
    return rule, account_ids


@extend_schema(tags=["rules"])
class RuleViewSet(viewsets.ModelViewSet):
    """The book's rules, in priority order (lower wins)."""

    serializer_class = RuleSerializer
    pagination_class = None
    queryset = Rule.objects.none()  # for drf-spectacular schema generation

    def get_permissions(self):
        if self.action in ("create", "reorder"):
            return [BookAdminWritePermissions()]
        return [BookModelAccessPermissions()]

    def get_queryset(self):
        return (
            Rule.objects.filter(book=self.request.book)
            .select_related("category", "book")
            .prefetch_related("accounts")
            .order_by("priority", "id")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self.request, "book", None) is not None:
            context["accounts_by_id"] = book_accounts(self.request.book)
        return context

    def perform_create(self, serializer):
        book = self.request.book
        data = serializer.validated_data
        explicit = data.get("priority")
        proposal_id = data.get("proposal_id")
        with transaction.atomic():
            rule = serializer.save(book=book, priority=0)
            if explicit is None:
                index, _rules = analysis.insertion_index(
                    book, rule.conditions, [a.pk for a in rule.accounts.all()], rule.direction, exclude_id=rule.pk
                )
            else:
                index = explicit
            ordering.place(book, rule, index)
            if proposal_id:
                RuleProposal.objects.filter(book=book, pk=proposal_id).update(status=RuleProposal.STATUS_ACCEPTED)
        log_event(AuditEvent.RULE_CREATED, request=self.request, metadata={"rule_id": rule.pk, "name": rule.name})
        apply.refresh(book)
        rule.refresh_from_db()

    def perform_update(self, serializer):
        book = self.request.book
        was_mode = serializer.instance.mode
        data = serializer.validated_data
        with transaction.atomic():
            extra = {}
            if data.get("mode") == Rule.MODE_AUTO_POST and was_mode != Rule.MODE_AUTO_POST:
                # Switching auto-post back on is the user's call: the demotion notice is answered.
                extra["demoted_at"] = None
            new_priority = data.pop("priority", None)
            rule = serializer.save(**extra)
            if new_priority is not None and new_priority != rule.priority:
                ordering.place(book, rule, new_priority)
        log_event(
            AuditEvent.RULE_UPDATED,
            request=self.request,
            metadata={"rule_id": rule.pk, "fields": sorted(self.request.data)},
        )
        apply.refresh(book)

    def perform_destroy(self, instance):
        book = self.request.book
        log_event(
            AuditEvent.RULE_DELETED, request=self.request, metadata={"rule_id": instance.pk, "name": instance.name}
        )
        instance.delete()
        ordering.renumber(book)
        apply.refresh(book)

    @extend_schema(
        operation_id="rules_reorder",
        tags=["rules"],
        request=ReorderSerializer,
        responses={200: RuleSerializer(many=True)},
    )
    @action(detail=False, methods=["post"])
    def reorder(self, request, team_slug=None, book_slug=None):
        """Put the book's rules in this order (ids first to last; any left out keep their order after)."""
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ordering.reorder(request.book, serializer.validated_data["ids"])
        apply.refresh(request.book)
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    @extend_schema(
        operation_id="rules_test",
        tags=["rules"],
        request=RuleDraftSerializer,
        responses={200: RuleTestResultSerializer},
    )
    @action(detail=False, methods=["post"])
    def test(self, request, team_slug=None, book_slug=None):
        """What a draft rule would match now, how it would have done on history, and what it collides with."""
        serializer = RuleDraftSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        rule, account_ids = _draft_rule(request.book, serializer.validated_data)
        try:
            result = analysis.test(request.book, rule, account_ids)
        except engine.ConditionError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @extend_schema(operation_id="rules_explain", tags=["rules"], request=ExplainRequestSerializer)
    @action(detail=False, methods=["post"])
    def explain(self, request, team_slug=None, book_slug=None):
        """Why a draft rule does or does not match one transaction."""
        serializer = ExplainRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        tx = (
            BankTransaction.objects.filter(book=request.book, pk=serializer.validated_data["transaction_id"])
            .select_related("account", "rule_match")
            .first()
        )
        if tx is None:
            return Response({"error": _("Transaction not found")}, status=status.HTTP_404_NOT_FOUND)
        rule, account_ids = _draft_rule(request.book, serializer.validated_data["rule"])
        return Response(analysis.explain(rule, account_ids, tx))

    @extend_schema(operation_id="rules_draft_from_transaction", tags=["rules"], request=TransactionIdSerializer)
    @action(detail=False, methods=["post"])
    def draft_from_transaction(self, request, team_slug=None, book_slug=None):
        """The rule a just-made categorization suggests, and whether it is worth offering."""
        serializer = TransactionIdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tx = BankTransaction.objects.filter(book=request.book, pk=serializer.validated_data["transaction_id"]).first()
        if tx is None:
            return Response({"error": _("Transaction not found")}, status=status.HTTP_404_NOT_FOUND)
        if not tx.journal_entry_id:
            return Response({"offer": False, "reason": "uncategorized", "rule": None, "coverage": 0})
        return Response(analysis.draft_from_transaction(request.book, tx))

    @extend_schema(operation_id="rules_decline_draft", tags=["rules"], request=DeclineDraftSerializer)
    @action(detail=False, methods=["post"])
    def decline_draft(self, request, team_slug=None, book_slug=None):
        """ "Don't offer a rule for this merchant again" -- the create-from-action toast's No."""
        serializer = DeclineDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        signature = serializer.validated_data["signature"]
        field, _sep, value = signature.partition(":")
        if field not in (RuleProposal.FIELD_PAYEE, RuleProposal.FIELD_DESCRIPTION) or not value:
            return Response({"error": _("Unknown signature")}, status=status.HTTP_400_BAD_REQUEST)
        category_id = serializer.validated_data.get("category")
        category = book_accounts(request.book).get(category_id) if category_id else None
        RuleProposal.objects.update_or_create(
            book=request.book,
            signature=signature,
            defaults={
                "field": field,
                "value": value[:255],
                "category": category,
                "status": RuleProposal.STATUS_DISMISSED,
            },
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(operation_id="rules_prompts", tags=["rules"])
    @action(detail=False, methods=["get"])
    def prompts(self, request, team_slug=None, book_slug=None):
        """Things to ask the user: rules ready for auto-post, rules demoted, proposals waiting."""
        offers = feedback.graduation_offers(request.book)
        demoted = Rule.objects.filter(book=request.book, demoted_at__isnull=False, mode=Rule.MODE_SUGGEST)
        return Response(
            {
                "graduation": [{"id": r.pk, "name": r.name, "streak": r.confirm_streak} for r in offers],
                "demoted": [{"id": r.pk, "name": r.name, "demoted_at": r.demoted_at} for r in demoted],
                "proposals": RuleProposal.objects.filter(book=request.book, status=RuleProposal.STATUS_OPEN).count(),
                "can_edit": is_admin(request.user, request.team),
            }
        )

    @extend_schema(
        operation_id="rules_graduate", tags=["rules"], request=GraduateSerializer, responses={200: RuleSerializer}
    )
    @action(detail=True, methods=["post"])
    def graduate(self, request, pk=None, team_slug=None, book_slug=None):
        """Answer "auto-post this from now on?": yes switches the rule to auto-post, no stops asking."""
        rule = self.get_object()
        serializer = GraduateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["accept"]:
            if rule.category_id and rule.category.has_feed:
                return Response(
                    {"error": _("A transfer to another bank account is only ever suggested.")},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            rule.mode = Rule.MODE_AUTO_POST
            rule.demoted_at = None
            rule.save(update_fields=["mode", "demoted_at", "updated_at"])
            log_event(AuditEvent.RULE_UPDATED, request=request, metadata={"rule_id": rule.pk, "fields": ["mode"]})
        else:
            rule.graduation_declined_at = timezone.now()
            rule.save(update_fields=["graduation_declined_at", "updated_at"])
        return Response(self.get_serializer(rule).data)

    @extend_schema(operation_id="rules_apply", tags=["rules"])
    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None, team_slug=None, book_slug=None):
        """ "Save and apply to N existing transactions": post this auto-post rule's current matches."""
        rule = self.get_object()
        if rule.mode != Rule.MODE_AUTO_POST:
            return Response({"error": _("Only an auto-post rule applies itself.")}, status=status.HTTP_400_BAD_REQUEST)
        counts = apply.run(request.book, auto_post_rule_ids={rule.pk})
        return Response(counts)


def _match_for(request, transaction_id):
    return (
        RuleMatch.objects.filter(book=request.book, transaction_id=transaction_id)
        .select_related("transaction__account", "transaction__journal_entry", "book")
        .first()
    )


class RuleMatchViewSet(viewsets.GenericViewSet):
    """A rule's suggestion or auto-post on one feed row, acted on by any member."""

    permission_classes = [BookAccessPermissions]
    serializer_class = RuleMatchSerializer
    queryset = RuleMatch.objects.none()
    lookup_field = "transaction_id"
    lookup_value_regex = r"\d+"

    @extend_schema(operation_id="rules_matches_accept", tags=["rules"], request=AcceptMatchesSerializer)
    @action(detail=False, methods=["post"])
    def accept(self, request, team_slug=None, book_slug=None):
        """Accept suggestions as offered. Each row stands alone: one refused row does not stop the rest."""
        serializer = AcceptMatchesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["transaction_ids"]
        matches = RuleMatch.objects.filter(
            book=request.book, transaction_id__in=ids, status=RuleMatch.STATUS_SUGGESTED
        ).select_related("transaction__account", "transaction__journal_entry", "book")
        accepted, refused = [], []
        for match in matches:
            try:
                feedback.accept(match)
            except (feedback.MatchError, *GUARD_ERRORS) as e:
                refused.append({"kind": "row", "id": match.transaction_id, "error": str(e)})
            else:
                accepted.append(match.transaction_id)
        if accepted:
            log_event(AuditEvent.BULK_CATEGORIZE, request=request, metadata={"count": len(accepted), "via": "rule"})
        return Response({"accepted": accepted, "refused": refused})

    @extend_schema(operation_id="rules_matches_dismiss", tags=["rules"], request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def dismiss(self, request, transaction_id=None, team_slug=None, book_slug=None):
        match = _match_for(request, transaction_id)
        if match is None:
            return Response({"error": _("Nothing to dismiss")}, status=status.HTTP_404_NOT_FOUND)
        try:
            feedback.dismiss(match)
        except feedback.MatchError as e:
            return Response({"error": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(operation_id="rules_matches_undo", tags=["rules"], request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def undo(self, request, transaction_id=None, team_slug=None, book_slug=None):
        match = _match_for(request, transaction_id)
        if match is None:
            return Response({"error": _("Nothing to undo")}, status=status.HTTP_404_NOT_FOUND)
        try:
            feedback.undo(match)
        except feedback.MatchError as e:
            return Response({"error": str(e)}, status=status.HTTP_409_CONFLICT)
        except GUARD_ERRORS as e:
            return Response({"error": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RuleProposalViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Rules the book's history proposes (`services.learning`)."""

    serializer_class = RuleProposalSerializer
    permission_classes = [BookAccessPermissions]
    pagination_class = None
    queryset = RuleProposal.objects.none()

    def get_queryset(self):
        return RuleProposal.objects.filter(book=self.request.book, status=RuleProposal.STATUS_OPEN).select_related(
            "category"
        )

    def _proposal(self, pk):
        return self.get_queryset().filter(pk=pk).first()

    @extend_schema(operation_id="rules_proposals_dismiss", tags=["rules"], request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None, team_slug=None, book_slug=None):
        proposal = self._proposal(pk)
        if proposal is None:
            return Response({"error": _("Proposal not found")}, status=status.HTTP_404_NOT_FOUND)
        proposal.status = RuleProposal.STATUS_DISMISSED
        proposal.save(update_fields=["status", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(operation_id="rules_proposals_accept", tags=["rules"], request=None)
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None, team_slug=None, book_slug=None):
        """The rule this proposal stands for, as a draft for the builder. Saving it marks the proposal accepted."""
        proposal = self._proposal(pk)
        if proposal is None:
            return Response({"error": _("Proposal not found")}, status=status.HTTP_404_NOT_FOUND)
        name = analysis._unique_name(request.book, f"{proposal.value.title()} → {proposal.category.name}")
        return Response(
            {
                "name": name,
                "direction": proposal.direction,
                "accounts": [],
                "match": engine.MATCH_ALL,
                "conditions": [{"field": proposal.field, "op": engine.OP_CONTAINS, "value": proposal.value}],
                "action": Rule.ACTION_CATEGORY,
                "category": proposal.category_id,
                "category_name": proposal.category.name,
                "mode": Rule.MODE_SUGGEST,
                "origin": Rule.ORIGIN_LEARNED,
                "proposal_id": proposal.pk,
            }
        )


@login_and_book_required
def rules_home(request, team_slug, book_slug):
    """The Rules page: the book's rules, the builder, and proposed rules."""
    from django.urls import reverse

    from apps.accounts.models import Account

    feed_accounts = list(
        Account.objects.filter(book=request.book, has_feed=True, is_hidden=False)
        .annotate(account_group_name=F("account_group__name"))
        .order_by("account_group__name", "name")
        .values("id", "name", "account_group_name")
    )
    base = reverse("rules:rules_home", args=request.book.url_args)
    return render(
        request,
        "rules/rules_home.html",
        {
            "page_title": _("Rules | {name}").format(name=book_display_name(request.book)),
            "active_tab": "accounts",
            "accounts_section": "rules",
            "rules_props": {
                "api": f"{base}api/",
                "book_base": request.book.base_url,
                "feed_url": reverse("bank_feed:bank_feed_home", args=request.book.url_args),
                "can_edit": is_admin(request.user, request.team),
                "categories": picker_accounts_data(request.book),
                "feed_accounts": feed_accounts,
            },
        },
    )
