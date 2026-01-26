# Goals Feature Design (Adjusted for Project Patterns)

> **Note:** This design has been adjusted to follow the existing project patterns in `apps/budget`.
> All changes should be made in `apps/budget` (NOT the deprecated `apps/goals` app).

## Overview

Goals allow users to set savings targets and allocate money toward them monthly. Each goal is backed by an equity-type Account in the chart of accounts, enabling proper double-entry accounting when money is spent from a goal.

---

## Django Models

Add the following to `apps/budget/models.py`:

```python
from decimal import Decimal

from django.db import models
from django.db.models import Sum, Q, F
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Account, AccountGroup, ACCOUNT_TYPE_EQUITY
from apps.teams.models import BaseTeamModel


class GoalQuerySet(models.QuerySet):
    def active(self):
        """Return only non-archived, non-complete goals."""
        return self.filter(is_archived=False, is_complete=False)

    def with_progress(self, month=None):
        """
        Annotate goals with their progress information for a given month.
        If month is None, uses current month.
        """
        from django.utils import timezone

        if month is None:
            month = timezone.now().date().replace(day=1)

        return self.annotate(
            # Total saved up to previous month
            saved_previous=Sum(
                "allocations__amount",
                filter=Q(allocations__month__lt=month),
                default=Decimal("0")
            ),
            # Saved this month
            saved_this_month=Sum(
                "allocations__amount",
                filter=Q(allocations__month=month),
                default=Decimal("0")
            ),
            # Total saved (all time)
            total_saved=Sum(
                "allocations__amount",
                default=Decimal("0")
            ),
            # Calculate remaining amount needed
            remaining=F("target_amount") - Sum(
                "allocations__amount",
                default=Decimal("0")
            )
        )


class Goal(BaseTeamModel):
    """
    Goal model for savings goals.
    Each goal is backed by an equity account in the chart of accounts.
    """

    name = models.CharField(max_length=200, verbose_name=_("Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))

    target_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        verbose_name=_("Target amount"),
        help_text=_("Target savings amount")
    )

    target_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Target date"),
        help_text=_("Target date to reach the goal")
    )

    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,
        related_name="goal",
        null=True,  # Allow null initially for migration
        blank=True,
        verbose_name=_("Account"),
        help_text=_("Associated equity account (automatically created)"),
    )

    is_complete = models.BooleanField(
        default=False,
        verbose_name=_("Completed"),
        help_text=_("Whether this goal has been completed")
    )

    is_archived = models.BooleanField(
        default=False,
        verbose_name=_("Archived"),
        help_text=_("Whether this goal is archived")
    )

    order = models.IntegerField(
        default=0,
        verbose_name=_("Order"),
        help_text=_("Display order for goals")
    )

    objects = GoalQuerySet.as_manager()

    class Meta:
        ordering = ["order", "target_date", "name"]
        unique_together = ["team", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("budget:goal_detail", kwargs={"team_slug": self.team.slug, "pk": self.pk})

    def save(self, *args, **kwargs):
        """Override save to automatically create backing account for new goals."""
        is_new = self.pk is None

        if is_new and not self.account_id:
            # Get or create the Goals account group
            goal_group, _ = AccountGroup.objects.get_or_create(
                team=self.team,
                account_type=ACCOUNT_TYPE_EQUITY,
                defaults={
                    "name": "Goals",
                    "description": "Savings goals"
                }
            )

            # Find the next available account number in the 3000s range (equity)
            last_goal_account = Account.objects.filter(
                team=self.team,
                account_number__startswith="3"
            ).order_by("-account_number").first()

            if last_goal_account:
                try:
                    next_number = int(last_goal_account.account_number) + 1
                except ValueError:
                    next_number = 3000
            else:
                next_number = 3000

            # Create the backing account
            self.account = Account.objects.create(
                team=self.team,
                name=f"Goal: {self.name}",
                account_number=str(next_number),
                account_group=goal_group
            )

        super().save(*args, **kwargs)

    @property
    def progress_percentage(self):
        """Calculate progress as a percentage."""
        if hasattr(self, "total_saved"):
            saved = self.total_saved or Decimal("0")
        else:
            saved = self.allocations.aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0")

        if self.target_amount > 0:
            return min(float(saved / self.target_amount * 100), 100)
        return 0


class GoalAllocation(BaseTeamModel):
    """
    Monthly allocation towards a goal.
    This represents how much is being saved toward the goal each month.
    """

    goal = models.ForeignKey(
        Goal,
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name=_("Goal")
    )

    month = models.DateField(
        verbose_name=_("Month"),
        help_text=_("Month of this allocation (first day of month)")
    )

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name=_("Amount"),
        help_text=_("Amount allocated this month")
    )

    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    class Meta:
        unique_together = ["team", "goal", "month"]
        ordering = ["-month"]

    def __str__(self):
        return f"{self.goal.name} - {self.month.strftime('%Y-%m')} - ${self.amount}"

    def save(self, *args, **kwargs):
        # Ensure month is always first day of month
        self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)
```

