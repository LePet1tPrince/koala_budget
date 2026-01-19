"""
Views for journal app.
Provides both template views and REST API endpoints for journal entries and lines.
"""

from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from apps.teams.mixins import LoginAndTeamRequiredMixin
from apps.accounts.models import Account, AccountGroup, Payee



# Accounts Home View
class TestingHomeView(LoginAndTeamRequiredMixin, TemplateView):
    """Home page for accounts app."""

    template_name = "testing/testing_home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "testing"
        context["page_title"] = _("testing | {team}").format(team=self.request.team)
        # Add counts for quick stats
        context["account_groups_count"] = AccountGroup.for_team.count()
        context["accounts_count"] = Account.for_team.count()
        context["payees_count"] = Payee.for_team.count()
        return context


class AccountViewMixin(LoginAndTeamRequiredMixin):
    """Mixin class for all Account views."""

    model = Account

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "Testing"
        context["page_title"] = _("Testing | {team}").format(team=self.request.team)
        return context


class AccountListView(AccountViewMixin, ListView):
    """List all accounts."""

    pass