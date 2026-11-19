"""
URL configuration for budget app.
"""

from django.urls import path

from . import views
from .api import views as api

app_name = "budget"

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
    # Goal views
    path("goals/", views.goals_list_view, name="goals_list"),
    path("goals/new/", views.goal_create_view, name="goal_create"),
    path("goals/link-preview/", views.goal_link_preview, name="goal_link_preview"),
    path("goals/<int:pk>/", views.goal_detail_view, name="goal_detail"),
    path("goals/<int:pk>/edit/", views.goal_update_view, name="goal_update"),
    path("goals/<int:pk>/delete/", views.goal_delete_view, name="goal_delete"),
    path("goals/<int:pk>/destroy/", views.goal_destroy, name="goal_destroy"),
    path("goals/<int:pk>/allocate/", views.goal_allocation_update_view, name="goal_allocate"),
    path("goals/<int:pk>/assign-available/", views.goal_assign_available, name="goal_assign_available"),
    path("goals/<int:pk>/withdraw/", views.goal_withdraw, name="goal_withdraw"),
    path("goals/<int:pk>/complete/", views.goal_complete_view, name="goal_complete"),
    path("goals/<int:pk>/close/", views.goal_close_view, name="goal_close"),
    path("goals/links/<int:link_pk>/unlink/", views.goal_unlink, name="goal_unlink"),
    path(
        "goals/contributions/<int:line_pk>/",
        views.goal_contribution_edit,
        name="goal_contribution_edit",
    ),
]
