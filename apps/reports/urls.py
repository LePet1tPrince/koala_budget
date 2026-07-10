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
    path("income-statement/account/<int:account_id>/", views.account_activity, name="account_activity"),
    path("balance-sheet/", views.balance_sheet, name="balance_sheet"),
    path("net-worth-trend/", views.net_worth_trend, name="net_worth_trend"),
    path("cash-flow/", views.cash_flow, name="cash_flow"),
    path("budget-vs-actual/", views.budget_vs_actual, name="budget_vs_actual"),
    path("goal-progress/", views.goal_progress, name="goal_progress"),
    # CSV exports
    path("export/income-statement/", views.export_income_statement, name="export_income_statement"),
    path("export/balance-sheet/", views.export_balance_sheet, name="export_balance_sheet"),
    path("export/account/<int:account_id>/", views.export_account_activity_view, name="export_account_activity"),
    path("export/transactions/", views.export_transactions, name="export_transactions"),
]
