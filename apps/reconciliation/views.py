"""
Statement reconciliation: the hub, the per-account workspace, a finished statement.

Any team member may start, finish or undo a reconciliation (plan D8) -- the
feed's reconcile has always been a member action, and households share the
chore. Every lookup is scoped to `request.book`, so another book's account or
statement is a 404, never a cross-tenant write; `BookModelAccessPermissions`
refuses anyone who is not an authenticated member before a view runs.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Account, Payee
from apps.accounts.serializers import PayeeSerializer, SimpleAccountSerializer
from apps.books.decorators import login_and_book_required
from apps.books.permissions import BookModelAccessPermissions
from apps.journal.models import JournalLine

from . import presenters
from .models import Reconciliation
from .serializers import (
    ReconciliationFinishSerializer,
    ReconciliationStartSerializer,
    ReconciliationTickSerializer,
    ReconciliationTickThroughSerializer,
    ReconciliationUpdateSerializer,
)
from .services import session
from .services.candidates import reconciled_balance
from .services.session import ReconciliationError, StaleDifference
from .services.signs import is_reconcilable, to_statement


def _account(book, account_id):
    try:
        account = Account.objects.select_related("account_group", "book").get(pk=account_id, book=book)
    except (Account.DoesNotExist, ValueError, TypeError):
        raise Http404 from None
    if not is_reconcilable(account):
        raise Http404
    return account


def _reconciliation(book, pk):
    try:
        return Reconciliation.objects.select_related(
            "account", "account__account_group", "account__book__team", "completed_by"
        ).get(pk=pk, book=book)
    except (Reconciliation.DoesNotExist, ValueError, TypeError):
        raise Http404 from None


def _error(exc):
    code = status.HTTP_409_CONFLICT if isinstance(exc, StaleDifference) else status.HTTP_400_BAD_REQUEST
    return Response({"error": str(exc)}, status=code)


def _invalid(serializer):
    return Response({"error": _("Check the values you entered."), "fields": serializer.errors}, status=400)


_ID = OpenApiParameter("id", int, OpenApiParameter.PATH)
_ACCOUNT = OpenApiParameter("account", int, OpenApiParameter.QUERY, required=True)
_LATER = OpenApiParameter("include_later", bool, OpenApiParameter.QUERY)


def _doc(operation_id, request=None, parameters=(), responses=OpenApiTypes.OBJECT):
    return extend_schema(
        operation_id=f"reconciliation_{operation_id}",
        tags=["reconciliation"],
        request=request,
        parameters=list(parameters),
        responses=responses,
    )


@extend_schema_view(
    list=_doc("list", parameters=[_ACCOUNT]),
    create=_doc("start", request=ReconciliationStartSerializer),
    retrieve=_doc("retrieve", parameters=[_ID, _LATER]),
    partial_update=_doc("update", request=ReconciliationUpdateSerializer, parameters=[_ID]),
    destroy=_doc("discard", parameters=[_ID], responses={204: None}),
    tick=_doc("tick", request=ReconciliationTickSerializer, parameters=[_ID]),
    tick_through=_doc("tick_through", request=ReconciliationTickThroughSerializer, parameters=[_ID]),
    untick_all=_doc("untick_all", parameters=[_ID]),
    finish=_doc("finish", request=ReconciliationFinishSerializer, parameters=[_ID]),
    undo=_doc("undo", parameters=[_ID]),
    accounts=_doc("accounts"),
)
class ReconciliationViewSet(viewsets.ViewSet):
    """
    /a/{team_slug}/{book_slug}/reconcile/api/reconciliations/

    Amounts in and out are in STATEMENT sign: what the paper statement prints.
    """

    permission_classes = [BookModelAccessPermissions]

    def list(self, request, team_slug=None, book_slug=None):
        account = _account(request.book, request.query_params.get("account"))
        draft = session.draft_for(account)
        return Response(
            {
                "account": presenters.account_payload(account),
                "draft": presenters.statement_payload(draft) if draft else None,
                "history": presenters.history_payload(account),
            }
        )

    def create(self, request, team_slug=None, book_slug=None):
        serializer = ReconciliationStartSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        data = serializer.validated_data
        account = _account(request.book, data["account"])
        try:
            draft = session.start(
                account,
                data["statement_date"],
                data["statement_balance"],
                request.user,
                preselect_line_ids=data["line_ids"],
                request=request,
            )
        except ReconciliationError as exc:
            return _error(exc)
        return Response(presenters.draft_payload(draft), status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None, team_slug=None, book_slug=None):
        rec = _reconciliation(request.book, pk)
        if rec.is_draft:
            include_later = request.query_params.get("include_later") in ("1", "true")
            return Response(presenters.draft_payload(rec, include_later=include_later))
        return Response(presenters.completed_payload(rec))

    def partial_update(self, request, pk=None, team_slug=None, book_slug=None):
        rec = _reconciliation(request.book, pk)
        serializer = ReconciliationUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            session.update_statement(rec, **serializer.validated_data)
        except ReconciliationError as exc:
            return _error(exc)
        return Response(presenters.draft_payload(rec))

    def destroy(self, request, pk=None, team_slug=None, book_slug=None):
        rec = _reconciliation(request.book, pk)
        try:
            session.discard(rec)
        except ReconciliationError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _numbers(self, rec, **extra):
        numbers = presenters.draft_numbers(rec)
        numbers.pop("lines")
        return Response({**numbers, **extra})

    @action(detail=True, methods=["post"])
    def tick(self, request, pk=None, team_slug=None, book_slug=None):
        rec = _reconciliation(request.book, pk)
        serializer = ReconciliationTickSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            session.tick(rec, serializer.validated_data["line_ids"], serializer.validated_data["ticked"])
        except ReconciliationError as exc:
            return _error(exc)
        return self._numbers(rec)

    @action(detail=True, methods=["post"])
    def tick_through(self, request, pk=None, team_slug=None, book_slug=None):
        rec = _reconciliation(request.book, pk)
        serializer = ReconciliationTickThroughSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            ids = session.tick_through(rec, serializer.validated_data["date"])
        except ReconciliationError as exc:
            return _error(exc)
        return self._numbers(rec, ticked_ids=ids)

    @action(detail=True, methods=["post"])
    def untick_all(self, request, pk=None, team_slug=None, book_slug=None):
        rec = _reconciliation(request.book, pk)
        try:
            session.untick_all(rec)
        except ReconciliationError as exc:
            return _error(exc)
        return self._numbers(rec)

    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None, team_slug=None, book_slug=None):
        rec = _reconciliation(request.book, pk)
        serializer = ReconciliationFinishSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            rec = session.finish(rec, request.user, request=request, **serializer.validated_data)
        except ReconciliationError as exc:
            return _error(exc)
        return Response(presenters.completed_payload(_reconciliation(request.book, rec.pk)))

    @action(detail=True, methods=["post"])
    def undo(self, request, pk=None, team_slug=None, book_slug=None):
        rec = _reconciliation(request.book, pk)
        try:
            session.undo(rec, request.user, request=request)
        except ReconciliationError as exc:
            return _error(exc)
        return Response(presenters.completed_payload(_reconciliation(request.book, rec.pk)))

    @action(detail=False, methods=["get"])
    def accounts(self, request, team_slug=None, book_slug=None):
        return Response({"accounts": presenters.accounts_payload(request.book)})


@login_and_book_required
def hub(request, team_slug, book_slug):
    """Every reconcilable account and where it stands -- the evidence page for the guarantee."""
    accounts = presenters.accounts_payload(request.book)
    return render(
        request,
        "reconciliation/hub.html",
        {
            "accounts": accounts,
            "all_intact": bool(accounts)
            and all(a["last_statement"] and a["last_statement"]["intact"] for a in accounts),
            "active_tab": "reports",
        },
    )


@login_and_book_required
@ensure_csrf_cookie
def account_page(request, team_slug, book_slug, account_id):
    account = _account(request.book, account_id)
    draft = session.draft_for(account)
    previous = session.last_completed(account)
    preselect = [int(i) for i in request.GET.get("lines", "").split(",") if i.strip().isdigit()]
    # The bank feed hands over its selection as journal entry ids (a feed row knows
    # its entry, not its line); this account's line on each is what gets ticked.
    entries = [int(i) for i in request.GET.get("entries", "").split(",") if i.strip().isdigit()]
    if entries:
        preselect += list(
            JournalLine.objects.filter(
                book=request.book, account=account, journal_entry_id__in=entries, is_reconciled=False
            ).values_list("id", flat=True)
        )
    api = reverse("reconciliation:reconciliation-list", args=[team_slug, book_slug])
    props = {
        "account": presenters.account_payload(account),
        "draft_id": draft.id if draft else None,
        "preselect_line_ids": preselect,
        "default_statement_date": presenters.default_statement_date(account).isoformat(),
        "previous": presenters.statement_payload(previous) if previous else None,
        "reconciled_balance": presenters.money(to_statement(account, reconciled_balance(account))),
        "history": presenters.history_payload(account),
        "book_base": request.book.base_url,
        # The "add a missing transaction" modal is the feed's own, so it needs the
        # feed's pickers -- only for an account that has a feed to add to.
        "all_accounts": SimpleAccountSerializer(
            Account.objects.filter(book=request.book).select_related("account_group", "institution").order_by("name"),
            many=True,
        ).data
        if account.has_feed
        else [],
        "all_payees": PayeeSerializer(Payee.objects.filter(book=request.book).order_by("name"), many=True).data
        if account.has_feed
        else [],
        "urls": {
            "api": api,
            "hub": reverse("reconciliation:hub", args=[team_slug, book_slug]),
            "feed": reverse("bank_feed:bank_feed_home", args=[team_slug, book_slug]),
            "account_detail": reverse("accounts:account_detail", args=[team_slug, book_slug, account.id]),
        },
    }
    return render(
        request,
        "reconciliation/account.html",
        {"account": account, "reconcile_props": props, "active_tab": "reports"},
    )


@login_and_book_required
def statement_page(request, team_slug, book_slug, pk):
    rec = _reconciliation(request.book, pk)
    if rec.is_draft:
        return redirect("reconciliation:account", team_slug, book_slug, rec.account_id)
    return render(
        request,
        "reconciliation/statement.html",
        {"statement": presenters.completed_payload(rec), "rec": rec, "active_tab": "reports"},
    )


@login_and_book_required
@require_POST
def statement_undo(request, team_slug, book_slug, pk):
    """The no-JS undo from the statement page."""
    rec = _reconciliation(request.book, pk)
    try:
        session.undo(rec, request.user, request=request)
    except ReconciliationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("Statement undone. Its transactions can be reconciled again."))
    return redirect("reconciliation:statement", team_slug, book_slug, rec.pk)
