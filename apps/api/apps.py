from django.apps import AppConfig


class APIConfig(AppConfig):
    name = "apps.api"
    label = "api"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Registers the OpenAPI extension that documents the session-token scheme.
        from . import schema  # noqa: F401
