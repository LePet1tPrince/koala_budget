"""
URL configuration for plaid app.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "plaid"

# API router for ViewSets
router = DefaultRouter()
router.register(r"bank-feed", views.BankFeedViewSet, basename="bank-feed")
router.register(r"items", views.PlaidItemViewSet, basename="plaid-item")
router.register(r"accounts", views.PlaidAccountViewSet, basename="plaid-account")
router.register(r"transactions", views.PlaidTransactionViewSet, basename="imported-transaction")

# URL patterns (all plaid URLs are team-based)
urlpatterns = [
    path("api/", include(router.urls)),
    path("api/link-token/", views.create_link_token_view, name="create-link-token"),
    path("api/exchange-token/", views.exchange_public_token_view, name="exchange-public-token"),
]
