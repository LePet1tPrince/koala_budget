"""
URL configuration for budgeting app.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "budgeting"

# API router for ViewSets
router = DefaultRouter()
router.register(r"account-types", views.AccountTypeViewSet, basename="account-type")
router.register(r"accounts", views.AccountViewSet, basename="account")
router.register(r"payees", views.PayeeViewSet, basename="payee")
router.register(r"transactions", views.TransactionViewSet, basename="transaction")
router.register(r"budgets", views.BudgetViewSet, basename="budget")
router.register(r"goals", views.GoalViewSet, basename="goal")

urlpatterns = [
    path("api/", include(router.urls)),
]
