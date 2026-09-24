"""
Audit rows record the set of books they happened in, beside the team. Nullable:
logins and membership changes belong to the team, not to any one book, and a
row must survive the deletion of the book it describes.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0009_alter_auditevent_event_type"),
        ("books", "0002_default_books"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditevent",
            name="book",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="books.book"
            ),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="book",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="books.book"
            ),
        ),
        migrations.AlterField(
            model_name="auditevent",
            name="event_type",
            field=models.CharField(
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
                    ("transfer_dup_resolved", "Transfer Duplicate Resolved"),
                    ("transfer_dup_dismissed", "Transfer Duplicate Dismissed"),
                    ("team_member_added", "Team Member Added"),
                    ("team_member_removed", "Team Member Removed"),
                    ("goal_funds_assigned", "Goal Funds Assigned"),
                    ("goal_funds_withdrawn", "Goal Funds Withdrawn"),
                    ("onboarding_started", "Onboarding Started"),
                    ("onboarding_phase_completed", "Onboarding Phase Completed"),
                    ("onboarding_completed", "Onboarding Questionnaire Completed"),
                    ("onboarding_skipped", "Onboarding Skipped"),
                    ("onboarding_task_completed", "Onboarding Task Completed"),
                    ("onboarding_finished", "Onboarding Finished"),
                    ("monthly_review_started", "Monthly Review Started"),
                    ("monthly_review_step_completed", "Monthly Review Step Completed"),
                    ("monthly_review_completed", "Monthly Review Completed"),
                    ("monthly_review_dismissed", "Monthly Review Dismissed"),
                    ("monthly_review_baseline_changed", "Monthly Review Baseline Changed"),
                    ("ynab_import_started", "YNAB Import Started"),
                    ("ynab_import", "YNAB Import Applied"),
                    ("data_exported", "Data Exported"),
                    ("data_wiped", "Data Wiped"),
                    ("data_imported", "Data Imported"),
                    ("reconciliation_started", "Reconciliation Started"),
                    ("reconciliation_completed", "Reconciliation Completed"),
                    ("reconciliation_undone", "Reconciliation Undone"),
                    ("book_created", "Set of Books Created"),
                    ("book_settings_changed", "Set of Books Settings Changed"),
                    ("book_archived", "Set of Books Archived"),
                    ("book_restored", "Set of Books Restored"),
                    ("book_deleted", "Set of Books Deleted"),
                ],
                max_length=50,
            ),
        ),
    ]