---

## Service Layer

Add `GoalService` to `apps/budget/services.py`:

```python
class GoalService:
    """Service class for goal-related calculations and queries."""

    def __init__(self, team):
        self.team = team

    def get_goals_with_progress(self, month=None, include_archived=False):
        """Get all goals with progress annotations for a given month."""
        qs = Goal.objects.filter(team=self.team)
        if not include_archived:
            qs = qs.filter(is_archived=False)
        return qs.with_progress(month).select_related("account")

    def get_total_saved(self):
        """Get the total amount saved across all active goals."""
        return GoalAllocation.objects.filter(
            team=self.team,
            goal__is_archived=False
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    def get_goal_summary(self, month):
        """Get summary data for the goals section of the budget page."""
        goals = self.get_goals_with_progress(month)
        total_target = goals.aggregate(total=Sum("target_amount"))["total"] or Decimal("0")
        total_saved = goals.aggregate(total=Sum("total_saved"))["total"] or Decimal("0")

        return {
            "goals": goals,
            "total_target": total_target,
            "total_saved": total_saved,
            "goal_count": goals.count(),
        }

    def update_allocation(self, goal, month, amount):
        """Create or update a goal allocation for a specific month."""
        month = month.replace(day=1)
        allocation, created = GoalAllocation.objects.update_or_create(
            team=self.team,
            goal=goal,
            month=month,
            defaults={"amount": amount}
        )
        return allocation
```

---

## Forms

Add to `apps/budget/forms.py`:

```python
from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Goal, GoalAllocation


class GoalForm(forms.ModelForm):
    """Form for creating and editing goals."""

    class Meta:
        model = Goal
        fields = ["name", "description", "target_amount", "target_date"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "description": forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 3}),
            "target_amount": forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "0.01"}),
            "target_date": forms.DateInput(attrs={"class": "input input-bordered w-full", "type": "date"}),
        }


class GoalAllocationForm(forms.ModelForm):
    """Form for editing goal allocations inline."""

    class Meta:
        model = GoalAllocation
        fields = ["amount"]
        widgets = {
            "amount": forms.NumberInput(attrs={
                "class": "input input-bordered input-sm w-24 text-right font-mono",
                "step": "0.01",
                "min": "0",
            }),
        }
```

---

## Views

Add to `apps/budget/views.py`:

