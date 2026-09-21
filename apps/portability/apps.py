from django.apps import AppConfig


class PortabilityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.portability"
    verbose_name = "Data export/import"

    def ready(self):
        # Fail at startup, not at the first export, if a column in the format
        # has drifted from the FieldMaps that are supposed to explain it. See
        # `services/schema.py::validate_schema` for what this actually checks.
        from .services.schema import validate_schema

        validate_schema()
