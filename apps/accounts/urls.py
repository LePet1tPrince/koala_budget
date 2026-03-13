"""
URL configuration for accounts app.
"""

from django.urls import path

from . import api_views, views

app_name = "accounts"

urlpatterns = [
    # Home
    path("", views.AccountsHomeView.as_view(), name="accounts_home"),
    # Account Group URLs
    path("account-groups/", views.AccountGroupListView.as_view(), name="accountgroup_list"),
    path("account-groups/new/", views.AccountGroupCreateView.as_view(), name="accountgroup_create"),
    path("account-groups/<int:pk>/", views.AccountGroupDetailView.as_view(), name="accountgroup_detail"),
    path("account-groups/<int:pk>/update/", views.AccountGroupUpdateView.as_view(), name="accountgroup_update"),
    path("account-groups/<int:pk>/delete/", views.AccountGroupDeleteView.as_view(), name="accountgroup_delete"),
    # Account URLs
    path("accounts/", views.AccountListView.as_view(), name="account_list"),
    path("accounts/new/", views.AccountCreateView.as_view(), name="account_create"),
    path("accounts/bulk-edit/", views.AccountBulkEditView.as_view(), name="account_bulk_edit"),
    path("accounts/bulk-edit/data/", api_views.AccountBulkListView.as_view(), name="account_bulk_data"),
    path("accounts/bulk-edit/save/", api_views.AccountBulkUpdateView.as_view(), name="account_bulk_save"),
    path("accounts/bulk-edit/export-csv/", api_views.AccountCSVExportView.as_view(), name="account_export_csv"),
    path("accounts/bulk-edit/import-csv/", api_views.AccountCSVImportView.as_view(), name="account_import_csv"),
    path("accounts/<int:pk>/", views.AccountDetailView.as_view(), name="account_detail"),
    path("accounts/<int:pk>/update/", views.AccountUpdateView.as_view(), name="account_update"),
    path("accounts/<int:pk>/delete/", views.AccountDeleteView.as_view(), name="account_delete"),
    # Payee URLs
    path("payees/", views.PayeeListView.as_view(), name="payee_list"),
    path("payees/new/", views.PayeeCreateView.as_view(), name="payee_create"),
    path("payees/<int:pk>/", views.PayeeDetailView.as_view(), name="payee_detail"),
    path("payees/<int:pk>/update/", views.PayeeUpdateView.as_view(), name="payee_update"),
    path("payees/<int:pk>/delete/", views.PayeeDeleteView.as_view(), name="payee_delete"),
]
