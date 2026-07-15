"""
Views for accounts app.
"""

import json
from urllib.parse import urlencode

from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event
from apps.teams.decorators import login_and_team_required
from apps.teams.mixins import LoginAndTeamRequiredMixin

from .forms import AccountForm, AccountGroupForm, InstitutionForm, PayeeForm
from .models import (
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_CHOICES,
    ACCOUNT_TYPE_EQUITY,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_LIABILITY,
    Account,
    AccountGroup,
    Institution,
    Payee,
)

# Display order and section labels for the chart-of-accounts board
ACCOUNT_TYPE_ORDER = [
    ACCOUNT_TYPE_ASSET,
    ACCOUNT_TYPE_LIABILITY,
    ACCOUNT_TYPE_INCOME,
    ACCOUNT_TYPE_EXPENSE,
    ACCOUNT_TYPE_EQUITY,
]
ACCOUNT_TYPE_SECTION_LABELS = {
    ACCOUNT_TYPE_ASSET: _("Assets"),
    ACCOUNT_TYPE_LIABILITY: _("Liabilities"),
    ACCOUNT_TYPE_INCOME: _("Income"),
    ACCOUNT_TYPE_EXPENSE: _("Expenses"),
    ACCOUNT_TYPE_EQUITY: _("Goals"),
}

FEED_ACCOUNT_TYPES = (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)


def _account_payload(account, team_slug):
    """Account row shape shared by the accounts board props and the create API."""
    return {
        "id": account.pk,
        "name": account.name,
        "balance": str(account.balance),
        "institution": account.institution.name if account.institution else None,
        "hasFeed": account.has_feed,
        "isSystem": account.is_system,
        "url": account.get_absolute_url(),
        "editUrl": reverse("accounts:account_update", args=[team_slug, account.pk]),
    }


def _group_payload(group, team_slug, accounts=None):
    """Group card shape shared by the accounts board props and the create API."""
    return {
        "id": group.pk,
        "name": group.name,
        "accountType": group.account_type,
        "isSystem": group.is_system,
        "url": group.get_absolute_url(),
        "accounts": accounts if accounts is not None else [],
    }


# Accounts Home View
@method_decorator(ensure_csrf_cookie, name="dispatch")
class AccountsHomeView(LoginAndTeamRequiredMixin, TemplateView):
    """Home page for accounts app: drag-and-drop chart-of-accounts board.

    ensure_csrf_cookie: the board POSTs JSON (reorder/create) with the
    X-CSRFToken header, so the cookie must be set even though the page
    renders no <form>.
    """

    template_name = "accounts/accounts_home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["page_title"] = _("Accounts | {team}").format(team=self.request.team)

        team = self.request.team
        team_slug = team.slug

        accounts_by_group = {}
        accounts = (
            Account.objects.filter(team=team)
            .with_balance()
            .select_related("institution")
            .order_by("sort_order", "name")
        )
        for account in accounts:
            accounts_by_group.setdefault(account.account_group_id, []).append(
                _account_payload(account, team_slug)
            )

        groups_by_type = {account_type: [] for account_type in ACCOUNT_TYPE_ORDER}
        for group in AccountGroup.objects.filter(team=team).order_by("sort_order", "name"):
            groups_by_type[group.account_type].append(
                _group_payload(group, team_slug, accounts_by_group.get(group.pk, []))
            )

        account_create_url = reverse("accounts:account_create", args=[team_slug])
        context["manage_props"] = {
            "types": [
                {
                    "key": account_type,
                    "label": str(ACCOUNT_TYPE_SECTION_LABELS[account_type]),
                    "groups": groups_by_type[account_type],
                }
                for account_type in ACCOUNT_TYPE_ORDER
            ],
            "urls": {
                "reorderAccounts": reverse("accounts:api_reorder_accounts", args=[team_slug]),
                "reorderGroups": reverse("accounts:api_reorder_groups", args=[team_slug]),
                "createAccount": reverse("accounts:api_create_account", args=[team_slug]),
                "createGroup": reverse("accounts:api_create_group", args=[team_slug]),
                "accountCreatePage": account_create_url,
            },
        }
        return context


