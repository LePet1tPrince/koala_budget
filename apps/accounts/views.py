"""
Views for accounts app.
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from apps.teams.mixins import LoginAndTeamRequiredMixin

from .forms import AccountForm, AccountGroupForm, PayeeForm
from .models import Account, AccountGroup, Payee


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

    pass


class AccountCreateView(AccountViewMixin, CreateView):
    """Create a new account."""

    form_class = AccountForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["team"] = self.request.team
        return kwargs

    def form_valid(self, form):
        form.instance.team = self.request.team
        return super().form_valid(form)


class AccountDetailView(AccountViewMixin, DetailView):
    """View details of an account."""

    pass


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
