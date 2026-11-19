"""
Request and response shapes of the data export/import API (`/a/{team}/{book}/data/api/...`).

The archive's manifest blocks (`source`, `checks`, `omitted`) are versioned with
the archive format (`services.schema`), so they travel as JSON objects rather than
a shape this API would have to change with every format version.
"""

from rest_framework import serializers

from apps.api.base import UploadField
from apps.utils.progress_serializers import ImportStartedFields, ImportStatusSerializer


class DataImportStatusSerializer(ImportStatusSerializer):
    safety_archive_available = serializers.BooleanField(
        help_text="The pre-import copy of the book can still be downloaded (`api/safety-export/`)."
    )


class DataImportStartedSerializer(ImportStartedFields, DataImportStatusSerializer):
    pass


class PortabilityPageSerializer(serializers.Serializer):
    book_name = serializers.CharField(help_text="What the user types to confirm an import.")
    uncategorized_count = serializers.IntegerField(help_text="Bank-feed rows not yet categorized.")
    resume = DataImportStatusSerializer(allow_null=True, help_text="An import uploaded or running, to pick back up.")


class DataArchiveFileSerializer(serializers.Serializer):
    source = serializers.JSONField(help_text="Where the archive came from (team and book names).")
    checks = serializers.JSONField(help_text="The archive's integrity figures (counts, totals, net worth, ...).")
    omitted = serializers.JSONField(help_text="What the export left out, and why.")
    hash_warnings = serializers.ListField(
        child=serializers.CharField(), help_text="One line per file whose hash did not match."
    )


class DataImportDestinationSerializer(serializers.Serializer):
    team_name = serializers.CharField()
    book_name = serializers.CharField()
    checks = serializers.JSONField(help_text="The same figures for the book the import would replace.")
    has_plaid = serializers.BooleanField(help_text="The book has linked banks, which an import unlinks.")


class DataUploadResultSerializer(serializers.Serializer):
    import_id = serializers.IntegerField()
    file = DataArchiveFileSerializer()
    destination = DataImportDestinationSerializer()


class DataUploadRequestSerializer(serializers.Serializer):
    file = UploadField(help_text="A Koala Budget export (.zip).")


class DataApplyRequestSerializer(serializers.Serializer):
    import_id = serializers.IntegerField()
    book_name = serializers.CharField(
        allow_blank=True, help_text="This book's name, typed exactly: what confirms that it is replaced."
    )