```python
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from .forms import GoalForm, GoalAllocationForm
from .models import Goal, GoalAllocation
from .services import GoalService


@login_and_team_required
def goals_list_view(request, team_slug):
    """List all goals with progress for the selected month."""
    month_param = request.GET.get("month")
    if month_param:
        month = parse_date(month_param)
    else:
        month = date.today().replace(day=1)

    month = month.replace(day=1)
    service = GoalService(request.team)
    summary = service.get_goal_summary(month)

    # Build forms for inline allocation editing
    goals_with_forms = []
    for goal in summary["goals"]:
        allocation = GoalAllocation.objects.filter(
            team=request.team,
            goal=goal,
            month=month
        ).first()

        if allocation:
            form = GoalAllocationForm(instance=allocation)
        else:
            form = GoalAllocationForm(initial={"amount": Decimal("0")})

        goals_with_forms.append({
            "goal": goal,
            "form": form,
            "allocation": allocation,
        })

    return render(
        request,
        "budget/goals_list.html",
        {
            "active_tab": "goals",
            "page_title": f"Goals | {request.team}",
            "month": month,
            "goals_with_forms": goals_with_forms,
            "summary": summary,
            "prev_month": month - relativedelta(months=1),
            "next_month": month + relativedelta(months=1),
        },
    )


@login_and_team_required
def goal_create_view(request, team_slug):
    """Create a new goal."""
    if request.method == "POST":
        form = GoalForm(request.POST)
        if form.is_valid():
            goal = form.save(commit=False)
            goal.team = request.team
            goal.save()
            messages.success(request, _("Goal created successfully."))
            return redirect("budget:goals_list", team_slug=team_slug)
    else:
        form = GoalForm()

    return render(
        request,
        "budget/goal_form.html",
        {
            "active_tab": "goals",
            "page_title": f"New Goal | {request.team}",
            "form": form,
            "is_new": True,
        },
    )


@login_and_team_required
def goal_detail_view(request, team_slug, pk):
    """View a single goal with full details and allocation history."""
    goal = get_object_or_404(
        Goal.objects.filter(team=request.team).with_progress(),
        pk=pk
    )

    allocations = goal.allocations.all()[:12]  # Last 12 months

    return render(
        request,
        "budget/goal_detail.html",
        {
            "active_tab": "goals",
            "page_title": f"{goal.name} | {request.team}",
            "goal": goal,
            "allocations": allocations,
        },
    )


@login_and_team_required
def goal_update_view(request, team_slug, pk):
    """Update an existing goal."""
    goal = get_object_or_404(Goal.objects.filter(team=request.team), pk=pk)

    if request.method == "POST":
        form = GoalForm(request.POST, instance=goal)
        if form.is_valid():
            form.save()
            messages.success(request, _("Goal updated successfully."))
            return redirect("budget:goal_detail", team_slug=team_slug, pk=pk)
    else:
        form = GoalForm(instance=goal)

    return render(
        request,
        "budget/goal_form.html",
        {
            "active_tab": "goals",
            "page_title": f"Edit {goal.name} | {request.team}",
            "form": form,
            "goal": goal,
            "is_new": False,
        },
    )


@login_and_team_required
def goal_delete_view(request, team_slug, pk):
    """Delete a goal (or archive it)."""
    goal = get_object_or_404(Goal.objects.filter(team=request.team), pk=pk)

    if request.method == "POST":
        # Soft delete by archiving
        goal.is_archived = True
        goal.save()
        messages.success(request, _("Goal archived successfully."))
        return redirect("budget:goals_list", team_slug=team_slug)

    return render(
        request,
        "budget/goal_confirm_delete.html",
        {
            "active_tab": "goals",
            "page_title": f"Archive {goal.name} | {request.team}",
            "goal": goal,
        },
    )


@login_and_team_required
def goal_allocation_update_view(request, team_slug, pk):
    """Update a goal allocation for a specific month (AJAX-friendly)."""
    goal = get_object_or_404(Goal.objects.filter(team=request.team), pk=pk)

    if request.method == "POST":
        month_param = request.POST.get("month")
        amount = request.POST.get("amount", "0")

        if month_param:
            month = parse_date(month_param).replace(day=1)
        else:
            month = date.today().replace(day=1)

        try:
            amount = Decimal(amount)
        except (ValueError, TypeError):
            amount = Decimal("0")

        service = GoalService(request.team)
        service.update_allocation(goal, month, amount)

        # Return to goals list at the same month
        return redirect(f"/a/{team_slug}/budget/goals/?month={month.isoformat()}")

    return redirect("budget:goals_list", team_slug=team_slug)


@login_and_team_required
def goal_complete_view(request, team_slug, pk):
    """Mark a goal as complete."""
    goal = get_object_or_404(Goal.objects.filter(team=request.team), pk=pk)

    if request.method == "POST":
        goal.is_complete = True
        goal.save()
        messages.success(request, _("Congratulations! Goal marked as complete."))

    return redirect("budget:goal_detail", team_slug=team_slug, pk=pk)
```

