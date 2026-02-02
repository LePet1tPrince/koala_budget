"""
URL configuration for journal app.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "journal"

# API router for ViewSets
router = DefaultRouter()
router.register(r"journal-entries", views.JournalEntryViewSet, basename="journal-entry")
router.register(r"lines", views.SimpleLineViewSet, basename="line")
router.register(r"transactions", views.TransactionViewSet, basename="transaction")

# URL patterns (all journal URLs are team-based)
urlpatterns = [
    path("transactions/", views.transactions_home, name="transactions_home"),
    path("api/", include(router.urls)),
]
