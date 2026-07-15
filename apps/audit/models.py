from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db import models


class AuditEvent(models.Model):
    """
    Operation-level audit events (logins, CSV uploads, Plaid syncs, bulk operations).

    Plain ``models.Model`` (not ``BaseTeamModel``) because events can originate
    from contexts without a team (e.g. failed logins) and must tolerate a null team.
    """

    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    LOGIN_FAILED = "login_failed"
    CSV_UPLOAD_STARTED = "csv_upload_started"
    CSV_UPLOAD_COMPLETED = "csv_upload_completed"
    CSV_UPLOAD_FAILED = "csv_upload_failed"
    PLAID_SYNC_STARTED = "plaid_sync_started"
    PLAID_SYNC_COMPLETED = "plaid_sync_completed"
    PLAID_SYNC_FAILED = "plaid_sync_failed"
    BULK_CATEGORIZE = "bulk_categorize"
    BULK_EDIT = "bulk_edit"
    BULK_RECONCILE = "bulk_reconcile"
    BULK_UNRECONCILE = "bulk_unreconcile"
    BULK_ARCHIVE = "bulk_archive"
    BULK_UNARCHIVE = "bulk_unarchive"
    BULK_DELETE = "bulk_delete"
    BULK_DUPLICATE = "bulk_duplicate"
    TRANSFER_DUP_RESOLVED = "transfer_dup_resolved"
    TRANSFER_DUP_DISMISSED = "transfer_dup_dismissed"
    TEAM_MEMBER_ADDED = "team_member_added"
    TEAM_MEMBER_REMOVED = "team_member_removed"
    GOAL_FUNDS_ASSIGNED = "goal_funds_assigned"
    GOAL_FUNDS_WITHDRAWN = "goal_funds_withdrawn"

    EVENT_TYPE_CHOICES = [
        (USER_LOGIN, "User Login"),
        (USER_LOGOUT, "User Logout"),
        (LOGIN_FAILED, "Login Failed"),
        (CSV_UPLOAD_STARTED, "CSV Upload Started"),
        (CSV_UPLOAD_COMPLETED, "CSV Upload Completed"),
        (CSV_UPLOAD_FAILED, "CSV Upload Failed"),
        (PLAID_SYNC_STARTED, "Plaid Sync Started"),
        (PLAID_SYNC_COMPLETED, "Plaid Sync Completed"),
        (PLAID_SYNC_FAILED, "Plaid Sync Failed"),
        (BULK_CATEGORIZE, "Bulk Categorize"),
        (BULK_EDIT, "Bulk Edit"),
        (BULK_RECONCILE, "Bulk Reconcile"),
        (BULK_UNRECONCILE, "Bulk Unreconcile"),
        (BULK_ARCHIVE, "Bulk Archive"),
        (BULK_UNARCHIVE, "Bulk Unarchive"),
        (BULK_DELETE, "Bulk Delete"),
        (BULK_DUPLICATE, "Bulk Duplicate"),
        (TRANSFER_DUP_RESOLVED, "Transfer Duplicate Resolved"),
        (TRANSFER_DUP_DISMISSED, "Transfer Duplicate Dismissed"),
        (TEAM_MEMBER_ADDED, "Team Member Added"),
        (TEAM_MEMBER_REMOVED, "Team Member Removed"),
        (GOAL_FUNDS_ASSIGNED, "Goal Funds Assigned"),
        (GOAL_FUNDS_WITHDRAWN, "Goal Funds Withdrawn"),
    ]

    team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPE_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Audit Event"
        verbose_name_plural = "Audit Events"

    def __str__(self):
        return f"{self.event_type} @ {self.timestamp:%Y-%m-%d %H:%M:%S}"


class AuditLog(models.Model):
    """
    Row-level field-diff audit for JournalEntry and JournalLine changes.

    Plain ``models.Model`` (not ``BaseTeamModel``) because the team must be nullable
    so a delete that races a team teardown still records cleanly.
    """

    ACTION_CREATE = "CREATE"
    ACTION_UPDATE = "UPDATE"
    ACTION_DELETE = "DELETE"

    ACTION_CHOICES = [
        (ACTION_CREATE, "Create"),
        (ACTION_UPDATE, "Update"),
        (ACTION_DELETE, "Delete"),
    ]

    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.SET_NULL, null=True)
    object_id = models.PositiveIntegerField(null=True)
    content_object = GenericForeignKey("content_type", "object_id")
    # Denormalized for fast "show history for this entry" queries (lines point at their entry too).
    journal_entry_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    event = models.ForeignKey("AuditEvent", on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    changes = models.JSONField(default=dict)
    source_model = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["journal_entry_id", "timestamp"], name="audit_audit_journal_3c3d8e_idx"),
        ]

    def __str__(self):
        return f"{self.action} {self.source_model} #{self.object_id}"
