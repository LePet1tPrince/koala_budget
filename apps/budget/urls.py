"""
URL configuration for budget app.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "budget"

# API router for ViewSets
router = DefaultRouter()
router.register(r"budget", views.BudgetViewSet, basename="budget")

# URL patterns (all budget URLs are team-based)
urlpatterns = [
    path("", views.budget_month_view, name="budget_home"),
    path("api/", include(router.urls)),
]
