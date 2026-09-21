"""URL configuration for the export/import page (all team-scoped)."""

from django.urls import path

from . import views

app_name = "portability"

urlpatterns = [
    path("", views.portability_home, name="home"),
    path("export/", views.export_view, name="export"),
    path("api/upload/", views.api_upload, name="api_upload"),
    path("api/apply/", views.api_apply, name="api_apply"),
    path("api/status/", views.api_status, name="api_status"),
    path("api/safety-export/", views.api_safety_export, name="api_safety_export"),
]
