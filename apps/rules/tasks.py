"""Celery tasks for transaction rules."""

import logging

from celery import shared_task

from apps.books.context import set_current_book, unset_current_book
from apps.books.models import Book

from .services.learning import active_book_ids, propose

logger = logging.getLogger(__name__)


@shared_task
def learn_rules():
    """Refresh every active book's proposed rules (SCHEDULED_TASKS["learn-rules"])."""
    proposed = 0
    for book in Book.objects.filter(pk__in=active_book_ids(), is_archived=False):
        token = set_current_book(book)
        try:
            proposed += propose(book)
        except Exception:
            logger.exception("Rules: learning failed for book %s", book.pk)
        finally:
            unset_current_book(token)
    return proposed
