"""URL configuration for the guided monthly review (team-scoped)."""

from django.urls import path

from . import views

app_name = "monthly_review"

urlpatterns = [
    path("", views.monthly_review_home, name="home"),
    path("api/step/", views.api_step, name="api_step"),
    path("api/complete/", views.api_complete, name="api_complete"),
    path("api/dismiss/", views.api_dismiss, name="api_dismiss"),
    path("export/", views.export_monthly_review, name="export"),
]
