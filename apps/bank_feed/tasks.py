"""Celery tasks for the bank feed."""

from celery import shared_task

from .services.recurring import materialize_due


@shared_task
def generate_recurring_transactions():
    """Write every recurring transaction due by today (SCHEDULED_TASKS["recurring-transactions"])."""
    return materialize_due()
