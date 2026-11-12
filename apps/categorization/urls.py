"""Mounted at `/a/{team}/{book}/bankfeed/rules/` (see `koala_budget/urls.py`)."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "categorization"

router = DefaultRouter()
router.register(r"rules", views.CategorizationRuleViewSet, basename="rule")

urlpatterns = [
    path("", views.rules_home, name="rules_home"),
    path("api/", include(router.urls)),
]
