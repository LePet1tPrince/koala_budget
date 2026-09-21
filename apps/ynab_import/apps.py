from django.apps import AppConfig


class YnabImportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ynab_import"
    verbose_name = "YNAB Import"
