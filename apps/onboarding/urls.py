"""URL configuration for the onboarding walkthrough (all team-scoped)."""

from django.urls import path

from . import views

app_name = "onboarding"

urlpatterns = [
    path("", views.onboarding_home, name="home"),
    path("api/answers/", views.api_answers, name="api_answers"),
    path("api/preview-coa/", views.api_preview_coa, name="api_preview_coa"),
    path("api/complete/", views.api_complete, name="api_complete"),
    path("api/skip/", views.api_skip, name="api_skip"),
]