---

## URL Configuration

Update `apps/budget/urls.py`:

```python
"""
URL configuration for budget app.
"""

from django.urls import path

from . import views

app_name = "budget"

# URL patterns (all budget URLs are team-based, mounted at /a/<team_slug>/budget/)
urlpatterns = [
    # Budget views
    path("", views.budget_month_view, name="budget_home"),

    # Goal views
    path("goals/", views.goals_list_view, name="goals_list"),
    path("goals/new/", views.goal_create_view, name="goal_create"),
    path("goals/<int:pk>/", views.goal_detail_view, name="goal_detail"),
    path("goals/<int:pk>/edit/", views.goal_update_view, name="goal_update"),
    path("goals/<int:pk>/delete/", views.goal_delete_view, name="goal_delete"),
    path("goals/<int:pk>/allocate/", views.goal_allocation_update_view, name="goal_allocate"),
    path("goals/<int:pk>/complete/", views.goal_complete_view, name="goal_complete"),
]
```

---

## Templates

### `templates/budget/goals_list.html`

```html
{% extends "budget/budget_base.html" %}
{% load static %}
{% load i18n %}

{% block app %}
  <nav aria-label="breadcrumbs">
    <ol class="pg-breadcrumbs">
      <li><a href="{% url 'budget:budget_home' team_slug=request.team.slug %}">{% translate "Budget" %}</a></li>
      <li class="pg-breadcrumb-active" aria-current="page">{% translate "Goals" %}</li>
    </ol>
  </nav>

  <div class="container mx-auto px-4 py-6">
    <!-- Header with Month Navigation -->
    <div class="flex justify-between items-center mb-6">
      <h1 class="text-3xl font-bold">{% translate "Savings Goals" %} – {{ month|date:"F Y" }}</h1>

      <div class="flex gap-2">
        <a href="?month={{ prev_month|date:'Y-m-d' }}" class="btn btn-outline btn-sm">
          ← {% translate "Previous" %}
        </a>
        <a href="?month={{ next_month|date:'Y-m-d' }}" class="btn btn-outline btn-sm">
          {% translate "Next" %} →
        </a>
        <a href="{% url 'budget:goal_create' team_slug=request.team.slug %}" class="btn btn-primary btn-sm">
          + {% translate "New Goal" %}
        </a>
      </div>
    </div>

    <!-- Summary Card -->
    <div class="stats shadow mb-6 w-full">
      <div class="stat">
        <div class="stat-title">{% translate "Total Goals" %}</div>
        <div class="stat-value">{{ summary.goal_count }}</div>
      </div>
      <div class="stat">
        <div class="stat-title">{% translate "Total Target" %}</div>
        <div class="stat-value text-primary">${{ summary.total_target|floatformat:2 }}</div>
      </div>
      <div class="stat">
        <div class="stat-title">{% translate "Total Saved" %}</div>
        <div class="stat-value text-success">${{ summary.total_saved|floatformat:2 }}</div>
      </div>
    </div>

    <!-- Goals Table -->
    <div class="overflow-x-auto bg-base-100 rounded-lg shadow">
      <table class="table w-full">
        <thead>
          <tr>
            <th>{% translate "Goal" %}</th>
            <th class="text-right">{% translate "Target" %}</th>
            <th class="text-right">{% translate "Saved" %}</th>
            <th class="text-center">{% translate "Progress" %}</th>
            <th class="text-right">{% translate "This Month" %}</th>
            <th class="text-center">{% translate "Action" %}</th>
          </tr>
        </thead>
        <tbody>
          {% for item in goals_with_forms %}
          <tr>
            <td>
              <a href="{% url 'budget:goal_detail' team_slug=request.team.slug pk=item.goal.pk %}" class="link link-hover">
                <div class="font-medium">{{ item.goal.name }}</div>
              </a>
              {% if item.goal.target_date %}
              <div class="text-sm text-gray-500">{% translate "Target:" %} {{ item.goal.target_date|date:"M d, Y" }}</div>
              {% endif %}
            </td>

            <td class="text-right font-mono">${{ item.goal.target_amount|floatformat:2 }}</td>

            <td class="text-right font-mono text-success">${{ item.goal.total_saved|floatformat:2 }}</td>

            <td class="text-center">
              <div class="flex items-center gap-2">
                <progress
                  class="progress progress-primary w-24"
                  value="{{ item.goal.progress_percentage }}"
                  max="100"
                ></progress>
                <span class="text-sm">{{ item.goal.progress_percentage|floatformat:0 }}%</span>
              </div>
            </td>

            <td class="text-right">
              <form method="post" action="{% url 'budget:goal_allocate' team_slug=request.team.slug pk=item.goal.pk %}" class="inline-flex items-center gap-2">
                {% csrf_token %}
                <input type="hidden" name="month" value="{{ month|date:'Y-m-d' }}">
                {{ item.form.amount }}
              </form>
            </td>

            <td class="text-center">
              <button type="submit" form="alloc-form-{{ item.goal.pk }}" class="btn btn-primary btn-sm">
                {% translate "Save" %}
              </button>
            </td>
          </tr>
          {% empty %}
          <tr>
            <td colspan="6" class="text-center text-gray-500 py-8">
              {% translate "No goals yet. Create your first savings goal!" %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
{% endblock %}
```

