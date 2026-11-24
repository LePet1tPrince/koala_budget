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

# ---- JournalEntry / JournalLine signals ----

# model -> (snapshot function, relation the snapshot reads)
SNAPSHOTS = {
    JournalEntry: (snapshot_journal_entry, "payee"),
    JournalLine: (snapshot_journal_line, "account"),
}


def _log(sender, instance, action, changes):
    AuditLog.objects.create(
        content_type=ContentType.objects.get_for_model(sender),
        object_id=instance.pk,
        journal_entry_id=instance.pk if sender is JournalEntry else instance.journal_entry_id,
        team_id=instance.book.team_id,
        book_id=instance.book_id,
        user=get_current_user(),
        action=action,
        source_model=sender.__name__,
        changes=changes,
    )


def remember_state(sender, instance, **kwargs):
    snapshot, related = SNAPSHOTS[sender]
    old = sender.objects.select_related(related).filter(pk=instance.pk).first() if instance.pk else None
    instance._pre_save_state = snapshot(old) if old else None


def log_save(sender, instance, created, **kwargs):
    snapshot = SNAPSHOTS[sender][0]
    if created:
        _log(sender, instance, AuditLog.ACTION_CREATE, {"snapshot": snapshot(instance)})
        return
    before = getattr(instance, "_pre_save_state", None)
    changes = diff_snapshots(before, snapshot(instance)) if before is not None else None
    if changes:
        _log(sender, instance, AuditLog.ACTION_UPDATE, changes)


def log_delete(sender, instance, **kwargs):
    _log(sender, instance, AuditLog.ACTION_DELETE, {"snapshot": SNAPSHOTS[sender][0](instance)})


for _model in SNAPSHOTS:
    pre_save.connect(remember_state, sender=_model)
    post_save.connect(log_save, sender=_model)
    post_delete.connect(log_delete, sender=_model)


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
