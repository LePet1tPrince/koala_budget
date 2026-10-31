"""
What a bank connection needs from the user.

A Plaid item stops syncing for reasons only the user can fix: the bank wants
them to sign in again (ITEM_LOGIN_REQUIRED), their consent is about to run out
(PENDING_EXPIRATION), they withdrew access at the bank (USER_PERMISSION_REVOKED),
or the bank has accounts they haven't shared yet (NEW_ACCOUNTS_AVAILABLE). Plaid
says so through ITEM webhooks and through the errors a sync hits; both land
here, on `PlaidItem.status`, so the Inbox can ask the user to reconnect through
Link's update mode instead of the feed silently going stale.
"""

import logging

from django.utils.dateparse import parse_datetime

from apps.audit.models import AuditEvent
from apps.audit.utils import log_event

from .models import PlaidItem

logger = logging.getLogger(__name__)

#: Item errors that Link's update mode fixes: the user signs in (again) at the bank.
LOGIN_REQUIRED_CODES = frozenset(
    {
        "ITEM_LOGIN_REQUIRED",
        "INVALID_CREDENTIALS",
        "INVALID_MFA",
        "INVALID_SEND_METHOD",
        "INSUFFICIENT_CREDENTIALS",
        "ITEM_LOCKED",
        "USER_SETUP_REQUIRED",
        "PASSWORD_RESET_REQUIRED",
    }
)

#: The connection is gone at Plaid or the bank; it has to be linked again.
REVOKED_CODES = frozenset({"ACCESS_NOT_GRANTED", "ITEM_NOT_FOUND", "INVALID_ACCESS_TOKEN", "USER_PERMISSION_REVOKED"})

#: Not a problem with the connection -- try again on the next sync.
TRANSIENT_CODES = frozenset(
    {"PRODUCT_NOT_READY", "INSTITUTION_DOWN", "INSTITUTION_NOT_RESPONDING", "INSTITUTION_NOT_AVAILABLE"}
)

#: Other ITEM errors that stop syncing until something changes.
OTHER_ITEM_CODES = frozenset(
    {"NO_ACCOUNTS", "ITEM_NOT_SUPPORTED", "MFA_NOT_SUPPORTED", "INSTITUTION_NO_LONGER_SUPPORTED"}
)


def status_for_error(error_code) -> str | None:
    """The item status an error code means, or None when it says nothing about the item."""
    if error_code in LOGIN_REQUIRED_CODES:
        return PlaidItem.STATUS_LOGIN_REQUIRED
    if error_code in REVOKED_CODES:
        return PlaidItem.STATUS_REVOKED
    if error_code in OTHER_ITEM_CODES:
        return PlaidItem.STATUS_ERROR
    return None


def set_status(item, status, *, error_code="", error_message="", **extra):
    """Record `status` on the item, auditing the change (a repeat is not a change)."""
    previous = item.status
    item.status = status
    item.error_code = error_code or ""
    item.error_message = error_message or ""
    fields = ["status", "error_code", "error_message", "updated_at"]
    for name, value in extra.items():
        setattr(item, name, value)
        fields.append(name)
    item.save(update_fields=fields)
    if previous != status:
        log_event(
            AuditEvent.PLAID_ITEM_STATUS_CHANGED,
            book=item.book,
            metadata={"plaid_item_id": item.pk, "from": previous, "to": status, "error_code": error_code or None},
        )


def record_error(item, error_code, error_message="") -> bool:
    """Record a sync error on the item; False when the code isn't about the item."""
    status = status_for_error(error_code)
    if status is None:
        return False
    set_status(item, status, error_code=error_code, error_message=error_message)
    return True


def record_sync_success(item):
    """A sync went through, so the connection works -- clear what said otherwise."""
    if item.status in (PlaidItem.STATUS_LOGIN_REQUIRED, PlaidItem.STATUS_REVOKED, PlaidItem.STATUS_ERROR):
        set_status(item, PlaidItem.STATUS_HEALTHY)


def record_reconnected(item):
    """The user went through Link's update mode: consent renewed, accounts re-shared."""
    set_status(item, PlaidItem.STATUS_HEALTHY, consent_expiration_time=None, new_accounts_available=False)


def handle_item_webhook(item, webhook_code, payload) -> bool:
    """
    Apply an ITEM webhook to the item. Returns True when the item can sync now
    (LOGIN_REPAIRED), so the caller queues one.
    """
    if webhook_code == "ERROR":
        error = payload.get("error") or {}
        code = error.get("error_code") or ""
        message = error.get("display_message") or error.get("error_message") or ""
        if not record_error(item, code, message):
            logger.warning("Plaid item %s reported error %s", item.pk, code)
    elif webhook_code == "PENDING_EXPIRATION":
        expires = payload.get("consent_expiration_time")
        set_status(
            item,
            PlaidItem.STATUS_PENDING_EXPIRATION,
            consent_expiration_time=parse_datetime(expires) if isinstance(expires, str) else None,
        )
    elif webhook_code == "PENDING_DISCONNECT":
        set_status(item, PlaidItem.STATUS_PENDING_DISCONNECT, error_message=payload.get("reason") or "")
    elif webhook_code == "USER_PERMISSION_REVOKED":
        set_status(item, PlaidItem.STATUS_REVOKED, error_code="USER_PERMISSION_REVOKED")
    elif webhook_code == "LOGIN_REPAIRED":
        set_status(item, PlaidItem.STATUS_HEALTHY)
        return True
    elif webhook_code == "NEW_ACCOUNTS_AVAILABLE":
        item.new_accounts_available = True
        item.save(update_fields=["new_accounts_available", "updated_at"])
    return False
