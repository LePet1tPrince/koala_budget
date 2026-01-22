"""
URL configuration for reports app.
"""

from django.urls import path

from . import views

app_name = "reports"

# URL patterns (all reports URLs are team-based)
urlpatterns = [
    path("", views.reports_home, name="reports_home"),
    path("income-statement/", views.income_statement, name="income_statement"),
    path("income-statement/account/<int:pk>/", views.account_activity, name="account_activity"),
    path("balance-sheet/", views.balance_sheet, name="balance_sheet"),
    path("net-worth-trend/", views.net_worth_trend, name="net_worth_trend"),
]
