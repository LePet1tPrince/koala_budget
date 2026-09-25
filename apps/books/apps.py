from django.apps import AppConfig


class BooksConfig(AppConfig):
    name = "apps.books"
    label = "books"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa F401
