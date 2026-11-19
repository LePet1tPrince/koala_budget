"""
URL configuration for budget app.
"""

from django.urls import path

from . import views
from .api import goals as goals_api
from .api import views as api

app_name = "budget"

goals = goals_api.GoalViewSet.as_view({"get": "list", "post": "create"})
goal = goals_api.GoalViewSet.as_view(
    {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
)


def goal_action(name):
    return goals_api.GoalViewSet.as_view({"get": name} if name == "activity" else {"post": name})


# URL patterns (all budget URLs are book-based, mounted at /a/<team_slug>/<book_slug>/budget/)
urlpatterns = [
    # Budget views
    path("", views.budget_month_view, name="budget_home"),
    # No-JS form posts (with JS the page uses the API below and never navigates)
    path("autofill/", views.budget_autofill_view, name="budget_autofill"),
    path("categories/<int:pk>/visibility/", views.budget_category_visibility, name="category_visibility"),
    path("grid/", views.budget_grid_view, name="budget_grid"),
    # Budget API (apps/budget/api/)
    path("api/month/", api.BudgetMonthView.as_view(), name="api_month"),
    path("api/amount/", api.BudgetAmountView.as_view(), name="api_amount"),
    path("api/cover/", api.BudgetCoverView.as_view(), name="api_cover"),
    path(
        "api/categories/<int:pk>/visibility/",
        api.BudgetCategoryVisibilityView.as_view(),
        name="api_category_visibility",
    ),
    path("api/autofill/", api.BudgetAutofillView.as_view(), name="api_autofill"),
    path("api/grid/", api.BudgetGridView.as_view(), name="api_grid"),
    path("api/grid/save/", api.BudgetGridSaveView.as_view(), name="api_grid_save"),
    path("api/unassigned/", api.UnassignedView.as_view(), name="api_unassigned"),
    # Goal API (apps/budget/api/goals.py)
    path("api/goals/", goals, name="api_goals"),
    path("api/goals/link-preview/", goals_api.GoalLinkPreviewView.as_view(), name="api_goal_link_preview"),
    path("api/goals/<int:pk>/", goal, name="api_goal"),
    path("api/goals/<int:pk>/activity/", goal_action("activity"), name="api_goal_activity"),
    path("api/goals/<int:pk>/allocate/", goal_action("allocate"), name="api_goal_allocate"),
    path("api/goals/<int:pk>/assign/", goal_action("assign"), name="api_goal_assign"),
    path("api/goals/<int:pk>/withdraw/", goal_action("withdraw"), name="api_goal_withdraw"),
    path("api/goals/<int:pk>/complete/", goal_action("complete"), name="api_goal_complete"),
    path("api/goals/<int:pk>/close/", goal_action("close"), name="api_goal_close"),
    path("api/goals/<int:pk>/archive/", goal_action("archive"), name="api_goal_archive"),
    path("api/goals/links/<int:link_pk>/unlink/", goals_api.GoalUnlinkView.as_view(), name="api_goal_unlink"),
    path(
        "api/goals/contributions/<int:line_pk>/",
        goals_api.GoalContributionView.as_view(),
        name="api_goal_contribution",
    ),
    # Goal pages and their form posts (with JS the goals page uses the goal API above)
    path("goals/", views.goals_list_view, name="goals_list"),
    path("goals/new/", views.goal_create_view, name="goal_create"),
    path("goals/<int:pk>/", views.goal_detail_view, name="goal_detail"),
    path("goals/<int:pk>/edit/", views.goal_update_view, name="goal_update"),
    path("goals/<int:pk>/delete/", views.goal_delete_view, name="goal_delete"),
    path("goals/<int:pk>/destroy/", views.goal_destroy, name="goal_destroy"),
    path("goals/<int:pk>/allocate/", views.goal_allocation_update_view, name="goal_allocate"),
    path("goals/<int:pk>/complete/", views.goal_complete_view, name="goal_complete"),
    path("goals/<int:pk>/close/", views.goal_close_view, name="goal_close"),
    path("goals/links/<int:link_pk>/unlink/", views.goal_unlink, name="goal_unlink"),
    path(
        "goals/contributions/<int:line_pk>/",
        views.goal_contribution_edit,
        name="goal_contribution_edit",
    ),
]
