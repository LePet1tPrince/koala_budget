"""
Statement reconciliation: the hub, the per-account workspace, a finished statement.

Any team member may start, finish or undo a reconciliation (plan D8) -- the
feed's reconcile has always been a member action, and households share the
chore. Every lookup is scoped to `request.team`, so another team's account or
statement is a 404, never a cross-tenant write; `TeamModelAccessPermissions`
refuses anyone who is not an authenticated member before a view runs.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Account
from apps.teams.decorators import login_and_team_required
from apps.teams.permissions import TeamModelAccessPermissions

from . import presenters
from .models import Reconciliation
from .serializers import FinishSerializer, StartSerializer, TickSerializer, TickThroughSerializer, UpdateSerializer
from .services import session
from .services.candidates import reconciled_balance
from .services.session import ReconciliationError, StaleDifference
from .services.signs import is_reconcilable, to_statement


def _account(team, account_id):
    try:
        account = Account.objects.select_related("account_group", "team").get(pk=account_id, team=team)
    except (Account.DoesNotExist, ValueError, TypeError):
        raise Http404 from None
    if not is_reconcilable(account):
        raise Http404
    return account


def _reconciliation(team, pk):
    try:
        return Reconciliation.objects.select_related(
            "account", "account__account_group", "account__team", "completed_by"
        ).get(pk=pk, team=team)
    except (Reconciliation.DoesNotExist, ValueError, TypeError):
        raise Http404 from None


def _error(exc):
    code = status.HTTP_409_CONFLICT if isinstance(exc, StaleDifference) else status.HTTP_400_BAD_REQUEST
    return Response({"error": str(exc)}, status=code)


def _invalid(serializer):
    return Response({"error": _("Check the values you entered."), "fields": serializer.errors}, status=400)


@extend_schema(tags=["reconciliation"])
class ReconciliationViewSet(viewsets.ViewSet):
    """
    /a/{team_slug}/reconcile/api/reconciliations/

    Amounts in and out are in STATEMENT sign: what the paper statement prints.
    """

    permission_classes = [TeamModelAccessPermissions]

    def list(self, request, team_slug=None):
        account = _account(request.team, request.query_params.get("account"))
        draft = session.draft_for(account)
        return Response(
            {
                "account": presenters.account_payload(account),
                "draft": presenters.statement_payload(draft) if draft else None,
                "history": presenters.history_payload(account),
            }
        )

    def create(self, request, team_slug=None):
        serializer = StartSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        data = serializer.validated_data
        account = _account(request.team, data["account"])
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

    def retrieve(self, request, pk=None, team_slug=None):
        rec = _reconciliation(request.team, pk)
        if rec.is_draft:
            include_later = request.query_params.get("include_later") in ("1", "true")
            return Response(presenters.draft_payload(rec, include_later=include_later))
        return Response(presenters.completed_payload(rec))

    def partial_update(self, request, pk=None, team_slug=None):
        rec = _reconciliation(request.team, pk)
        serializer = UpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            session.update_statement(rec, **serializer.validated_data)
        except ReconciliationError as exc:
            return _error(exc)
        return Response(presenters.draft_payload(rec))

    def destroy(self, request, pk=None, team_slug=None):
        rec = _reconciliation(request.team, pk)
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
    def tick(self, request, pk=None, team_slug=None):
        rec = _reconciliation(request.team, pk)
        serializer = TickSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            session.tick(rec, serializer.validated_data["line_ids"], serializer.validated_data["ticked"])
        except ReconciliationError as exc:
            return _error(exc)
        return self._numbers(rec)

    @action(detail=True, methods=["post"])
    def tick_through(self, request, pk=None, team_slug=None):
        rec = _reconciliation(request.team, pk)
        serializer = TickThroughSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            ids = session.tick_through(rec, serializer.validated_data["date"])
        except ReconciliationError as exc:
            return _error(exc)
        return self._numbers(rec, ticked_ids=ids)

    @action(detail=True, methods=["post"])
    def untick_all(self, request, pk=None, team_slug=None):
        rec = _reconciliation(request.team, pk)
        try:
            session.untick_all(rec)
        except ReconciliationError as exc:
            return _error(exc)
        return self._numbers(rec)

    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None, team_slug=None):
        rec = _reconciliation(request.team, pk)
        serializer = FinishSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            rec = session.finish(rec, request.user, request=request, **serializer.validated_data)
        except ReconciliationError as exc:
            return _error(exc)
        return Response(presenters.completed_payload(_reconciliation(request.team, rec.pk)))

    @action(detail=True, methods=["post"])
    def undo(self, request, pk=None, team_slug=None):
        rec = _reconciliation(request.team, pk)
        try:
            session.undo(rec, request.user, request=request)
        except ReconciliationError as exc:
            return _error(exc)
        return Response(presenters.completed_payload(_reconciliation(request.team, rec.pk)))

    @action(detail=False, methods=["get"])
    def accounts(self, request, team_slug=None):
        return Response({"accounts": presenters.accounts_payload(request.team)})


@login_and_team_required
def hub(request, team_slug):
    """Every reconcilable account and where it stands -- the evidence page for the guarantee."""
    accounts = presenters.accounts_payload(request.team)
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


@login_and_team_required
@ensure_csrf_cookie
def account_page(request, team_slug, account_id):
    account = _account(request.team, account_id)
    draft = session.draft_for(account)
    previous = session.last_completed(account)
    preselect = [int(i) for i in request.GET.get("lines", "").split(",") if i.strip().isdigit()]
    api = reverse("reconciliation:reconciliation-list", args=[team_slug])
    props = {
        "account": presenters.account_payload(account),
        "draft_id": draft.id if draft else None,
        "preselect_line_ids": preselect,
        "default_statement_date": presenters.default_statement_date(account).isoformat(),
        "previous": presenters.statement_payload(previous) if previous else None,
        "reconciled_balance": presenters.money(to_statement(account, reconciled_balance(account))),
        "history": presenters.history_payload(account),
        "urls": {
            "api": api,
            "hub": reverse("reconciliation:hub", args=[team_slug]),
            "feed": reverse("bank_feed:bank_feed_home", args=[team_slug]),
            "account_detail": reverse("accounts:account_detail", args=[team_slug, account.id]),
        },
    }
    return render(
        request,
        "reconciliation/account.html",
        {"account": account, "reconcile_props": props, "active_tab": "reports"},
    )


@login_and_team_required
def statement_page(request, team_slug, pk):
    rec = _reconciliation(request.team, pk)
    if rec.is_draft:
        return redirect("reconciliation:account", team_slug, rec.account_id)
    return render(
        request,
        "reconciliation/statement.html",
        {"statement": presenters.completed_payload(rec), "rec": rec, "active_tab": "reports"},
    )


@login_and_team_required
@require_POST
def statement_undo(request, team_slug, pk):
    """The no-JS undo from the statement page."""
    rec = _reconciliation(request.team, pk)
    try:
        session.undo(rec, request.user, request=request)
    except ReconciliationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("Statement undone. Its transactions can be reconciled again."))
    return redirect("reconciliation:statement", team_slug, rec.pk)
