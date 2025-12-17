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

urlpatterns = [
    path("api/", include(router.urls)),
]

