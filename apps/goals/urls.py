"""
URL configuration for goals app.
"""

from django.urls import path

from . import views

app_name = "goals"

urlpatterns = [
    # Home
    path("", views.GoalsHomeView.as_view(), name="goals_home"),
    # Goal URLs
    path("goals/", views.GoalListView.as_view(), name="goal_list"),
    path("goals/new/", views.GoalCreateView.as_view(), name="goal_create"),
    path("goals/<int:pk>/", views.GoalDetailView.as_view(), name="goal_detail"),
    path("goals/<int:pk>/update/", views.GoalUpdateView.as_view(), name="goal_update"),
    path("goals/<int:pk>/delete/", views.GoalDeleteView.as_view(), name="goal_delete"),
]
