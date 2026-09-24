"""
A set of books: the tenant every piece of money data belongs to.

A team owns people and billing; a book owns the chart of accounts, the journal,
the budget, goals, the bank feed and everything built from them. A team has one
or more books and nothing is shared between two of them -- no row belongs to
more than one book and no query spans two. See `docs/books-plan.md`.
"""

import logging

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.teams.models import Team
from apps.utils.models import BaseModel

from .context import EmptyBookContextException, get_current_book

DEFAULT_BOOK_NAME = "Personal"
DEFAULT_BOOK_SLUG = "personal"


class Book(BaseModel):
    """A set of books: one chart of accounts, budget and ledger inside a team."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="books")
    name = models.CharField(max_length=100)
    # Unique within the team and the second URL segment (`/a/{team}/{book}/`).
    # Derived from the name on creation and deliberately *not* changed by a
    # rename, so links survive it.
    slug = models.SlugField(max_length=50)
    # Whether income is budgeted before it arrives. On, this month's budgeted but
    # not-yet-received income counts toward Unassigned; off, money is unassigned
    # only once it has landed. Books that predate the setting were migrated to on
    # (their existing behaviour); new books default to off.
    budget_future_income = models.BooleanField(
        default=False,
        help_text=_("Budget income before it arrives: this month's expected income counts toward Unassigned."),
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = [("team", "name"), ("team", "slug")]
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    @property
    def url_args(self) -> tuple[str, str]:
        """The two slugs every book URL is reversed with: `reverse(name, args=[*book.url_args, ...])`."""
        return (self.team.slug, self.slug)

    @property
    def base_url(self) -> str:
        """`/a/{team}/{book}/` -- the prefix the frontend builds every book URL from."""
        return f"/a/{self.team.slug}/{self.slug}/"

    def get_absolute_url(self):
        return reverse("web_book:home", args=self.url_args)


class BookScopedManager(models.Manager):
    """
    Filters to the book in the current context (`apps.books.context`).

    With no book set it raises under `STRICT_BOOK_CONTEXT`, else logs and returns
    nothing -- never every book's rows. Built with `from_queryset` it keeps a
    model's own queryset methods: `BookScopedManager.from_queryset(AccountQuerySet)()`.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        book = get_current_book()
        if book is None:
            if getattr(settings, "STRICT_BOOK_CONTEXT", False):
                raise EmptyBookContextException("Book missing from context")
            logging.warning("Book not available in filtered context. Use `set_current_book()`.")
            return queryset.none()
        return queryset.filter(book=book)


class BaseBookModel(BaseModel):
    """Abstract model for everything that belongs to one set of books."""

    book = models.ForeignKey(Book, verbose_name=_("Book"), on_delete=models.CASCADE)

    # Default unfiltered manager, for the admin and anywhere the queryset is not
    # easily customised. See https://docs.djangoproject.com/en/stable/topics/db/managers/#default-managers
    objects = models.Manager()

    # Pre-filtered to the current book.
    for_book = BookScopedManager()

    class Meta:
        abstract = True
