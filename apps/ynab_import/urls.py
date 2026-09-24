"""URL configuration for the YNAB import wizard (all book-scoped)."""

from django.urls import path

from . import views

app_name = "ynab_import"

urlpatterns = [
    path("", views.ynab_import_home, name="home"),
    path("api/upload/", views.api_upload, name="api_upload"),
    path("api/preview/", views.api_preview, name="api_preview"),
    path("api/apply/", views.api_apply, name="api_apply"),
    path("api/status/", views.api_status, name="api_status"),
]
