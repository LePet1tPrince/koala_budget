"""
URL configuration for budget app.
"""

from django.urls import path

from . import views

app_name = "budget"

# API router for ViewSets
# URL patterns (all budget URLs are team-based)
urlpatterns = [
    path("", views.budget_month_view, name="budget_home"),
]
