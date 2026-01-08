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
    path("new/", views.GoalCreateView.as_view(), name="goal_create"),
    path("<int:pk>/", views.GoalDetailView.as_view(), name="goal_detail"),
    path("<int:pk>/update/", views.GoalUpdateView.as_view(), name="goal_update"),
    path("<int:pk>/delete/", views.GoalDeleteView.as_view(), name="goal_delete"),
]
