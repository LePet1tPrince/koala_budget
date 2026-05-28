"""
Views for accounts app.
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from apps.teams.mixins import LoginAndTeamRequiredMixin

from .forms import AccountForm, AccountGroupForm, InstitutionForm, PayeeForm
from .models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_CHOICES, ACCOUNT_TYPE_LIABILITY, Account, AccountGroup, Institution, Payee


# Accounts Home View
class AccountsHomeView(LoginAndTeamRequiredMixin, TemplateView):
    """Home page for accounts app."""

    template_name = "accounts/accounts_home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "accounts"
        context["page_title"] = _("accounts | {team}").format(team=self.request.team)
        # Add counts for quick stats
        context["account_groups_count"] = AccountGroup.for_team.count()
        context["accounts_count"] = Account.for_team.count()
        context["payees_count"] = Payee.for_team.count()
        context["institutions_count"] = Institution.for_team.count()
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
        return context

    def form_valid(self, form):
        form.instance.team = self.request.team
        account_group = form.cleaned_data.get("account_group")
        if account_group:
            form.instance.has_feed = account_group.account_type in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY)
            if account_group.account_type not in (ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY):
                form.instance.institution = None
        return super().form_valid(form)


class AccountDetailView(AccountViewMixin, DetailView):
    """View details of an account."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["journal_lines"] = self.object.journal_lines.all()
        return context


class AccountUpdateView(AccountViewMixin, UpdateView):
    """Update an account."""

    form_class = AccountForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["team"] = self.request.team
        return kwargs


class AccountDeleteView(AccountViewMixin, DeleteView):
    """Delete an account."""

    def get_success_url(self):
        return reverse("accounts:account_list", args=[self.request.team.slug])


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
