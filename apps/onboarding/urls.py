"""URL configuration for the onboarding walkthrough (all book-scoped)."""

from django.urls import path

from . import views

app_name = "onboarding"

urlpatterns = [
    path("", views.onboarding_home, name="home"),
    # The no-JS fallback's form post; the app itself skips through `api/skip/`.
    path("skip/", views.skip_form, name="skip"),
    path("api/catalog/", views.CatalogView.as_view(), name="api_catalog"),
    path("api/state/", views.StateView.as_view(), name="api_state"),
    path("api/answers/", views.AnswersView.as_view(), name="api_answers"),
    path("api/preview-coa/", views.PreviewCoaView.as_view(), name="api_preview_coa"),
    path("api/complete/", views.CompleteView.as_view(), name="api_complete"),
    path("api/tasks/", views.TasksView.as_view(), name="api_tasks"),
    path("api/task/", views.TaskView.as_view(), name="api_task"),
    path("api/opening-balances/", views.OpeningBalancesView.as_view(), name="api_opening_balances"),
    path("api/skip/", views.SkipView.as_view(), name="api_skip"),
]
