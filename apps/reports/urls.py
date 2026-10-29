"""
URL configuration for reports app.
"""

from django.urls import path

from . import views

app_name = "reports"

# URL patterns (all reports URLs are book-based)
urlpatterns = [
    path("", views.reports_home, name="reports_home"),
    path("spending/", views.spending, name="spending"),
    path("net-worth/", views.net_worth, name="net_worth"),
    path("budget-and-goals/", views.budget_goals, name="budget_goals"),
    # CSV exports
    path("export/income-statement/", views.export_income_statement, name="export_income_statement"),
    path("export/balance-sheet/", views.export_balance_sheet, name="export_balance_sheet"),
    path("export/account/<int:account_id>/", views.export_account_activity_view, name="export_account_activity"),
    path("export/transactions/", views.export_transactions, name="export_transactions"),
]
