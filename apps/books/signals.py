from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.teams.models import Team

from .helpers import ensure_default_book


@receiver(post_save, sender=Team)
def create_default_book_on_team_create(sender, instance, created, raw=False, **kwargs):
    """
    Every team has at least one set of books, from the moment it exists.

    `bootstrap_team_on_create` also calls `ensure_default_book`, since it needs
    the book to apply the starter chart of accounts to and signal receivers run
    in registration order; whichever runs first creates it.
    """
    if created and not raw:
        ensure_default_book(instance)
