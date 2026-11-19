"""
The API shape of an import's progress (`apps.utils.progress.status_payload`), shared
by the YNAB import and the data import, whose status endpoints answer the same thing.
"""

from rest_framework import serializers

STATUS_CHOICES = ["uploaded", "running", "done", "failed"]


class ImportStatusSerializer(serializers.Serializer):
    """An import record's `as_dict()`, as the wizard's apply screen polls it."""

    id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=STATUS_CHOICES)
    progress = serializers.IntegerField(min_value=0, max_value=100, help_text="Percent complete.")
    step = serializers.CharField(allow_blank=True, help_text="What the import is doing right now.")
    error = serializers.CharField(allow_blank=True, help_text="Why a failed import failed; blank otherwise.")
    result = serializers.JSONField(help_text="What was written, once done (counts and the reconciliation).")
    started = serializers.BooleanField(help_text="A worker has picked the import up.")
    elapsed_seconds = serializers.FloatField(allow_null=True, help_text="How long the worker has been at it.")
    eta_seconds = serializers.IntegerField(allow_null=True, help_text="Estimated seconds left; null until knowable.")


class ImportStatusQuerySerializer(serializers.Serializer):
    import_id = serializers.IntegerField(help_text="The import to report on (one of this book's).")


class ImportStartedFields(serializers.Serializer):
    """Mixed into an app's status serializer for the answer to starting an import."""

    import_id = serializers.IntegerField()
    task_id = serializers.CharField(allow_blank=True, help_text="The Celery task; blank when it ran in the request.")
