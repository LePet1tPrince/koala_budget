from django.apps import AppConfig


class BudgetingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.budgeting"

    def ready(self):
        import apps.budgeting.signals  # noqa: F401