### `templates/budget/goal_form.html`

```html
{% extends "budget/budget_base.html" %}
{% load static %}
{% load i18n %}

{% block app %}
  <nav aria-label="breadcrumbs">
    <ol class="pg-breadcrumbs">
      <li><a href="{% url 'budget:budget_home' team_slug=request.team.slug %}">{% translate "Budget" %}</a></li>
      <li><a href="{% url 'budget:goals_list' team_slug=request.team.slug %}">{% translate "Goals" %}</a></li>
      <li class="pg-breadcrumb-active" aria-current="page">
        {% if is_new %}{% translate "New Goal" %}{% else %}{% translate "Edit Goal" %}{% endif %}
      </li>
    </ol>
  </nav>

  <div class="container mx-auto px-4 py-6 max-w-2xl">
    <h1 class="text-3xl font-bold mb-6">
      {% if is_new %}{% translate "Create New Goal" %}{% else %}{% translate "Edit Goal" %}{% endif %}
    </h1>

    <div class="card bg-base-100 shadow-xl">
      <div class="card-body">
        <form method="post">
          {% csrf_token %}

          <div class="form-control mb-4">
            <label class="label">
              <span class="label-text">{% translate "Goal Name" %}</span>
            </label>
            {{ form.name }}
            {% if form.name.errors %}
            <label class="label">
              <span class="label-text-alt text-error">{{ form.name.errors.0 }}</span>
            </label>
            {% endif %}
          </div>

          <div class="form-control mb-4">
            <label class="label">
              <span class="label-text">{% translate "Description" %}</span>
            </label>
            {{ form.description }}
          </div>

          <div class="grid grid-cols-2 gap-4 mb-4">
            <div class="form-control">
              <label class="label">
                <span class="label-text">{% translate "Target Amount" %}</span>
              </label>
              {{ form.target_amount }}
              {% if form.target_amount.errors %}
              <label class="label">
                <span class="label-text-alt text-error">{{ form.target_amount.errors.0 }}</span>
              </label>
              {% endif %}
            </div>

            <div class="form-control">
              <label class="label">
                <span class="label-text">{% translate "Target Date" %}</span>
              </label>
              {{ form.target_date }}
            </div>
          </div>

          <div class="card-actions justify-end mt-6">
            <a href="{% url 'budget:goals_list' team_slug=request.team.slug %}" class="btn btn-ghost">
              {% translate "Cancel" %}
            </a>
            <button type="submit" class="btn btn-primary">
              {% if is_new %}{% translate "Create Goal" %}{% else %}{% translate "Save Changes" %}{% endif %}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
{% endblock %}
```