# Account Group Views
class AccountGroupViewMixin(LoginAndTeamRequiredMixin):
    """Mixin class for all AccountGroup views."""

    model = AccountGroup

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["page_title"] = _("Account Groups | {team}").format(team=self.request.team)
        return context


class AccountGroupListView(AccountGroupViewMixin, ListView):
    """List all account groups."""

    pass


class AccountGroupCreateView(AccountGroupViewMixin, CreateView):
    """Create a new account group."""

    form_class = AccountGroupForm

    def form_valid(self, form):
        form.instance.team = self.request.team
        return super().form_valid(form)


class AccountGroupDetailView(AccountGroupViewMixin, DetailView):
    """View details of an account group."""

    pass


class AccountGroupUpdateView(AccountGroupViewMixin, UpdateView):
    """Update an account group."""

    form_class = AccountGroupForm


class AccountGroupDeleteView(AccountGroupViewMixin, DeleteView):
    """Delete an account group."""

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.is_system:
            from django.contrib import messages

            messages.error(request, _("System account groups cannot be deleted."))
            return redirect(obj.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("accounts:accountgroup_list", args=[self.request.team.slug])


# Account Views
class AccountViewMixin(LoginAndTeamRequiredMixin):
    """Mixin class for all Account views."""

    model = Account

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["page_title"] = _("Accounts | {team}").format(team=self.request.team)
        return context


class AccountCreateView(AccountViewMixin, CreateView):
    """Create a new account."""

    form_class = AccountForm
    template_name = "accounts/account_create.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["team"] = self.request.team
        kwargs["is_create"] = True
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["account_types_with_groups"] = [
            {
                "value": value,
                "label": label,
                "groups": list(AccountGroup.for_team.filter(account_type=value)),
            }
            for value, label in ACCOUNT_TYPE_CHOICES
        ]
        context["initial_type"] = self.request.GET.get("account_type", "")
        context["initial_group"] = self.request.GET.get("account_group", "")
        context["initial_institution"] = self.request.GET.get("institution", "")
        return context

    def form_valid(self, form):
        form.instance.team = self.request.team
        account_group = form.cleaned_data.get("account_group")
        if account_group:
            form.instance.has_feed = account_group.account_type in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)
            if account_group.account_type not in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY):
                form.instance.institution = None

        response = super().form_valid(form)

        if self.request.POST.get("next_action") == "save_and_create_another":
            params = {
                "account_type": form.cleaned_data.get("account_type", ""),
                "account_group": form.instance.account_group_id or "",
            }
            if form.instance.institution_id:
                params["institution"] = form.instance.institution_id
            url = reverse("accounts:account_create", args=[self.request.team.slug])
            return redirect(f"{url}?{urlencode(params)}")

        return response


class AccountDetailView(AccountViewMixin, DetailView):
    """View details of an account."""

    def get_context_data(self, **kwargs):
        from datetime import date, datetime

        from apps.reports.services import ReportService

        context = super().get_context_data(**kwargs)
        context["journal_lines"] = self.object.journal_lines.all()

        # Activity section (same components as the reports drill-down):
        # date range from ?start_date/?end_date, defaulting to the current month.
        try:
            start_date = datetime.strptime(self.request.GET.get("start_date", ""), "%Y-%m-%d").date()
            end_date = datetime.strptime(self.request.GET.get("end_date", ""), "%Y-%m-%d").date()
        except ValueError:
            today = date.today()
            start_date = today.replace(day=1)
            end_date = today

        service = ReportService(self.request.team)
        report_data = service.get_account_activity(self.object, start_date, end_date)
        context["report_data"] = report_data
        context["balance_chart_data"] = ReportService.build_balance_chart_data(report_data, start_date, end_date)
        context["budget_chart_data"] = service.get_budget_vs_actual_chart_data(self.object, start_date, end_date)
        context["start_date"] = start_date
        context["end_date"] = end_date
        return context


class AccountUpdateView(AccountViewMixin, UpdateView):
    """Update an account."""

    form_class = AccountForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["team"] = self.request.team
        return kwargs

    def get_success_url(self):
        return self.object.get_absolute_url()


