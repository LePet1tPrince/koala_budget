from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.audit.models import AuditEvent, AuditLog
from apps.audit.utils import (
    diff_snapshots,
    get_current_user,
    log_event,
    snapshot_journal_entry,
    snapshot_journal_line,
)
from apps.journal.models import JournalEntry, JournalLine

# ---- JournalEntry signals ----


@receiver(pre_save, sender=JournalEntry)
def journal_entry_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = JournalEntry.objects.select_related("payee").get(pk=instance.pk)
            instance._pre_save_state = snapshot_journal_entry(old)
        except JournalEntry.DoesNotExist:
            instance._pre_save_state = None
    else:
        instance._pre_save_state = None


@receiver(post_save, sender=JournalEntry)
def journal_entry_post_save(sender, instance, created, **kwargs):
    ct = ContentType.objects.get_for_model(JournalEntry)
    user = get_current_user()
    if created:
        AuditLog.objects.create(
            content_type=ct,
            object_id=instance.pk,
            journal_entry_id=instance.pk,
            team=instance.team,
            user=user,
            action=AuditLog.ACTION_CREATE,
            source_model="JournalEntry",
            changes={"snapshot": snapshot_journal_entry(instance)},
        )
    else:
        before = getattr(instance, "_pre_save_state", None)
        if before is not None:
            changes = diff_snapshots(before, snapshot_journal_entry(instance))
            if changes:
                AuditLog.objects.create(
                    content_type=ct,
                    object_id=instance.pk,
                    journal_entry_id=instance.pk,
                    team=instance.team,
                    user=user,
                    action=AuditLog.ACTION_UPDATE,
                    source_model="JournalEntry",
                    changes=changes,
                )


@receiver(post_delete, sender=JournalEntry)
def journal_entry_post_delete(sender, instance, **kwargs):
    ct = ContentType.objects.get_for_model(JournalEntry)
    AuditLog.objects.create(
        content_type=ct,
        object_id=instance.pk,
        journal_entry_id=instance.pk,
        team=instance.team,
        user=get_current_user(),
        action=AuditLog.ACTION_DELETE,
        source_model="JournalEntry",
        changes={"snapshot": snapshot_journal_entry(instance)},
    )


# ---- JournalLine signals ----


@receiver(pre_save, sender=JournalLine)
def journal_line_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = JournalLine.objects.select_related("account").get(pk=instance.pk)
            instance._pre_save_state = snapshot_journal_line(old)
        except JournalLine.DoesNotExist:
            instance._pre_save_state = None
    else:
        instance._pre_save_state = None


@receiver(post_save, sender=JournalLine)
def journal_line_post_save(sender, instance, created, **kwargs):
    ct = ContentType.objects.get_for_model(JournalLine)
    user = get_current_user()
    entry_id = instance.journal_entry_id
    if created:
        AuditLog.objects.create(
            content_type=ct,
            object_id=instance.pk,
            journal_entry_id=entry_id,
            team=instance.team,
            user=user,
            action=AuditLog.ACTION_CREATE,
            source_model="JournalLine",
            changes={"snapshot": snapshot_journal_line(instance)},
        )
    else:
        before = getattr(instance, "_pre_save_state", None)
        if before is not None:
            changes = diff_snapshots(before, snapshot_journal_line(instance))
            if changes:
                AuditLog.objects.create(
                    content_type=ct,
                    object_id=instance.pk,
                    journal_entry_id=entry_id,
                    team=instance.team,
                    user=user,
                    action=AuditLog.ACTION_UPDATE,
                    source_model="JournalLine",
                    changes=changes,
                )


@receiver(post_delete, sender=JournalLine)
def journal_line_post_delete(sender, instance, **kwargs):
    ct = ContentType.objects.get_for_model(JournalLine)
    AuditLog.objects.create(
        content_type=ct,
        object_id=instance.pk,
        journal_entry_id=instance.journal_entry_id,
        team=instance.team,
        user=get_current_user(),
        action=AuditLog.ACTION_DELETE,
        source_model="JournalLine",
        changes={"snapshot": snapshot_journal_line(instance)},
    )


# ---- Auth event signals ----


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    log_event(AuditEvent.USER_LOGIN, user=user, request=request, metadata={"email": user.email})


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    if user:
        log_event(AuditEvent.USER_LOGOUT, user=user, request=request, metadata={"email": user.email})


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request=None, **kwargs):
    log_event(
        AuditEvent.LOGIN_FAILED,
        request=request,
        metadata={"username": credentials.get("email", credentials.get("username", ""))},
    )
