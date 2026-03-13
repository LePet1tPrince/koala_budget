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
    path("autofill/", views.budget_autofill_view, name="budget_autofill"),
    # Goal views
    path("goals/", views.goals_list_view, name="goals_list"),
    path("goals/new/", views.goal_create_view, name="goal_create"),
    path("goals/<int:pk>/", views.goal_detail_view, name="goal_detail"),
    path("goals/<int:pk>/edit/", views.goal_update_view, name="goal_update"),
    path("goals/<int:pk>/delete/", views.goal_delete_view, name="goal_delete"),
    path("goals/<int:pk>/allocate/", views.goal_allocation_update_view, name="goal_allocate"),
    path("goals/<int:pk>/complete/", views.goal_complete_view, name="goal_complete"),
]