### `templates/budget/goal_detail.html`

```html
{% extends "budget/budget_base.html" %}
{% load static %}
{% load i18n %}

{% block app %}
  <nav aria-label="breadcrumbs">
    <ol class="pg-breadcrumbs">
      <li><a href="{% url 'budget:budget_home' team_slug=request.team.slug %}">{% translate "Budget" %}</a></li>
      <li><a href="{% url 'budget:goals_list' team_slug=request.team.slug %}">{% translate "Goals" %}</a></li>
      <li class="pg-breadcrumb-active" aria-current="page">{{ goal.name }}</li>
    </ol>
  </nav>

  <div class="container mx-auto px-4 py-6">
    <div class="flex justify-between items-start mb-6">
      <div>
        <h1 class="text-3xl font-bold">{{ goal.name }}</h1>
        {% if goal.description %}
        <p class="text-gray-600 mt-2">{{ goal.description }}</p>
        {% endif %}
      </div>

      <div class="flex gap-2">
        <a href="{% url 'budget:goal_update' team_slug=request.team.slug pk=goal.pk %}" class="btn btn-outline btn-sm">
          {% translate "Edit" %}
        </a>
        {% if not goal.is_complete %}
        <form method="post" action="{% url 'budget:goal_complete' team_slug=request.team.slug pk=goal.pk %}">
          {% csrf_token %}
          <button type="submit" class="btn btn-success btn-sm">{% translate "Mark Complete" %}</button>
        </form>
        {% endif %}
      </div>
    </div>

    <!-- Progress Card -->
    <div class="card bg-base-100 shadow-xl mb-6">
      <div class="card-body">
        <div class="flex justify-between items-center mb-4">
          <div>
            <div class="text-sm text-gray-500">{% translate "Progress" %}</div>
            <div class="text-2xl font-bold">
              ${{ goal.total_saved|floatformat:2 }} / ${{ goal.target_amount|floatformat:2 }}
            </div>
          </div>
          <div class="text-4xl font-bold text-primary">{{ goal.progress_percentage|floatformat:0 }}%</div>
        </div>

        <progress
          class="progress progress-primary w-full h-4"
          value="{{ goal.progress_percentage }}"
          max="100"
        ></progress>

        {% if goal.target_date %}
        <div class="mt-4 text-sm text-gray-500">
          {% translate "Target Date:" %} {{ goal.target_date|date:"F d, Y" }}
        </div>
        {% endif %}

        {% if goal.is_complete %}
        <div class="alert alert-success mt-4">
          <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{% translate "Goal completed!" %}</span>
        </div>
        {% endif %}
      </div>
    </div>

    <!-- Allocation History -->
    <div class="card bg-base-100 shadow-xl">
      <div class="card-body">
        <h2 class="card-title">{% translate "Allocation History" %}</h2>

        <div class="overflow-x-auto">
          <table class="table w-full">
            <thead>
              <tr>
                <th>{% translate "Month" %}</th>
                <th class="text-right">{% translate "Amount" %}</th>
                <th>{% translate "Notes" %}</th>
              </tr>
            </thead>
            <tbody>
              {% for allocation in allocations %}
              <tr>
                <td>{{ allocation.month|date:"F Y" }}</td>
                <td class="text-right font-mono">${{ allocation.amount|floatformat:2 }}</td>
                <td>{{ allocation.notes|default:"-" }}</td>
              </tr>
              {% empty %}
              <tr>
                <td colspan="3" class="text-center text-gray-500">
                  {% translate "No allocations yet." %}
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
{% endblock %}
```

