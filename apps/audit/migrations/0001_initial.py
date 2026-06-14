import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("teams", "0005_invitation_archived_at_membership_archived_at_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("user_login", "User Login"),
                            ("user_logout", "User Logout"),
                            ("login_failed", "Login Failed"),
                            ("csv_upload_started", "CSV Upload Started"),
                            ("csv_upload_completed", "CSV Upload Completed"),
                            ("csv_upload_failed", "CSV Upload Failed"),
                            ("plaid_sync_started", "Plaid Sync Started"),
                            ("plaid_sync_completed", "Plaid Sync Completed"),
                            ("plaid_sync_failed", "Plaid Sync Failed"),
                            ("bulk_categorize", "Bulk Categorize"),
                            ("bulk_edit", "Bulk Edit"),
                            ("bulk_reconcile", "Bulk Reconcile"),
                            ("bulk_unreconcile", "Bulk Unreconcile"),
                            ("bulk_archive", "Bulk Archive"),
                            ("bulk_unarchive", "Bulk Unarchive"),
                            ("bulk_delete", "Bulk Delete"),
                            ("bulk_duplicate", "Bulk Duplicate"),
                            ("team_member_added", "Team Member Added"),
                            ("team_member_removed", "Team Member Removed"),
                        ],
                        max_length=50,
                    ),
                ),
                ("timestamp", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("metadata", models.JSONField(default=dict)),
                (
                    "team",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="teams.team",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Audit Event",
                "verbose_name_plural": "Audit Events",
                "ordering": ["-timestamp"],
            },
        ),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.PositiveIntegerField(null=True)),
                ("journal_entry_id", models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                (
                    "action",
                    models.CharField(
                        choices=[("CREATE", "Create"), ("UPDATE", "Update"), ("DELETE", "Delete")],
                        max_length=10,
                    ),
                ),
                ("timestamp", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("changes", models.JSONField(default=dict)),
                ("source_model", models.CharField(blank=True, max_length=50)),
                (
                    "content_type",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="audit.auditevent",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="teams.team",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Audit Log",
                "verbose_name_plural": "Audit Logs",
                "ordering": ["-timestamp"],
            },
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["journal_entry_id", "timestamp"], name="audit_audit_journal_3c3d8e_idx"),
        ),
    ]
