"""URL configuration for the YNAB import wizard (all book-scoped)."""

from django.urls import path

from . import views

app_name = "ynab_import"

urlpatterns = [
    path("", views.ynab_import_home, name="home"),
    path("api/state/", views.StateView.as_view(), name="api_state"),
    path("api/upload/", views.UploadView.as_view(), name="api_upload"),
    path("api/preview/", views.PreviewView.as_view(), name="api_preview"),
    path("api/apply/", views.ApplyView.as_view(), name="api_apply"),
    path("api/status/", views.StatusView.as_view(), name="api_status"),
]
