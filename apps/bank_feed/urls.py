"""
URL configuration for bank_feed app.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "bank_feed"

# API router for ViewSets
router = DefaultRouter()
router.register(r"transactions", views.BankTransactionViewSet, basename="bank-feed-transaction")

# URL patterns (all bank_feed URLs are team-based)
urlpatterns = [
    path("", views.bank_feed_home, name="bank_feed_home"),
    path("api/", include(router.urls)),
]