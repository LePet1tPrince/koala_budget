"""
Views for accounts app.
"""

from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

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


# Accounts Home View
class AccountsHomeView(LoginAndTeamRequiredMixin, TemplateView):
    """Home page for accounts app."""

    template_name = "accounts/accounts_home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["page_title"] = _("Accounts | {team}").format(team=self.request.team)
        context["account_groups_count"] = AccountGroup.for_team.count()
        context["accounts_count"] = Account.for_team.count()
        context["payees_count"] = Payee.for_team.count()
        context["institutions_count"] = Institution.for_team.count()

        # Accounts grouped by type, in balance-sheet order, with balances annotated
        accounts = (
            Account.objects.filter(team=self.request.team).with_balance().select_related("account_group", "institution")
        )
        by_type = {}
        for account in accounts:
            by_type.setdefault(account.account_group.account_type, []).append(account)
        type_labels = dict(ACCOUNT_TYPE_CHOICES)
        type_order = [
            ACCOUNT_TYPE_ASSET,
            ACCOUNT_TYPE_LIABILITY,
            ACCOUNT_TYPE_INCOME,
            ACCOUNT_TYPE_EXPENSE,
            ACCOUNT_TYPE_EQUITY,
        ]
        context["grouped_accounts"] = [
            {"type": account_type, "label": type_labels[account_type], "accounts": by_type[account_type]}
            for account_type in type_order
            if account_type in by_type
        ]
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


class AccountListView(AccountViewMixin, ListView):
    """List all accounts."""

    def get_queryset(self):
        qs = super().get_queryset()
        account_type = self.request.GET.get("type")
        if account_type:
            qs = qs.filter(account_group__account_type=account_type)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["account_type_choices"] = ACCOUNT_TYPE_CHOICES
        context["selected_type"] = self.request.GET.get("type", "")
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
        context = super().get_context_data(**kwargs)
        context["journal_lines"] = self.object.journal_lines.all()
        context["return_type"] = self.request.GET.get("return_type", "")
        return context


class AccountUpdateView(AccountViewMixin, UpdateView):
    """Update an account."""

    form_class = AccountForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["team"] = self.request.team
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["return_type"] = self.request.GET.get("return_type", "") or self.request.POST.get("return_type", "")
        return context

    def get_success_url(self):
        return_type = self.request.POST.get("return_type", "")
        if return_type:
            url = reverse("accounts:account_list", args=[self.request.team.slug])
            return f"{url}?type={return_type}"
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["return_type"] = self.request.GET.get("return_type", "")
        return context

    def get_success_url(self):
        url = reverse("accounts:account_list", args=[self.request.team.slug])
        return_type = self.request.GET.get("return_type", "")
        if return_type:
            url = f"{url}?type={return_type}"
        return url


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
