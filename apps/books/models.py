"""
A set of books: the tenant every piece of money data belongs to.

A team owns people and billing; a book owns the chart of accounts, the journal,
the budget, goals, the bank feed and everything built from them. A team has one
or more books and nothing is shared between two of them -- no row belongs to
more than one book and no query spans two. See `docs/books-plan.md`.
"""

import logging

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.teams.models import Team
from apps.utils.models import BaseModel

from .context import EmptyBookContextException, get_current_book

DEFAULT_BOOK_NAME = "Personal"
DEFAULT_BOOK_SLUG = "personal"
MAX_HOUSEHOLD_ADULTS = 10


class ReportTimeframe(models.TextChoices):
    """
    The range a report opens on when its address names none (`Book.report_timeframe`).

    `REPORT` keeps each report's own default (this month on the income statement,
    this year on Income & Spending, the last 12 months on net worth). "Last N months"
    are the N full months before this one, so they line up with "Last month".
    The ranges themselves are computed in `apps.reports.timeframes`.
    """

    REPORT = "report", _("Each report's own default")
    THIS_MONTH = "this_month", _("This month")
    LAST_MONTH = "last_month", _("Last month")
    LAST_3_MONTHS = "last_3_months", _("Last 3 months")
    LAST_6_MONTHS = "last_6_months", _("Last 6 months")
    LAST_12_MONTHS = "last_12_months", _("Last 12 months")
    THIS_YEAR = "this_year", _("This year")
    LAST_YEAR = "last_year", _("Last year")


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
    # `db_default` for the same reason as `household_adults` below.
    report_timeframe = models.CharField(
        max_length=20,
        choices=ReportTimeframe.choices,
        default=ReportTimeframe.REPORT,
        db_default=ReportTimeframe.REPORT,
        help_text=_("The dates a report shows when you open it."),
    )
    # How many adults share this book's net worth. Wealth rankings compare one adult
    # with another (household wealth split equally between its adults), so a couple
    # sharing one book is ranked on half of it.
    # `db_default` too: an insert that leaves the column out (a historical model in a
    # migration that predates it) still gets 1 rather than violating NOT NULL.
    household_adults = models.PositiveSmallIntegerField(
        default=1,
        db_default=1,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_HOUSEHOLD_ADULTS)],
        help_text=_("Adults who share this book's net worth, for comparing it with other people's."),
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
