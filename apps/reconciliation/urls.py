from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "reconciliation"

router = DefaultRouter()
router.register(r"reconciliations", views.ReconciliationViewSet, basename="reconciliation")

urlpatterns = [
    path("", views.hub, name="hub"),
    path("<int:account_id>/", views.account_page, name="account"),
    path("statement/<int:pk>/", views.statement_page, name="statement"),
    path("statement/<int:pk>/undo/", views.statement_undo, name="statement_undo"),
    path("api/", include(router.urls)),
]
