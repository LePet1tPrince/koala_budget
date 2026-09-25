"""URL configuration for the onboarding walkthrough (all book-scoped)."""

from django.urls import path

from . import views

app_name = "onboarding"

urlpatterns = [
    path("", views.onboarding_home, name="home"),
    path("api/answers/", views.api_answers, name="api_answers"),
    path("api/preview-coa/", views.api_preview_coa, name="api_preview_coa"),
    path("api/complete/", views.api_complete, name="api_complete"),
    path("api/tasks/", views.api_tasks, name="api_tasks"),
    path("api/task/", views.api_task, name="api_task"),
    path("api/opening-balances/", views.api_opening_balances, name="api_opening_balances"),
    path("api/skip/", views.api_skip, name="api_skip"),
]
