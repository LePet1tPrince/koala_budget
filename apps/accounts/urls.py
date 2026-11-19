"""
URL configuration for accounts app.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api, views

app_name = "accounts"

# The accounts API (`/a/{team}/{book}/accounts/api/...`), see `api.py`.
router = DefaultRouter()
router.register(r"board", api.AccountsBoardViewSet, basename="board")
router.register(r"accounts", api.AccountViewSet, basename="account")
router.register(r"groups", api.AccountGroupViewSet, basename="account-group")
router.register(r"payees", api.PayeeViewSet, basename="payee")
router.register(r"institutions", api.InstitutionViewSet, basename="institution")

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
    path("accounts/new/", views.AccountCreateView.as_view(), name="account_create"),
    path("accounts/<int:pk>/", views.AccountDetailView.as_view(), name="account_detail"),
    path("accounts/<int:pk>/update/", views.AccountUpdateView.as_view(), name="account_update"),
    path("accounts/<int:pk>/delete/", views.AccountDeleteView.as_view(), name="account_delete"),
    # Payee URLs
    path("payees/", views.PayeeListView.as_view(), name="payee_list"),
    path("payees/new/", views.PayeeCreateView.as_view(), name="payee_create"),
    path("payees/<int:pk>/", views.PayeeDetailView.as_view(), name="payee_detail"),
    path("payees/<int:pk>/update/", views.PayeeUpdateView.as_view(), name="payee_update"),
    path("payees/<int:pk>/delete/", views.PayeeDeleteView.as_view(), name="payee_delete"),
    # Institution URLs
    path("institutions/", views.InstitutionListView.as_view(), name="institution_list"),
    path("institutions/new/", views.InstitutionCreateView.as_view(), name="institution_create"),
    path("institutions/<int:pk>/", views.InstitutionDetailView.as_view(), name="institution_detail"),
    path("institutions/<int:pk>/accounts/", views.InstitutionAccountsView.as_view(), name="institution_accounts"),
    path("institutions/<int:pk>/update/", views.InstitutionUpdateView.as_view(), name="institution_update"),
    path("institutions/<int:pk>/delete/", views.InstitutionDeleteView.as_view(), name="institution_delete"),
    path("api/board/", api.BoardView.as_view(), name="board"),
    path("api/", include(router.urls)),
]