### `templates/budget/goal_confirm_delete.html`

```html
{% extends "budget/budget_base.html" %}
{% load static %}
{% load i18n %}

{% block app %}
  <div class="container mx-auto px-4 py-6 max-w-lg">
    <div class="card bg-base-100 shadow-xl">
      <div class="card-body">
        <h2 class="card-title text-warning">{% translate "Archive Goal" %}</h2>
        <p>{% blocktranslate with name=goal.name %}Are you sure you want to archive "{{ name }}"?{% endblocktranslate %}</p>
        <p class="text-sm text-gray-500">{% translate "The goal will be hidden but your allocation history will be preserved." %}</p>

        <div class="card-actions justify-end mt-4">
          <a href="{% url 'budget:goals_list' team_slug=request.team.slug %}" class="btn btn-ghost">
            {% translate "Cancel" %}
          </a>
          <form method="post">
            {% csrf_token %}
            <button type="submit" class="btn btn-warning">{% translate "Archive" %}</button>
          </form>
        </div>
      </div>
    </div>
  </div>
{% endblock %}
```

---

## Admin Configuration

Add to `apps/budget/admin.py`:

```python
from django.contrib import admin

from .models import Budget, Goal, GoalAllocation


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ["month", "category", "budget_amount", "team"]
    list_filter = ["month", "team"]
    search_fields = ["category__name"]
    autocomplete_fields = ["category", "team"]


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ["name", "target_amount", "target_date", "is_complete", "is_archived", "team"]
    list_filter = ["is_complete", "is_archived", "team"]
    search_fields = ["name"]
    autocomplete_fields = ["account", "team"]


@admin.register(GoalAllocation)
class GoalAllocationAdmin(admin.ModelAdmin):
    list_display = ["goal", "month", "amount", "team"]
    list_filter = ["month", "team"]
    search_fields = ["goal__name"]
    autocomplete_fields = ["goal", "team"]
```

---

## Migration Steps

1. Create migrations:
   ```bash
   make migrations
   ```

2. Apply migrations:
   ```bash
   make migrate
   ```

---

## Testing Checklist

### Model Tests
- [ ] Creating a goal automatically creates a backing equity account
- [ ] Account number is auto-assigned in 3000s range
- [ ] `with_progress()` queryset method calculates correctly
- [ ] `progress_percentage` property works with and without annotations
- [ ] Deleting a goal cascades to delete the account
- [ ] GoalAllocation enforces unique constraint on (team, goal, month)

### View Tests
- [ ] Goals list shows all non-archived goals with progress
- [ ] Month navigation preserves goal data
- [ ] Goal CRUD operations work correctly
- [ ] Allocation updates persist correctly
- [ ] Team scoping prevents access to other teams' goals

### Integration Tests
- [ ] Full flow: create goal → allocate monthly → view progress
- [ ] Archive goal → goal hidden from list
- [ ] Mark goal complete → success message shown

---

## Future Enhancements (Out of Scope)

These features are NOT part of the initial implementation:

1. **React progress bar component** - For animated progress visualization
2. **Drag-and-drop reordering** - Would require React/Alpine.js
3. **Goal spending tracking** - Track journal entries against goal accounts
4. **NetWorthCard integration** - Show goals summary on main budget page
5. **Recurring allocations** - Automatically allocate same amount monthly
