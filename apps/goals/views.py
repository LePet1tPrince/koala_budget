"""
Views for goals app.
"""

from datetime import date
from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.accounts.models import ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY
from apps.budget.services import BudgetService
from apps.journal.models import JournalLine
from apps.teams.mixins import LoginAndTeamRequiredMixin

from .forms import GoalForm
from .models import Goal


# Goals Home View
class GoalsHomeView(LoginAndTeamRequiredMixin, ListView):
    """Home page for goals app."""

    model = Goal
    template_name = "goals/goals_home.html"
    context_object_name = "object_list"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "goals"
        context["page_title"] = _("Goals | {team}").format(team=self.request.team)

        team = self.request.team

        # Calculate net worth: sum(debits) - sum(credits) for asset and liability accounts
        net_worth_data = JournalLine.objects.filter(
            team=team,
            account__account_group__account_type__in=[ACCOUNT_TYPE_ASSET, ACCOUNT_TYPE_LIABILITY]
        ).aggregate(
            total_debits=models.Sum('dr_amount'),
            total_credits=models.Sum('cr_amount')
        )
        total_debits = net_worth_data.get('total_debits') or Decimal('0')
        total_credits = net_worth_data.get('total_credits') or Decimal('0')
        net_worth = total_debits - total_credits

        # Calculate grand total available using BudgetService
        budget_service = BudgetService(team)
        current_month = date.today().replace(day=1)

        # Get all expense and income categories
        from apps.accounts.models import Account
        categories = Account.for_team.filter(
            account_group__account_type__in=("expense", "income"),
        )

        grand_total_available = Decimal('0')
        for category in categories:
            available = budget_service.available(category, current_month)
            grand_total_available += available

        # Calculate sum of all goals saved amounts
        goals_saved_total = Goal.for_team.aggregate(
            total_saved=models.Sum('saved_amount')
        )['total_saved'] or Decimal('0')

        # Calculate left to allocate
        left_to_allocate = net_worth - grand_total_available - goals_saved_total

        # Add to context
        context.update({
            "goals_count": Goal.for_team.count(),
            "net_worth": net_worth,
            "grand_total_available": grand_total_available,
            "goals_saved_total": goals_saved_total,
            "left_to_allocate": left_to_allocate,
        })

        return context

    def get_queryset(self):
        """Return goals for the current team."""
        return Goal.for_team.all()


# Goal Views
class GoalViewMixin(LoginAndTeamRequiredMixin):
    """Mixin class for all Goal views."""

    model = Goal

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "goals"
        context["page_title"] = _("Goals | {team}").format(team=self.request.team)
        return context


class GoalHomeView(GoalViewMixin, ListView):
    """List all goals."""

    template_name = "goals/goals_home.html"


class GoalCreateView(GoalViewMixin, CreateView):
    """Create a new goal."""

    form_class = GoalForm

    def form_valid(self, form):
        form.instance.team = self.request.team
        return super().form_valid(form)


class GoalDetailView(GoalViewMixin, DetailView):
    """View details of a goal."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        goal = self.get_object()
        context['remaining_amount'] = goal.goal_amount - goal.saved_amount
        return context


class GoalUpdateView(GoalViewMixin, UpdateView):
    """Update a goal."""

    form_class = GoalForm


class GoalDeleteView(GoalViewMixin, DeleteView):
    """Delete a goal."""

    def get_success_url(self):
        return reverse("goals:goals_home", args=[self.request.team.slug])