class AccountDeleteView(AccountViewMixin, DeleteView):
    """Delete an account."""

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.is_system:
            from django.contrib import messages

            messages.error(request, _("System accounts cannot be deleted."))
            return redirect(obj.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("accounts:accounts_home", args=[self.request.team.slug])


# Payee Views
class PayeeViewMixin(LoginAndTeamRequiredMixin):
    """Mixin class for all Payee views."""

    model = Payee

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["page_title"] = _("Payees | {team}").format(team=self.request.team)
        return context


class PayeeListView(PayeeViewMixin, ListView):
    """List all payees."""

    pass


class PayeeCreateView(PayeeViewMixin, CreateView):
    """Create a new payee."""

    form_class = PayeeForm

    def form_valid(self, form):
        form.instance.team = self.request.team
        return super().form_valid(form)


class PayeeDetailView(PayeeViewMixin, DetailView):
    """View details of a payee."""

    pass


class PayeeUpdateView(PayeeViewMixin, UpdateView):
    """Update a payee."""

    form_class = PayeeForm


class PayeeDeleteView(PayeeViewMixin, DeleteView):
    """Delete a payee."""

    def get_success_url(self):
        return reverse("accounts:payee_list", args=[self.request.team.slug])


# Institution Views
class InstitutionViewMixin(LoginAndTeamRequiredMixin):
    """Mixin class for all Institution views."""

    model = Institution

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["page_title"] = _("Institutions | {team}").format(team=self.request.team)
        return context


class InstitutionListView(InstitutionViewMixin, ListView):
    """List all institutions."""

    pass


class InstitutionCreateView(InstitutionViewMixin, CreateView):
    """Create a new institution."""

    form_class = InstitutionForm

    def form_valid(self, form):
        form.instance.team = self.request.team
        return super().form_valid(form)


class InstitutionDetailView(InstitutionViewMixin, DetailView):
    """View details of an institution."""

    pass


class InstitutionUpdateView(InstitutionViewMixin, UpdateView):
    """Update an institution."""

    form_class = InstitutionForm


class InstitutionDeleteView(InstitutionViewMixin, DeleteView):
    """Delete an institution."""

    def get_success_url(self):
        return reverse("accounts:institution_list", args=[self.request.team.slug])


# =============================================================================
# JSON API for the drag-and-drop chart-of-accounts board
# =============================================================================


def _json_body(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@login_and_team_required
@require_POST
def api_reorder_accounts(request, team_slug):
    """Persist account ordering (and group moves) from the board.

    Body: {"groups": [{"group_id": int, "account_ids": [int, ...]}, ...]}
    Each entry is the full ordered list of accounts now in that group; an account
    listed under a different group than its current one is moved there (same
    account type only). All-or-nothing.
    """
    payload = _json_body(request)
    if payload is None or not isinstance(payload.get("groups"), list) or len(payload["groups"]) > 100:
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    group_ids = []
    placements = {}  # account_id -> (group_id, position)
    for entry in payload["groups"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("account_ids"), list):
            return JsonResponse({"error": _("Invalid request body.")}, status=400)
        group_ids.append(entry.get("group_id"))
        for position, account_id in enumerate(entry["account_ids"]):
            if account_id in placements:
                return JsonResponse({"error": _("An account appears more than once.")}, status=400)
            placements[account_id] = (entry.get("group_id"), position)

    groups = {g.pk: g for g in AccountGroup.objects.filter(team=request.team, pk__in=group_ids)}
    if len(groups) != len(set(group_ids)):
        return JsonResponse({"error": _("Unknown account group.")}, status=400)

    accounts = {
        a.pk: a
        for a in Account.objects.filter(team=request.team, pk__in=placements).select_related("account_group")
    }
    if len(accounts) != len(placements):
        return JsonResponse({"error": _("Unknown account.")}, status=400)

    moved = 0
    for account_id, (group_id, position) in placements.items():
        account = accounts[account_id]
        group = groups[group_id]
        if account.account_group_id != group_id:
            if account.account_group.account_type != group.account_type:
                return JsonResponse(
                    {"error": _("Accounts can only be moved between groups of the same type.")}, status=400
                )
            moved += 1
        account.account_group = group
        account.sort_order = position

    with transaction.atomic():
        Account.objects.bulk_update(accounts.values(), ["account_group", "sort_order"], batch_size=500)

    if moved:
        log_event(
            AuditEvent.BULK_EDIT,
            request=request,
            metadata={"scope": "accounts_board", "action": "move_account", "moved": moved},
        )
    return JsonResponse({"ok": True})


@login_and_team_required
@require_POST
def api_reorder_groups(request, team_slug):
    """Persist account-group ordering within one account type.

    Body: {"account_type": str, "group_ids": [int, ...]}
    """
    payload = _json_body(request)
    if payload is None or not isinstance(payload.get("group_ids"), list):
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    account_type = payload.get("account_type")
    if account_type not in dict(ACCOUNT_TYPE_CHOICES):
        return JsonResponse({"error": _("Invalid account type.")}, status=400)

    group_ids = payload["group_ids"]
    groups = {
        g.pk: g
        for g in AccountGroup.objects.filter(team=request.team, account_type=account_type, pk__in=group_ids)
    }
    if len(groups) != len(group_ids) or len(set(group_ids)) != len(group_ids):
        return JsonResponse({"error": _("Unknown account group.")}, status=400)

    for position, group_id in enumerate(group_ids):
        groups[group_id].sort_order = position

    with transaction.atomic():
        AccountGroup.objects.bulk_update(groups.values(), ["sort_order"], batch_size=500)
    return JsonResponse({"ok": True})


@login_and_team_required
@require_POST
def api_create_account(request, team_slug):
    """Create an account at the bottom of a group (board inline "+" form).

    Body: {"name": str, "group_id": int}
    """
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 200:
        return JsonResponse({"error": _("Enter an account name (max 200 characters).")}, status=400)

    group = AccountGroup.objects.filter(team=request.team, pk=payload.get("group_id")).first()
    if group is None:
        return JsonResponse({"error": _("Unknown account group.")}, status=400)

    # Same uniqueness rule as AccountForm: name must be unique within the account type
    if Account.objects.filter(team=request.team, name=name, account_group__account_type=group.account_type).exists():
        return JsonResponse(
            {
                "error": _("An account named '%(name)s' already exists for account type '%(type)s'.")
                % {"name": name, "type": dict(ACCOUNT_TYPE_CHOICES)[group.account_type]}
            },
            status=400,
        )

    with transaction.atomic():
        next_order = (
            Account.objects.filter(team=request.team, account_group=group).aggregate(m=Max("sort_order"))["m"]
        )
        account = Account.objects.create(
            team=request.team,
            name=name,
            account_group=group,
            has_feed=group.account_type in FEED_ACCOUNT_TYPES,
            sort_order=0 if next_order is None else next_order + 1,
        )
    return JsonResponse({"account": _account_payload(account, team_slug)}, status=201)


@login_and_team_required
@require_POST
def api_create_group(request, team_slug):
    """Create an account group at the bottom of a type section (board inline "+" form).

    Body: {"name": str, "account_type": str}
    """
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": _("Invalid request body.")}, status=400)

    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 200:
        return JsonResponse({"error": _("Enter a group name (max 200 characters).")}, status=400)

    account_type = payload.get("account_type")
    if account_type not in dict(ACCOUNT_TYPE_CHOICES):
        return JsonResponse({"error": _("Invalid account type.")}, status=400)

    if AccountGroup.objects.filter(team=request.team, name=name).exists():
        return JsonResponse({"error": _("A group named '%(name)s' already exists.") % {"name": name}}, status=400)

    with transaction.atomic():
        next_order = (
            AccountGroup.objects.filter(team=request.team, account_type=account_type).aggregate(
                m=Max("sort_order")
            )["m"]
        )
        group = AccountGroup.objects.create(
            team=request.team,
            name=name,
            account_type=account_type,
            sort_order=0 if next_order is None else next_order + 1,
        )
    return JsonResponse({"group": _group_payload(group, team_slug)}, status=201)
