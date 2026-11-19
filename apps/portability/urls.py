"""URL configuration for the export/import page (all book-scoped)."""

from django.urls import path

from . import views

app_name = "portability"

urlpatterns = [
    path("", views.portability_home, name="home"),
    path("export/", views.export_view, name="export"),
    path("api/state/", views.StateView.as_view(), name="api_state"),
    path("api/upload/", views.UploadView.as_view(), name="api_upload"),
    path("api/apply/", views.ApplyView.as_view(), name="api_apply"),
    path("api/status/", views.StatusView.as_view(), name="api_status"),
    path("api/safety-export/", views.SafetyExportView.as_view(), name="api_safety_export"),
]
