"""
Views for goals app.
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from apps.teams.mixins import LoginAndTeamRequiredMixin

from .forms import GoalForm
from .models import Goal


# Goals Home View
class GoalsHomeView(LoginAndTeamRequiredMixin, TemplateView):
    """Home page for goals app."""

    template_name = "goals/goals_home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "goals"
        context["page_title"] = _("Goals | {team}").format(team=self.request.team)
        # Add counts for quick stats
        context["goals_count"] = Goal.for_team.count()
        return context


# Goal Views
class GoalViewMixin(LoginAndTeamRequiredMixin):
    """Mixin class for all Goal views."""

    model = Goal

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "goals"
        context["page_title"] = _("Goals | {team}").format(team=self.request.team)
        return context


class GoalListView(GoalViewMixin, ListView):
    """List all goals."""

    pass


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
        return reverse("goals:goal_list", args=[self.request.team.slug])
