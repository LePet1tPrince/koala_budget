from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "audit"

router = DefaultRouter()
router.register(r"events", views.AuditEventViewSet, basename="audit-event")

urlpatterns = [
    path("api/", include(router.urls)),
    path("log/", views.audit_log_view, name="audit_log"),
]
