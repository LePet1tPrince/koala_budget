"""Celery tasks that send email, so a webhook or a sync never waits on the mail server."""

import logging

from celery import shared_task

from apps.books.context import set_current_book, unset_current_book

from . import alerts

logger = logging.getLogger(__name__)

# A send that fails leaves no record (`services.send`), so a retry sends it.
RETRY = {"autoretry_for": (Exception,), "retry_backoff": 60, "max_retries": 3}


@shared_task(**RETRY)
def send_bank_connection_alert(item_id, status):
    return alerts.bank_connection(item_id, status)


BILLING_HANDLERS = {
    "customer.subscription.trial_will_end": alerts.trial_ending,
    "invoice.payment_failed": alerts.payment_failed,
    "invoice.upcoming": alerts.renewal_upcoming,
}


@shared_task(**RETRY)
def send_billing_email(event_type, stripe_object):
    return BILLING_HANDLERS[event_type](stripe_object)


@shared_task
def send_overspend_alerts():
    """Every open book with a budget (SCHEDULED_TASKS["overspend-alerts"]). Returns emails sent."""
    from apps.books.models import Book

    sent = 0
    for book in Book.objects.filter(is_archived=False).select_related("team"):
        token = set_current_book(book)
        try:
            sent += alerts.budget_overspent(book)
        except Exception:
            logger.exception("Emails: overspend alert failed for book %s", book.pk)
        finally:
            unset_current_book(token)
    return sent
