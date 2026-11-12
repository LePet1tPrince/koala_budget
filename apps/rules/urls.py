from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "rules"

router = DefaultRouter()
router.register(r"rules", views.RuleViewSet, basename="rule")
router.register(r"matches", views.RuleMatchViewSet, basename="rule-match")
router.register(r"proposals", views.RuleProposalViewSet, basename="rule-proposal")

urlpatterns = [
    path("", views.rules_home, name="rules_home"),
    path("api/", include(router.urls)),
]
