"""URL configuration for the guided monthly review (book-scoped)."""

from django.urls import path

from . import views

app_name = "monthly_review"

urlpatterns = [
    path("", views.monthly_review_home, name="home"),
    path("api/review/", views.ReviewView.as_view(), name="api_review"),
    path("api/step/", views.StepView.as_view(), name="api_step"),
    path("api/complete/", views.CompleteView.as_view(), name="api_complete"),
    path("api/dismiss/", views.DismissView.as_view(), name="api_dismiss"),
    path("export/", views.export_monthly_review, name="export"),
]
