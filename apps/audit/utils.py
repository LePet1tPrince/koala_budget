import threading

_thread_locals = threading.local()


def get_current_user():
    return getattr(_thread_locals, "user", None)


def set_current_user(user):
    _thread_locals.user = user


def log_event(event_type, user=None, team=None, metadata=None, request=None):
    """Create an AuditEvent. Safe to call from Celery (user/team can be None)."""
    from apps.audit.models import AuditEvent

    ip = None
    if request:
        ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR"))
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()
        if user is None:
            user = request.user if request.user.is_authenticated else None
        if team is None:
            team = getattr(request, "team", None)
    return AuditEvent.objects.create(
        event_type=event_type,
        user=user,
        team=team,
        ip_address=ip,
        metadata=metadata or {},
    )


def snapshot_journal_entry(entry):
    """Frozen snapshot of JournalEntry fields (resolves FKs to display names)."""
    return {
        "entry_date": str(entry.entry_date) if entry.entry_date else None,
        "description": entry.description,
        "status": entry.status,
        "payee": {"id": entry.payee_id, "name": entry.payee.name} if entry.payee_id else None,
    }


def snapshot_journal_line(line):
    """Frozen snapshot of JournalLine fields (resolves FKs to display names)."""
    return {
        "account": {"id": line.account_id, "name": line.account.name} if line.account_id else None,
        # Always format to 2dp so Decimal('0.00') and Decimal('0') compare equal and don't
        # produce spurious diffs when lines are re-saved for budget re-linking.
        "dr_amount": f"{line.dr_amount:.2f}",
        "cr_amount": f"{line.cr_amount:.2f}",
        "is_reconciled": line.is_reconciled,
        "is_cleared": line.is_cleared,
    }


def diff_snapshots(before, after):
    """Return only fields that changed, as {field: {before: x, after: y}}."""
    changes = {}
    all_keys = set(before) | set(after)
    for key in all_keys:
        b = before.get(key)
        a = after.get(key)
        if b != a:
            changes[key] = {"before": b, "after": a}
    return changes
